"""Lines (tenants), docks, licence plates and LTL orders."""

from __future__ import annotations

import math
import string

import numpy as np
import pandas as pd

from . import reference as ref
from .config import Config

# a general line runs the smallest truck whose usable volume covers its expected day (m3 limits)
STANDARD_VEHICLE_LIMITS = [("6.8m", 30), ("9.6m", 45), ("13m", 65)]
# a hazmat line's goods are dense, so its truck is sized by expected weight (kg limits)
HAZMAT_MEAN_ORDER_KG = 380
HAZMAT_VEHICLE_LIMITS = [("6.8m", 6_000), ("9.6m", 12_000)]
OUT_FLEET, IN_FLEET = 6, 6  # a line's own trucks: those loading here, and those arriving from the destination side
PLATE_CHARS = [c for c in string.ascii_uppercase if c not in "IO"] + list(string.digits) * 3


class PlateBook:
    """Every plate in the dataset is issued here, so no two vehicles share one."""

    def __init__(self):
        self.issued: set[str] = set()

    def new(self, rng: np.random.Generator, prefix: str) -> str:
        while True:
            plate = prefix + "".join(rng.choice(PLATE_CHARS, size=5))
            if plate not in self.issued:
                self.issued.add(plate)
                return plate


def make_lines(cfg: Config, rng: np.random.Generator, book: PlateBook) -> pd.DataFrame:
    n_dest = len(ref.DESTINATIONS)
    base = list(range(n_dest)) * (cfg.n_general_lines // n_dest)
    extra = rng.choice(n_dest, size=cfg.n_general_lines - len(base), replace=False).tolist()
    general_dests = sorted(base + extra)
    hazmat_dests = sorted(rng.choice(n_dest, size=cfg.n_hazmat_lines, replace=False).tolist())

    factor = rng.lognormal(0.0, 0.5, size=cfg.n_general_lines)
    factor = factor / factor.mean()
    general_lam = np.clip(cfg.mean_orders_per_line_day * factor, 6, 70)
    hazmat_lam = np.clip(cfg.mean_orders_per_line_day * 0.4 * rng.lognormal(0.0, 0.3, size=cfg.n_hazmat_lines), 4, 20)

    rows = []
    letters_used: dict[int, int] = {}
    specs = [(d, lam, False) for d, lam in zip(general_dests, general_lam)]
    specs += [(d, lam, True) for d, lam in zip(hazmat_dests, hazmat_lam)]
    for i, (d, lam, hazmat) in enumerate(specs, start=1):
        city, _, _, km, plate_prefix = ref.DESTINATIONS[d]
        k = letters_used.get(d, 0)
        letters_used[d] = k + 1
        if hazmat:
            expected_kg = lam * HAZMAT_MEAN_ORDER_KG
            vehicle = next((vt for vt, limit in HAZMAT_VEHICLE_LIMITS if expected_kg <= limit), "13m")
            name = f"{city}危险品专线"
        else:
            expected_m3 = lam * cfg.mean_order_volume_m3
            vehicle = next((vt for vt, limit in STANDARD_VEHICLE_LIMITS if expected_m3 <= limit), "17.5m")
            name = f"{city}专线{string.ascii_uppercase[k]}"
        fleet = [book.new(rng, plate_prefix) for _ in range(OUT_FLEET + IN_FLEET)]
        rows.append(
            {
                "line_id": f"L{i:02d}",
                "line_name": name,
                "destination": city,
                "distance_km": km,
                "hazmat_qualified": hazmat,
                "standard_vehicle": vehicle,
                "departure_time": str(rng.choice(ref.DEPARTURE_TIMES)),
                "x_lam": float(lam),
                "x_prefix": plate_prefix,
                "x_fleet": fleet,
            }
        )
    return pd.DataFrame(rows)


def make_docks(cfg: Config, lines: pd.DataFrame) -> pd.DataFrame:
    general = lines[~lines["hazmat_qualified"]].copy()
    owned = {lid: 1 for lid in general["line_id"]}
    spare = cfg.n_general_docks - len(general)
    if spare < 0:
        raise ValueError("fewer general docks than general lines")
    by_size = general.sort_values(["x_lam", "line_id"], ascending=[False, True])["line_id"].tolist()
    for j in range(spare):
        owned[by_size[j % len(by_size)]] += 1

    rows = []
    n = 0
    for lid in general["line_id"]:
        for _ in range(owned[lid]):
            n += 1
            rows.append({"dock_id": f"G{n:02d}", "dock_type": "general", "owner": lid})
    for j in range(1, cfg.n_hazmat_docks + 1):
        rows.append({"dock_id": f"H{j:02d}", "dock_type": "hazmat", "owner": "PORT"})
    docks = pd.DataFrame(rows)
    zones = ["A", "B", "C", "D"]
    docks["zone"] = [
        "H" if t == "hazmat" else zones[min(3, (int(d[1:]) - 1) * 4 // max(1, cfg.n_general_docks))]
        for d, t in zip(docks["dock_id"], docks["dock_type"])
    ]
    return docks


def make_orders(cfg: Config, lines: pd.DataFrame, rng: np.random.Generator):
    """Return (orders, undeclared_key). Orders are the parcels shippers hand to a line on one day."""
    cats = list(ref.CATEGORIES)
    cat_p = np.array([ref.CATEGORIES[c][0] for c in cats])
    cat_p = cat_p / cat_p.sum()
    hz = list(ref.HAZMAT_CLASSES)
    hz_p = np.array([ref.HAZMAT_CLASSES[c][0] for c in hz])
    hz_p = hz_p / hz_p.sum()

    days = pd.date_range(cfg.start_date, periods=cfg.days, freq="D")
    rows, key = [], []
    for day in days:
        wf = ref.WEEKDAY_FACTOR[day.weekday()]
        for li, line in enumerate(lines.itertuples(index=False), start=1):
            n = int(rng.poisson(line.x_lam * wf))
            for k in range(1, n + 1):
                oid = f"O{day:%m%d}{li:02d}{k:03d}"
                shipper = f"S{int(rng.integers(1, 601)):04d}"
                hazmat_class = ""
                if line.hazmat_qualified:
                    hazmat_class = str(rng.choice(hz, p=hz_p))
                    _, items, unit = ref.HAZMAT_CLASSES[hazmat_class]
                    category = ref.HAZMAT_CATEGORY
                    weight = float(np.clip(rng.lognormal(math.log(300), 0.7), 20, 1500))
                    density = 900 * rng.lognormal(0.0, 0.15)
                    item = str(rng.choice(items))
                else:
                    hidden = rng.random() < cfg.p_undeclared_hazmat
                    if hidden:
                        item, likely, category = ref.UNDECLARED_ITEMS[int(rng.integers(len(ref.UNDECLARED_ITEMS)))]
                        key.append({"order_id": oid, "item": item, "likely_class": likely})
                    else:
                        category = str(rng.choice(cats, p=cat_p))
                    _, dens, items, unit = ref.CATEGORIES[category]
                    if not hidden:
                        item = str(rng.choice(items))
                    weight = float(np.clip(rng.lognormal(math.log(250), 0.9), 5, 3000))
                    density = dens * rng.lognormal(0.0, 0.2)
                volume = weight / density
                if volume > cfg.max_order_volume_m3:  # light goods: cap the order at an LTL size
                    volume = cfg.max_order_volume_m3 * rng.uniform(0.7, 1.0)
                    weight = volume * density
                volume = max(0.05, volume)
                pieces = max(1, int(round(volume / 0.1 * rng.uniform(0.6, 1.4))))
                rows.append(
                    {
                        "order_id": oid,
                        "date": day.strftime("%Y-%m-%d"),
                        "line_id": line.line_id,
                        "shipper_id": shipper,
                        "destination": line.destination,
                        "category": category,
                        "description": f"{item} {pieces}{unit}",
                        "weight_kg": round(weight, 1),
                        "volume_m3": round(volume, 2),
                        "pieces": pieces,
                        "hazmat_class": hazmat_class,
                    }
                )
    return pd.DataFrame(rows), pd.DataFrame(key, columns=["order_id", "item", "likely_class"])
