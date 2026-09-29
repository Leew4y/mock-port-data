"""Baseline linehaul dispatch: each line loads only its own orders into its own standard trucks. When one truck is
not enough, the extra truck is hired at the smallest size that fits what is left (at least 6.8m on long routes).
A line with a single truck that day still runs its own standard truck, however empty.

This is the "today" practice the rehearsal team is meant to beat (skeleton B pools lines to the same city).
"""

from __future__ import annotations

import pandas as pd

from . import reference as ref
from .config import Config


OVERFLOW_SIZES = ["4.2m", "6.8m", "9.6m", "13m", "17.5m"]


def conflicts(classes: set, categories: set) -> list[str]:
    """Illustrative incompatible pairs present in one vehicle (NOT the JT/T 617.6 table)."""
    present = set(classes) | set(categories)
    return [f"{a}+{b}" for a, b in ref.ILLUSTRATIVE_INCOMPATIBLE if a in present and b in present]


def first_fit_decreasing(orders: pd.DataFrame, cap_kg: float, cap_m3: float) -> list[list[int]]:
    """Pack order rows (by index) into bins; returns list of bins of row indices."""
    ordered = orders.sort_values(["volume_m3", "order_id"], ascending=[False, True])
    bins: list[list[int]] = []
    loads: list[list[float]] = []
    for idx, w, v in zip(ordered.index, ordered["weight_kg"], ordered["volume_m3"]):
        if w > cap_kg or v > cap_m3:
            raise ValueError(f"order row {idx} does not fit one vehicle")
        for b, (lw, lv) in enumerate(loads):
            if lw + w <= cap_kg and lv + v <= cap_m3:
                bins[b].append(idx)
                loads[b][0] += w
                loads[b][1] += v
                break
        else:
            bins.append([idx])
            loads.append([w, v])
    return bins


def _squeeze_small_overflow(orders, bins, cap_kg, vol, small_m3=3.0):
    """A leftover under small_m3 is squeezed into earlier trucks up to their full volume instead of a new truck."""
    if len(bins) < 2:
        return bins
    last = orders.loc[bins[-1]]
    if float(last["volume_m3"].sum()) >= small_m3:
        return bins
    kept = [list(b) for b in bins[:-1]]
    loads = [[float(orders.loc[b, "weight_kg"].sum()), float(orders.loc[b, "volume_m3"].sum())] for b in kept]
    for idx, w, v in zip(last.index, last["weight_kg"], last["volume_m3"]):
        for b, (lw, lv) in enumerate(loads):
            if lw + w <= cap_kg and lv + v <= vol:
                kept[b].append(idx)
                loads[b][0] += w
                loads[b][1] += v
                break
        else:
            return bins
    return kept


def baseline_dispatch(cfg: Config, lines: pd.DataFrame, orders: pd.DataFrame):
    """Return (trucks, order_to_truck Series indexed like orders)."""
    line_info = lines.set_index("line_id")
    truck_rows = []
    assign = pd.Series("", index=orders.index, dtype=object)
    for (date, lid), grp in orders.groupby(["date", "line_id"], sort=True):
        info = line_info.loc[lid]
        vt = info["standard_vehicle"]
        _, cap_kg, vol = ref.VEHICLE_TYPES[vt]
        bins = first_fit_decreasing(grp, cap_kg, vol * cfg.volume_fill_limit)
        bins = _squeeze_small_overflow(orders, bins, cap_kg, vol)
        for k, rows in enumerate(bins, start=1):
            sub = orders.loc[rows]
            vt_k, cap_kg_k, vol_k = vt, cap_kg, vol
            if k == len(bins) > 1:  # the overflow truck is hired at the smallest size that fits
                w_, v_ = float(sub["weight_kg"].sum()), float(sub["volume_m3"].sum())
                first = 0 if info["distance_km"] <= cfg.min_overflow_km_for_small_truck else 1
                for cand in OVERFLOW_SIZES[first : OVERFLOW_SIZES.index(vt) + 1]:
                    _, ck, cv = ref.VEHICLE_TYPES[cand]
                    if w_ <= ck and v_ <= cv * cfg.volume_fill_limit:
                        vt_k, cap_kg_k, vol_k = cand, ck, cv
                        break
            tid = f"T{date[5:7]}{date[8:10]}-{lid}-{k}"
            assign.loc[rows] = tid
            classes = {c for c in sub["hazmat_class"] if c}
            cats = set(sub["category"])
            found = conflicts(classes, cats)
            w, v = float(sub["weight_kg"].sum()), float(sub["volume_m3"].sum())
            truck_rows.append(
                {
                    "truck_id": tid,
                    "date": date,
                    "line_id": lid,
                    "destination": info["destination"],
                    "vehicle_type": vt_k,
                    "n_orders": len(sub),
                    "weight_kg": round(w, 1),
                    "volume_m3": round(v, 2),
                    "load_factor_volume": round(v / vol_k, 3),
                    "load_factor_weight": round(w / cap_kg_k, 3),
                    "load_factor": round(max(v / vol_k, w / cap_kg_k), 3),
                    "hazmat_classes": ";".join(sorted(classes)),
                    "illustrative_conflicts": ";".join(found),
                    "planned_departure": f"{date} {info['departure_time']}:00",
                    "x_truck_no": k,
                    "x_hired": k == len(bins) > 1,
                }
            )
    return pd.DataFrame(truck_rows), assign
