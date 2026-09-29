"""Score a team's plan against today's practice with the same code.

    python -m portsim.evaluate docks PLAN.csv --data out
    python -m portsim.evaluate loads PLAN.csv --data out

A plan is a CSV. It may cover some dates only; each date it covers must be complete, and only those dates are
scored, for the plan and for today's practice alike.

docks: one row per dock visit (event_id from gate_events) with the dock that serves it (dock_id) and its planned
       start (planned_start, a time written like gate_events' times). Each dock serves its visits in order of
       planned start, each as soon as the truck has reached the dock area, its cargo is ready (the visits it waits
       for have finished) and the dock is free; a dock is never held idle for a later planned start. Arrival and
       service times are the recorded ones. A general truck at another line's dock takes the pooled reference's
       extra handling (cross_dock_penalty_min, an invented 15 min). Hazmat trucks use hazmat docks, others general
       docks. Visits on dates the plan does not cover keep their recorded dock and order.
loads: one row per order (order_id) with the truck it leaves on (truck_id, any label, unique within the date) and
       the truck's vehicle_type; or hold = 1 to keep the order back for inspection, in which case it is not loaded
       that evening. The orders on one truck share a destination; their weight and volume fit the vehicle (full
       volume; trucks above the 90% fill limit are counted); declared hazmat orders ride only with declared hazmat
       orders.

Both are scored on the dataset rebuilt from the config in <data>/answer_key/baseline_summary.json, so the parts a
team cannot see (which visit waits for which, hidden hazmat) are the true ones. Today's practice is turned into a
plan of the same form (the recorded dock schedule, baseline_dispatch) and scored by the same functions.
"""

from __future__ import annotations

import argparse
import dataclasses
import heapq
import json
import sys
from pathlib import Path

import pandas as pd

from . import reference as ref
from .build import TIME_FMT, build_dataset
from .config import Config
from .dispatch import conflicts
from .docksim import kpis

HOLD_VALUES = {"1", "true", "yes", "y", "是"}
NOTE = ("模拟数据 (simulated data): compare only with today's practice in this data, labelled 模拟数据; "
        "see README 'Using the numbers'.")
DOCK_NOTE = ("The plan is scored against the recorded arrivals. A plan made knowing every arrival in advance "
             "(hindsight) overstates what a dispatcher deciding in real time can reach.")


class PlanError(ValueError):
    """The plan cannot be scored; the message lists what to fix."""


def load_context(data: Path) -> dict:
    """Rebuild the dataset from the config stored with a generated folder and check that it matches the folder."""
    data = Path(data)
    summary_path = data / "answer_key" / "baseline_summary.json"
    if not summary_path.exists():
        raise PlanError(f"{summary_path} not found: --data must be a folder written by `python -m portsim`")
    stored = json.loads(summary_path.read_text(encoding="utf-8"))["config"]
    ctx = context_from_config(Config(**stored))
    recorded = data / "clean" / "gate_events.csv"
    if recorded.exists():
        rec = pd.read_csv(recorded, dtype=str, keep_default_na=False)
        rebuilt = ctx["gate_events"]
        if list(rec["event_id"]) != list(rebuilt["event_id"]) or list(rec["gate_in"]) != list(rebuilt["gate_in"]):
            raise PlanError(f"the rebuilt data does not match {recorded}: another generator version or other "
                            "package versions (see README 'Run')")
    return ctx


def context_from_config(cfg: Config) -> dict:
    cfg = dataclasses.replace(cfg, trajectories=False, messy=False)  # neither changes visits, orders or trucks
    return context_from_dataset(cfg, build_dataset(cfg))


def context_from_dataset(cfg: Config, ds: dict) -> dict:
    return {
        "cfg": cfg,
        "ops": ds["internal"]["ops"],
        "docks": ds["clean"]["docks"],
        "gate_events": ds["clean"]["gate_events"],
        "orders": ds["clean"]["orders"],
        "lines": ds["clean"]["lines"],
        "baseline_dispatch": ds["clean"]["baseline_dispatch"],
        "undeclared": ds["answer_key"]["undeclared_hazmat"],
        "summary": ds["summary"],
    }


