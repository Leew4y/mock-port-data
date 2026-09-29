"""First-come-first-served dock queue.

policy="owned":  a truck may use only its own line's docks (today's practice; this produces the gate records)
policy="pooled": any general dock, the one that finishes first; another line's dock costs cross_dock_penalty_min
                 extra (a naive reference showing the headroom of port-level coordination, not a solution)
Hazmat trucks always use the port's hazmat docks.

A truck joins the queue when it has reached the dock area and the visits it waits for (its `after` list: the
deliveries of its cargo, or the inbound truck it collects from) have finished. Trucks are served in the order they
become ready; among equally good docks the one idle longest is taken.
"""

from __future__ import annotations

import heapq

import pandas as pd

from .config import Config


def simulate(cfg: Config, ops: pd.DataFrame, docks: pd.DataFrame, policy: str = "owned") -> pd.DataFrame:
    if policy not in ("owned", "pooled"):
        raise ValueError(policy)
    general = docks.loc[docks["dock_type"] == "general", "dock_id"].tolist()
    hazmat = docks.loc[docks["dock_type"] == "hazmat", "dock_id"].tolist()
    owned: dict[str, list[str]] = {}
    for d, owner in zip(docks["dock_id"], docks["owner"]):
        owned.setdefault(owner, []).append(d)
    free_at = {d: float("-inf") for d in docks["dock_id"]}

    arrived = ops[ops["gate_in"].notna()]
    rows = {r.op_id: r for r in arrived.itertuples(index=False)}
    waiting = {oid: {a for a in r.after.split(";") if a} for oid, r in rows.items()}
    children: dict[str, list[str]] = {}
    for oid, deps in waiting.items():
        for d in deps:
            if d not in rows:
                raise ValueError(f"{oid} waits for {d}, which never reaches the port")
            children.setdefault(d, []).append(oid)
    cargo_ready: dict[str, int] = {}

    def at_dock(oid):
        return int(rows[oid].gate_in) + cfg.approach_min

    heap = [(at_dock(oid), oid) for oid in rows if not waiting[oid]]
    heapq.heapify(heap)
    out = []
    while heap:
        ready, oid = heapq.heappop(heap)
        r = rows[oid]
        if r.hazmat:
            cand = hazmat
        elif policy == "owned":
            cand = owned[r.line_id]
        else:
            cand = general
        mine = owned.get(r.line_id, [])

        def service(d):
            extra = cfg.cross_dock_penalty_min if (policy == "pooled" and not r.hazmat and d not in mine) else 0
            return int(r.service_min) + extra

        best = min(cand, key=lambda d: (max(ready, free_at[d]) + service(d), free_at[d], d))
        start = int(max(ready, free_at[best]))
        end = start + service(best)
        free_at[best] = end
        out.append(
            {
                "op_id": oid,
                "gate_in": int(r.gate_in),
                "ready": int(ready),
                "dock_id": best,
                "dock_start": start,
                "dock_end": end,
                "gate_out": end + int(r.exit_min),
            }
        )
        for c in children.get(oid, []):  # ready times pushed here are >= end >= ready, so the order stays FCFS
            waiting[c].discard(oid)
            cargo_ready[c] = max(cargo_ready.get(c, end), end)
            if not waiting[c]:
                heapq.heappush(heap, (max(at_dock(c), cargo_ready[c]), c))
    if len(out) != len(rows):
        raise RuntimeError("some visits never became ready")
    return pd.DataFrame(out).sort_values(["gate_in", "op_id"]).reset_index(drop=True)


def kpis(ops: pd.DataFrame, sim: pd.DataFrame, docks: pd.DataFrame, cfg: Config) -> dict:
    m = sim.merge(ops[["op_id", "op_type", "hazmat", "due"]], on="op_id")
    wait = m["dock_start"] - m["gate_in"] - cfg.approach_min  # everything between reaching the docks and service
    queue = m["dock_start"] - m["ready"]  # waiting for a dock once the cargo is ready
    cargo = m["ready"] - m["gate_in"] - cfg.approach_min  # waiting for the cargo (deliveries, or unloading)
    turn = m["gate_out"] - m["gate_in"]
    busy = (m["dock_end"] - m["dock_start"]).groupby(m["dock_id"]).sum()
    horizon = cfg.days * 1440
    util = busy.reindex(docks["dock_id"]).fillna(0) / horizon
    by_type = docks.set_index("dock_id")["dock_type"]
    out = m[m["op_type"] == "linehaul_out"]
    late = out["gate_out"] - out["due"].astype(float)
    return {
        "dock_visits": int(len(m)),
        "mean_wait_min": round(float(wait.mean()), 1),
        "p90_wait_min": round(float(wait.quantile(0.9)), 1),
        "share_wait_over_60min": round(float((wait > 60).mean()), 3),
        "mean_turnaround_min": round(float(turn.mean()), 1),
        "mean_wait_by_op_type": {k: round(float(v), 1) for k, v in wait.groupby(m["op_type"]).mean().items()},
        "mean_queue_wait_min": round(float(queue.mean()), 1),
        "mean_wait_for_cargo_min": round(float(cargo.mean()), 1),
        "linehaul_share_leaving_after_planned_departure": round(float((late > 0).mean()), 3),
        "linehaul_mean_delay_when_late_min": round(float(late[late > 0].mean()), 1) if (late > 0).any() else 0.0,
        "dock_utilization_24h_mean": {
            t: round(float(util[by_type == t].mean()), 3) for t in ("general", "hazmat")
        },
        "dock_utilization_24h_min_max_general": [
            round(float(util[by_type == "general"].min()), 3),
            round(float(util[by_type == "general"].max()), 3),
        ],
    }
