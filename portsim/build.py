"""Build every table from one seed and write the dataset folder."""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from . import reference as ref
from .config import Config
from .dispatch import baseline_dispatch, conflicts
from .docksim import kpis, simulate
from .entities import make_docks, make_lines, make_local_plates, make_orders
from .messy import make_messy
from .operations import make_operations
from .trajectories import make_trajectories

DOCS = Path(__file__).resolve().parent.parent / "docs"
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _times(cfg: Config, minutes: pd.Series) -> pd.Series:
    ts = pd.Timestamp(cfg.start_date) + pd.to_timedelta(pd.to_numeric(minutes), unit="min")
    return ts.dt.strftime(TIME_FMT).fillna("")


def build_dataset(cfg: Config) -> dict:
    """Return {'clean': {...}, 'messy': {...}, 'answer_key': {...}, 'summary': {...}}."""
    r_static, r_orders, r_ops, r_traj, r_messy = [np.random.default_rng(s) for s in np.random.SeedSequence(cfg.seed).spawn(5)]

    lines = make_lines(cfg, r_static)
    docks = make_docks(cfg, lines)
    local_plates = make_local_plates(r_static)
    orders, undeclared = make_orders(cfg, lines, r_orders)
    trucks, order_truck = baseline_dispatch(cfg, lines, orders)
    ops, dropoff = make_operations(cfg, lines, orders, trucks, local_plates, r_ops)
    sim = simulate(cfg, ops, docks, "owned")
    pooled = simulate(cfg, ops, docks, "pooled")

    # clean tables
    lines_out = lines.drop(columns=["x_lam", "x_fleet"]).copy()
    lines_out["docks_owned"] = lines_out["line_id"].map(docks["owner"].value_counts()).fillna(0).astype(int)
    vehicle_types = pd.DataFrame(
        [(k, *v) for k, v in ref.VEHICLE_TYPES.items()], columns=["vehicle_type", "length_m", "max_load_kg", "volume_m3"]
    )
    orders_out = orders.copy()
    orders_out["dropoff_event_id"] = dropoff
    orders_out["baseline_truck_id"] = order_truck

    appt = ops[ops["appointment_id"] != ""].copy()
    appointments = pd.DataFrame({
        "appointment_id": appt["appointment_id"],
        "plate": appt["plate"],
        "line_id": appt["line_id"],
        "op_type": appt["op_type"],
        "vehicle_type": appt["vehicle_type"],
        "slot_start": _times(cfg, appt["slot_start"]),
        "slot_end": _times(cfg, appt["slot_end"]),
    }).reset_index(drop=True)

    g = sim.merge(ops.drop(columns=["gate_in"]), on="op_id", how="left").sort_values(["gate_in", "op_id"])
    gate_events = pd.DataFrame({
        "event_id": g["op_id"],
        "date": g["date"],
        "plate": g["plate"],
        "appointment_id": g["appointment_id"],
        "line_id": g["line_id"],
        "op_type": g["op_type"],
        "vehicle_type": g["vehicle_type"],
        "cargo_volume_m3": g["cargo_volume_m3"],
        "hazmat": g["hazmat"],
        "truck_id": g["ref_id"],
        "gate_in": _times(cfg, g["gate_in"]),
        "dock_id": g["dock_id"],
        "dock_start": _times(cfg, g["dock_start"]),
        "dock_end": _times(cfg, g["dock_end"]),
        "gate_out": _times(cfg, g["gate_out"]),
    }).reset_index(drop=True)

    rules = pd.DataFrame(ref.ILLUSTRATIVE_INCOMPATIBLE, columns=["a", "b"])
    rules["source"] = "ILLUSTRATIVE ONLY - not the JT/T 617.6 table; replace before use"

    clean = {
        "lines": lines_out,
        "docks": docks,
        "vehicle_types": vehicle_types,
        "orders": orders_out,
        "baseline_dispatch": trucks.drop(columns=["x_truck_no"]),
        "appointments": appointments,
        "gate_events": gate_events,
        "hazmat_rules_illustrative": rules,
    }
    answer = {"undeclared_hazmat": undeclared}

    if cfg.trajectories:
        traj, anomalies = make_trajectories(ops, lines, r_traj)
        traj["ts"] = _times(cfg, traj["ts"])
        anomalies["start"] = _times(cfg, anomalies["start"])
        anomalies["end"] = _times(cfg, anomalies["end"])
        clean["trajectories"] = traj.rename(columns={"op_id": "event_id"})
        answer["trajectory_anomalies"] = anomalies.rename(columns={"op_id": "event_id"})

    messy = {}
    if cfg.messy:
        messy, ledger = make_messy({k: clean[k] for k in ("orders", "gate_events", "appointments")}, r_messy)
        answer["messy_injected_issues"] = ledger

    # summary (answer key: the team computes its own "before" numbers)
    hidden = set(undeclared["order_id"])
    trucks_hidden = orders_out.loc[orders_out["order_id"].isin(hidden), "baseline_truck_id"].nunique()
    food_mix = 0
    for tid, grp in orders_out[orders_out["baseline_truck_id"] != ""].groupby("baseline_truck_id"):
        ids = set(grp["order_id"]) & hidden
        if ids:
            likely = set(undeclared.loc[undeclared["order_id"].isin(ids), "likely_class"])
            food_mix += bool(conflicts(likely, set(grp["category"])))
    lf = trucks["load_factor"]
    summary = {
        "config": dataclasses.asdict(cfg),
        "counts": {
            "lines": int(len(lines)),
            "docks": int(len(docks)),
            "orders": int(len(orders)),
            "baseline_trucks": int(len(trucks)),
            "dock_visits": int(len(gate_events)),
            "appointments": int(len(appointments)),
            "appointment_no_shows": int(ops["no_show"].sum()),
            "orders_with_undeclared_hazmat": int(len(undeclared)),
        },
        "baseline_owned_docks": kpis(ops, sim, docks, cfg),
        "reference_pooled_fcfs_not_a_solution": kpis(ops, pooled, docks, cfg),
        "baseline_dispatch": {
            "mean_load_factor": round(float(lf.mean()), 3),
            "share_trucks_below_60pct_load": round(float((lf < 0.6).mean()), 3),
            "trucks_per_day": round(len(trucks) / cfg.days, 1),
            "trucks_with_illustrative_conflict": int((trucks["illustrative_conflicts"] != "").sum()),
            "trucks_carrying_undeclared_hazmat": int(trucks_hidden),
            "of_which_illustrative_conflict_with_food": int(food_mix),
        },
    }
    return {"clean": clean, "messy": messy, "answer_key": answer, "summary": summary}


def write_dataset(ds: dict, out: Path) -> None:
    out = Path(out)
    for sub in ("clean", "messy", "answer_key"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    for name, df in ds["clean"].items():
        df.to_csv(out / "clean" / f"{name}.csv", index=False, encoding="utf-8")
    for name, df in ds["messy"].items():
        enc = "gb18030" if name == "orders" else "utf-8-sig"
        df.to_csv(out / "messy" / f"{name}.csv", index=False, encoding=enc)
    for name, df in ds["answer_key"].items():
        df.to_csv(out / "answer_key" / f"{name}.csv", index=False, encoding="utf-8")
    (out / "answer_key" / "baseline_summary.json").write_text(
        json.dumps(ds["summary"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for doc in ("data_dictionary.md", "scenario_brief_zh.md"):
        if (DOCS / doc).exists():
            shutil.copy(DOCS / doc, out / doc)