def _require(plan: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    missing = [c for c in cols if c not in plan.columns]
    if missing:
        raise PlanError(f"plan lacks column(s) {missing}; it has {list(plan.columns)}")
    if plan.empty:
        raise PlanError("the plan has no rows")
    plan = plan.copy()
    for c in plan.columns:
        plan[c] = plan[c].astype(str).str.strip()
    return plan


def _few(items) -> str:
    items = sorted(items)
    return ", ".join(items[:5]) + (f" and {len(items) - 5} more" if len(items) > 5 else "")


# ----------------------------------------------------------------------------------------------------- docks


def today_dock_plan(ctx: dict) -> pd.DataFrame:
    """Today's practice as a dock plan: the recorded dock and start of every visit."""
    g = ctx["gate_events"]
    return pd.DataFrame({"event_id": g["event_id"], "dock_id": g["dock_id"], "planned_start": g["dock_start"]})


def schedule_docks(ctx: dict, plan: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Serve the plan; return (a table shaped like docksim.simulate's, the event_ids of the dates it covers)."""
    cfg, ops, docks = ctx["cfg"], ctx["ops"], ctx["docks"]
    plan = _require(plan, ["event_id", "dock_id", "planned_start"])
    dup = plan.loc[plan["event_id"].duplicated(), "event_id"]
    if len(dup):
        raise PlanError(f"visits listed twice: {_few(set(dup))}")
    date_of = ctx["gate_events"].set_index("event_id")["date"]
    unknown = set(plan["event_id"]) - set(date_of.index)
    if unknown:
        raise PlanError(f"event_id not in gate_events: {_few(unknown)}")
    dates = set(date_of[plan["event_id"]])
    covered = set(date_of.index[date_of.isin(dates)])
    missing = covered - set(plan["event_id"])
    if missing:
        raise PlanError(f"the plan covers {sorted(dates)} but leaves out {len(missing)} visit(s) of those dates: "
                        f"{_few(missing)}")

    dock_type = docks.set_index("dock_id")["dock_type"]
    bad_dock = set(plan.loc[~plan["dock_id"].isin(dock_type.index), "dock_id"])
    if bad_dock:
        raise PlanError(f"unknown dock_id: {_few(bad_dock)}")
    starts = pd.to_datetime(plan["planned_start"], format=TIME_FMT, errors="coerce")
    if starts.isna().any():
        raise PlanError(f"planned_start must be written like 2026-09-14 08:05:00; unreadable for "
                        f"{_few(set(plan.loc[starts.isna(), 'event_id']))}")
    plan["key"] = (starts - pd.Timestamp(cfg.start_date)) / pd.Timedelta(minutes=1)

    rows = ops[ops["gate_in"].notna()].set_index("op_id")
    hz = rows.loc[plan["event_id"], "hazmat"].to_numpy()
    wrong = plan.loc[(dock_type[plan["dock_id"]].to_numpy() == "hazmat") != hz, "event_id"]
    if len(wrong):
        raise PlanError(f"hazmat trucks must use hazmat docks and other trucks general docks: {_few(set(wrong))}")

    # visits of dates the plan does not cover keep their recorded dock and order
    rest = today_dock_plan(ctx)
    rest = rest[~rest["event_id"].isin(covered)].copy()
    rest["key"] = (pd.to_datetime(rest["planned_start"], format=TIME_FMT) - pd.Timestamp(cfg.start_date)) / pd.Timedelta(minutes=1)
    full = pd.concat([plan[["event_id", "dock_id", "key"]], rest[["event_id", "dock_id", "key"]]], ignore_index=True)
    tie = full[full.duplicated(["dock_id", "key"], keep=False)]
    if len(tie):
        raise PlanError(f"two visits share a dock and a planned start, so their order is unclear: "
                        f"{_few(set(tie['event_id']))}")

    owned: dict[str, set] = {}
    for d, owner in zip(docks["dock_id"], docks["owner"]):
        owned.setdefault(owner, set()).add(d)
    dock_of = dict(zip(full["event_id"], full["dock_id"]))
    prev: dict[str, str] = {}
    for _, grp in full.sort_values(["dock_id", "key"]).groupby("dock_id", sort=True):
        ids = list(grp["event_id"])
        prev.update(zip(ids[1:], ids[:-1]))

    deps = {oid: [a for a in rows.at[oid, "after"].split(";") if a] for oid in full["event_id"]}
    children: dict[str, list[str]] = {}
    indeg = {}
    for oid, ds_ in deps.items():
        before = ds_ + ([prev[oid]] if oid in prev else [])
        indeg[oid] = len(before)
        for b in before:
            children.setdefault(b, []).append(oid)
    heap = sorted(oid for oid, n in indeg.items() if n == 0)
    heapq.heapify(heap)
    end: dict[str, int] = {}
    out = []
    while heap:
        oid = heapq.heappop(heap)
        r = rows.loc[oid]
        d = dock_of[oid]
        at_dock = int(r["gate_in"]) + cfg.approach_min
        ready = max([at_dock] + [end[a] for a in deps[oid]])
        start = max(ready, end[prev[oid]]) if oid in prev else ready
        extra = cfg.cross_dock_penalty_min if (not r["hazmat"] and d not in owned.get(r["line_id"], set())) else 0
        end[oid] = start + int(r["service_min"]) + extra
        out.append({"op_id": oid, "gate_in": int(r["gate_in"]), "ready": ready, "dock_id": d, "dock_start": start,
                    "dock_end": end[oid], "gate_out": end[oid] + int(r["exit_min"]), "x_cross_dock": extra > 0})
        for c in children.get(oid, []):
            indeg[c] -= 1
            if indeg[c] == 0:
                heapq.heappush(heap, c)
    if len(out) != len(full):
        stuck = set(full["event_id"]) - set(end)
        raise PlanError(f"the dock order contradicts which visit waits for which (a loading truck placed before a "
                        f"delivery of its own cargo on the same dock, directly or through other docks): "
                        f"{_few(stuck)}")
    sim = pd.DataFrame(out).sort_values(["gate_in", "op_id"]).reset_index(drop=True)
    return sim, sorted(covered)


def _dock_kpis(ctx: dict, sim: pd.DataFrame, covered: list[str]) -> dict:
    cfg, ops = ctx["cfg"], ctx["ops"]
    part = sim[sim["op_id"].isin(covered)]
    n_days = ctx["gate_events"].loc[ctx["gate_events"]["event_id"].isin(covered), "date"].nunique()
    out = kpis(ops, part.drop(columns=["x_cross_dock"]), ctx["docks"], dataclasses.replace(cfg, days=n_days))
    out["visits_at_another_lines_dock"] = int(part["x_cross_dock"].sum())
    return out


def evaluate_docks(ctx: dict, plan: pd.DataFrame) -> dict:
    sim, covered = schedule_docks(ctx, plan)
    today, _ = schedule_docks(ctx, today_dock_plan(ctx))
    dates = sorted(set(ctx["gate_events"].loc[ctx["gate_events"]["event_id"].isin(covered), "date"]))
    return {"dates": dates, "today": _dock_kpis(ctx, today, covered), "plan": _dock_kpis(ctx, sim, covered),
            "notes": [NOTE, DOCK_NOTE]}


# ----------------------------------------------------------------------------------------------------- loads


def today_load_plan(ctx: dict) -> pd.DataFrame:
    """Today's practice as a load plan: baseline_dispatch's trucks."""
    o, t = ctx["orders"], ctx["baseline_dispatch"]
    vt = t.set_index("truck_id")["vehicle_type"]
    return pd.DataFrame({"order_id": o["order_id"], "truck_id": o["baseline_truck_id"],
                         "vehicle_type": o["baseline_truck_id"].map(vt), "hold": ""})


def evaluate_load_plan(ctx: dict, plan: pd.DataFrame) -> dict:
    """KPIs of one load plan over the dates it covers."""
    cfg = ctx["cfg"]
    plan = _require(plan, ["order_id", "truck_id", "vehicle_type"])
    if "hold" not in plan.columns:
        plan["hold"] = ""
    dup = plan.loc[plan["order_id"].duplicated(), "order_id"]
    if len(dup):
        raise PlanError(f"orders listed twice: {_few(set(dup))}")
    orders = ctx["orders"].set_index("order_id")
    unknown = set(plan["order_id"]) - set(orders.index)
    if unknown:
        raise PlanError(f"order_id not in orders: {_few(unknown)}")
    dates = set(orders.loc[plan["order_id"], "date"])
    covered = set(orders.index[orders["date"].isin(dates)])
    missing = covered - set(plan["order_id"])
    if missing:
        raise PlanError(f"the plan covers {sorted(dates)} but leaves out {len(missing)} order(s) of those dates: "
                        f"{_few(missing)}")

    held = plan["hold"].str.lower().isin(HOLD_VALUES)
    loaded = plan[~held].join(orders, on="order_id")
    no_truck = loaded.loc[(loaded["truck_id"] == "") | ~loaded["vehicle_type"].isin(list(ref.VEHICLE_TYPES)),
                          "order_id"]
    if len(no_truck):
        raise PlanError(f"a loaded order needs a truck_id and a vehicle_type from vehicle_types.csv: "
                        f"{_few(set(no_truck))}")

    hidden = ctx["undeclared"].set_index("order_id")["likely_class"]
    km = ctx["lines"].groupby("destination")["distance_km"].first()
    problems, trucks = [], []
    for (date, tid), grp in loaded.groupby(["date", "truck_id"], sort=True):
        name = f"{date} {tid}"
        if grp["vehicle_type"].nunique() > 1:
            problems.append(f"{name}: more than one vehicle_type")
        if grp["destination"].nunique() > 1:
            problems.append(f"{name}: more than one destination")
        declared = grp["hazmat_class"] != ""
        if declared.any() and not declared.all():
            problems.append(f"{name}: declared hazmat orders together with other goods")
        vt = grp["vehicle_type"].iloc[0]
        _, cap_kg, vol = ref.VEHICLE_TYPES[vt]
        w, v = float(grp["weight_kg"].sum()), float(grp["volume_m3"].sum())
        if w > cap_kg + 1e-6 or v > vol + 1e-6:
            problems.append(f"{name}: {w:.0f} kg and {v:.1f} m3 exceed a {vt} truck ({cap_kg} kg, {vol} m3)")
        classes = {c for c in grp["hazmat_class"] if c}
        cats = set(grp["category"])
        in_hidden = hidden.reindex(grp["order_id"]).dropna()
        trucks.append({
            "vehicle_type": vt,
            "km": float(km[grp["destination"].iloc[0]]),
            "load_factor": round(max(v / vol, w / cap_kg), 3),  # rounded per truck, as baseline_dispatch is
            "over_fill_limit": v > vol * cfg.volume_fill_limit + 1e-6,
            "declared_conflict": bool(conflicts(classes, cats)),
            "hidden": len(in_hidden) > 0,
            "hidden_conflict": bool(conflicts(set(in_hidden), cats)) if len(in_hidden) else False,
        })
    if problems:
        raise PlanError("the plan breaks these rules:\n  " + "\n  ".join(problems[:20])
                        + (f"\n  and {len(problems) - 20} more" if len(problems) > 20 else ""))

    t = pd.DataFrame(trucks)
    held_ids = set(plan.loc[held, "order_id"])
    hidden_ids = set(hidden.index) & covered
    return {
        "trucks": int(len(t)),
        "trucks_per_day": round(len(t) / len(dates), 1),
        "trucks_by_type": {k: int(v) for k, v in t["vehicle_type"].value_counts().sort_index().items()},
        "truck_km": int(round(t["km"].sum())),
        "mean_load_factor": round(float(t["load_factor"].mean()), 3),
        "share_trucks_below_60pct_load": round(float((t["load_factor"] < 0.6).mean()), 3),
        "trucks_over_volume_fill_limit": int(t["over_fill_limit"].sum()),
        "trucks_with_illustrative_conflict": int(t["declared_conflict"].sum()),
        "orders_held": len(held_ids),
        "hidden_hazmat_orders": len(hidden_ids),
        "hidden_hazmat_held": len(hidden_ids & held_ids),
        "ordinary_orders_held": len(held_ids - hidden_ids),
        "trucks_carrying_hidden_hazmat": int(t["hidden"].sum()),
        "of_which_illustrative_conflict_with_hidden": int(t["hidden_conflict"].sum()),
    }


def evaluate_loads(ctx: dict, plan: pd.DataFrame) -> dict:
    result = evaluate_load_plan(ctx, plan)
    orders = ctx["orders"]
    dates = sorted(set(orders.loc[orders["order_id"].isin(set(plan["order_id"].astype(str).str.strip())), "date"]))
    today = today_load_plan(ctx)
    today = today[today["order_id"].isin(set(orders.loc[orders["date"].isin(dates), "order_id"]))]
    return {"dates": dates, "today": evaluate_load_plan(ctx, today), "plan": result, "notes": [NOTE]}


# ------------------------------------------------------------------------------------------------------- CLI


def _table(res: dict) -> str:
    lines = [f"dates: {res['dates'][0]} to {res['dates'][-1]} ({len(res['dates'])})", "",
             f"{'metric':44} {'today':>14} {'plan':>14} {'plan - today':>14}"]
    for k, a in res["today"].items():
        b = res["plan"][k]
        if isinstance(a, (int, float)) and not isinstance(a, bool):
            lines.append(f"{k:44} {a:>14} {b:>14} {round(b - a, 3):>14}")
        else:
            lines.append(f"{k:44} {json.dumps(a, ensure_ascii=False)}  ->  {json.dumps(b, ensure_ascii=False)}")
    return "\n".join(lines + [""] + res["notes"])


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="python -m portsim.evaluate", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("kind", choices=["docks", "loads"])
    p.add_argument("plan", help="the plan CSV")
    p.add_argument("--data", default="out", help="a folder written by `python -m portsim` (default: out)")
    p.add_argument("--json", action="store_true", help="print JSON instead of a table")
    a = p.parse_args(argv)
    try:
        plan = pd.read_csv(a.plan, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        ctx = load_context(Path(a.data))
        res = (evaluate_docks if a.kind == "docks" else evaluate_loads)(ctx, plan)
    except (PlanError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else _table(res))


if __name__ == "__main__":
    main()
