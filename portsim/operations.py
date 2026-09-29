"""Truck visits to docks (four operation types), with appointments and actual gate arrivals.

Times are integer minutes since start_date 00:00 until build.py converts them.

delivery_in   shipper vans drop LTL orders at the line's dock (daytime)
linehaul_out  the line's trucks load the day's orders and leave (evening); loading waits for every order on the
              truck to be unloaded from its delivery van
linehaul_in   trucks from the destination side arrive and unload (early morning)
pickup_out    local vans collect the unloaded goods for delivery (morning); each van loads from one inbound truck
              and waits for it to be unloaded

A visit's `after` lists the visits it waits for (op ids joined by ";"); docksim.py enforces it.
Local van plates are left empty here and issued after the dock simulation (assign_local_plates), so that one van
is never at the port twice at the same time.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import reference as ref
from .config import Config
from .entities import IN_FLEET, OUT_FLEET, PlateBook


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _profile_minute(rng: np.random.Generator, op_type: str) -> int:
    first, weights = ref.ARRIVAL_PROFILE[op_type]
    p = np.array(weights, dtype=float)
    hour = first + int(rng.choice(len(p), p=p / p.sum()))
    return hour * 60 + int(rng.integers(0, 60))


def _fits(vt: str, w: float, v: float, fill: float) -> bool:
    _, cap_kg, vol = ref.VEHICLE_TYPES[vt]
    return w <= cap_kg and v <= vol * fill


class _Ops:
    def __init__(self, cfg: Config, rng: np.random.Generator):
        self.cfg, self.rng, self.rows = cfg, rng, []

    def add(self, *, date, line, op_type, planned, vehicle, plate, volume, n_orders, ref_id="", after=(), due=None):
        rng, cfg = self.rng, self.cfg
        op_id = f"E{len(self.rows) + 1:06d}"
        has_appt = bool(rng.random() < ref.APPOINTMENT_SHARE[op_type])
        mu, sd = ref.ARRIVAL_DELAY[op_type]
        delay = rng.normal(mu, sd)
        if op_type == "linehaul_in" and rng.random() < 0.06:
            delay += rng.uniform(60, 240)
        no_show = bool(has_appt and op_type == "pickup_out" and rng.random() < cfg.p_no_show)
        hazmat = bool(line.hazmat_qualified)
        service = (ref.SERVICE_SETUP_MIN + ref.SERVICE_RATE_MIN_PER_M3[op_type] * volume * rng.lognormal(0.0, 0.25)
                   + (10 if hazmat else 0))
        exit_min = int(rng.integers(5, 16))
        if has_appt:
            slot_start = planned - planned % 30
            gate_in = None if no_show else planned + int(round(float(np.clip(delay, -45, 300))))
        else:
            slot_start = None
            gate_in = planned
        self.rows.append(
            {
                "op_id": op_id,
                "date": date,
                "line_id": line.line_id,
                "op_type": op_type,
                "vehicle_type": vehicle,
                "plate": plate,
                "cargo_volume_m3": round(float(volume), 2),
                "n_orders": n_orders,
                "hazmat": hazmat,
                "ref_id": ref_id,
                "appointment_id": f"A{op_id[1:]}" if has_appt else "",
                "slot_start": slot_start,
                "slot_end": None if slot_start is None else slot_start + 30,
                "planned": planned,
                "no_show": no_show,
                "gate_in": gate_in,
                "service_min": max(5, int(round(service))),
                "exit_min": exit_min,
                "after": ";".join(after),
                "due": due,
            }
        )
        return op_id


def make_operations(cfg, lines, orders, trucks, order_truck, book: PlateBook, rng):
    """Return (ops, dropoff_op Series indexed like orders)."""
    ops = _Ops(cfg, rng)
    dropoff = pd.Series("", index=orders.index, dtype=object)
    orders_by = {k: g for k, g in orders.groupby(["date", "line_id"], sort=True)}
    trucks_by = {k: g for k, g in trucks.groupby(["date", "line_id"], sort=True)}
    fill = cfg.volume_fill_limit
    days = pd.date_range(cfg.start_date, periods=cfg.days, freq="D")
    hired: dict[tuple, list[str]] = {}  # (line, vehicle type) -> plates of trucks hired for overflow

    for di, day in enumerate(days):
        date = day.strftime("%Y-%m-%d")
        base = di * 1440
        for line in lines.itertuples(index=False):
            key = (date, line.line_id)
            out_fleet, in_fleet = line.x_fleet[:OUT_FLEET], line.x_fleet[OUT_FLEET:OUT_FLEET + IN_FLEET]

            g = orders_by.get(key)
            if g is not None:
                perm = rng.permutation(g.index.to_numpy())
                i = 0
                while i < len(perm):
                    size = min(1 + int(rng.poisson(0.8)), 4, len(perm) - i)
                    while size > 1 and not _fits("9.6m", *_sums(orders, perm[i : i + size]), fill):
                        size -= 1
                    idx = perm[i : i + size]
                    i += size
                    w, v = _sums(orders, idx)
                    vt = next(t for t in ref.SMALL_VEHICLES if _fits(t, w, v, fill))
                    op_id = ops.add(
                        date=date, line=line, op_type="delivery_in", planned=base + _profile_minute(rng, "delivery_in"),
                        vehicle=vt, plate="", volume=v, n_orders=len(idx),
                    )
                    dropoff.loc[idx] = op_id

            tg = trucks_by.get(key)
            dep = _hhmm(line.departure_time)
            n_out = 0 if tg is None else len(tg)
            if tg is not None:
                for t in tg.itertuples(index=False):
                    if t.x_hired:
                        pool = hired.setdefault((line.line_id, t.vehicle_type), [])
                        if len(pool) < 3:
                            pool.append(book.new(rng, line.x_prefix))
                        plate = pool[di % len(pool)]
                    else:
                        plate = out_fleet[(t.x_truck_no - 1) % len(out_fleet)]
                    cargo = sorted(set(dropoff.loc[order_truck.index[order_truck == t.truck_id]]))
                    ops.add(
                        date=date, line=line, op_type="linehaul_out",
                        planned=base + dep - ref.LOADING_LEAD_MIN + int(rng.integers(-20, 21)),
                        vehicle=t.vehicle_type, plate=plate, volume=t.volume_m3, n_orders=t.n_orders,
                        ref_id=t.truck_id, after=cargo, due=base + dep,
                    )

            n_in = max(1, int(round(max(1, n_out) * rng.uniform(0.7, 1.3))))
            vol_std = ref.VEHICLE_TYPES[line.standard_vehicle][2]
            per_van_max = ref.VEHICLE_TYPES["6.8m"][2] * fill
            for j in range(n_in):
                v_in = vol_std * fill * rng.beta(6, 3)
                planned_in = base + _profile_minute(rng, "linehaul_in")
                in_id = ops.add(
                    date=date, line=line, op_type="linehaul_in", planned=planned_in,
                    vehicle=line.standard_vehicle, plate=in_fleet[j % len(in_fleet)], volume=v_in, n_orders=0,
                )
                # the goods of one inbound truck leave in local vans booked for after its expected unloading
                n_vans = max(1, int(round(v_in / rng.uniform(8, 14))), math.ceil(v_in / per_van_max))
                v = v_in / n_vans
                unloaded = planned_in + cfg.approach_min + ref.SERVICE_SETUP_MIN + ref.SERVICE_RATE_MIN_PER_M3["linehaul_in"] * v_in
                for _ in range(n_vans):
                    small_ok = v <= ref.VEHICLE_TYPES["4.2m"][2] * fill
                    vt = "4.2m" if (small_ok and rng.random() < 0.8) else "6.8m"
                    planned = max(base + _profile_minute(rng, "pickup_out"), int(unloaded) + int(rng.integers(0, 61)))
                    ops.add(
                        date=date, line=line, op_type="pickup_out", planned=planned,
                        vehicle=vt, plate="", volume=v, n_orders=0, after=(in_id,),
                    )

    return pd.DataFrame(ops.rows), dropoff


def assign_local_plates(cfg: Config, ops: pd.DataFrame, sim: pd.DataFrame, book: PlateBook, rng) -> pd.DataFrame:
    """Issue local van plates after the dock simulation: a van is reused only once it has left the port and
    local_van_turnaround_min has passed, and each plate keeps one vehicle type."""
    ops = ops.copy()
    local = ops["op_type"].isin(["delivery_in", "pickup_out"])
    times = sim.set_index("op_id")[["gate_in", "gate_out"]].rename(columns={"gate_in": "g_in", "gate_out": "g_out"})
    shown = ops[local & ops["gate_in"].notna()].join(times, on="op_id").sort_values(["g_in", "op_id"])
    pools: dict[str, list[list]] = {}  # vehicle type -> [plate, free from minute]
    for r in shown.itertuples():
        pool = pools.setdefault(r.vehicle_type, [])
        free = [i for i, (_, t) in enumerate(pool) if t <= r.g_in]
        if free and rng.random() < 0.9:  # mostly vans already seen; now and then a new one
            i = free[int(rng.integers(len(free)))]
        else:
            pool.append([book.new(rng, ref.LOCAL_PLATE_PREFIX), 0])
            i = len(pool) - 1
        pool[i][1] = int(r.g_out) + cfg.local_van_turnaround_min
        ops.at[r.Index, "plate"] = pool[i][0]
    for idx in ops.index[local & ops["gate_in"].isna()]:  # no-shows: a van that exists, it just never came
        pool = pools.setdefault(ops.at[idx, "vehicle_type"], [])
        if not pool:
            pool.append([book.new(rng, ref.LOCAL_PLATE_PREFIX), 0])
        ops.at[idx, "plate"] = pool[int(rng.integers(len(pool)))][0]
    return ops


def _sums(orders: pd.DataFrame, idx) -> tuple[float, float]:
    sub = orders.loc[idx]
    return float(sub["weight_kg"].sum()), float(sub["volume_m3"].sum())
