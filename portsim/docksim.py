"""First-come-first-served dock queue.

policy="owned":  a truck may use only its own line's docks (today's practice; this produces the gate records)
policy="pooled": any general dock, the one that finishes first; another line's dock costs cross_dock_penalty_min
                 extra (a naive reference showing the headroom of port-level coordination, not a solution)
Hazmat trucks always use the port's hazmat docks.
"""

from __future__ import annotations

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

    arrived = ops[ops["gate_in"].notna()].copy()
    arrived["gate_in"] = arrived["gate_in"].astype(int)
    arrived = arrived.sort_values(["gate_in", "op_id"])
    out = []
    for r in arrived.itertuples(index=False):
        if r.hazmat:
            cand = hazmat
        elif policy == "owned":
            cand = owned[r.line_id]
        else:
            cand = general
        ready = r.gate_in + cfg.approach_min
        mine = owned.get(r.line_id, [])

        def service(d):
            extra = cfg.cross_dock_penalty_min if (policy == "pooled" and not r.hazmat and d not in mine) else 0
            return int(r.service_min) + extra

        best = min(cand, key=lambda d: (max(ready, free_at[d]) + service(d), d))
        start = int(max(ready, free_at[best]))
        end = start + service(best)
        free_at[best] = end
        out.append(
            {
                "op_id": r.op_id,
                "gate_in": r.gate_in,
                "dock_id": best,
                "dock_start": start,
                "dock_end": end,
                "gate_out": end + int(r.exit_min),
            }
        )
    return pd.DataFrame(out)


def kpis(ops: pd.DataFrame, sim: pd.DataFrame, docks: pd.DataFrame, cfg: Config) -> dict:
    m = sim.merge(ops[["op_id", "op_type", "hazmat"]], on="op_id")
    wait = m["dock_start"] - m["gate_in"] - cfg.approach_min
    turn = m["gate_out"] - m["gate_in"]
    busy = (m["dock_end"] - m["dock_start"]).groupby(m["dock_id"]).sum()
    horizon = cfg.days * 1440
    util = busy.reindex(docks["dock_id"]).fillna(0) / horizon
    by_type = docks.set_index("dock_id")["dock_type"]
    return {
        "dock_visits": int(len(m)),
        "mean_wait_min": round(float(wait.mean()), 1),
        "p90_wait_min": round(float(wait.quantile(0.9)), 1),
        "share_wait_over_60min": round(float((wait > 60).mean()), 3),
        "mean_turnaround_min": round(float(turn.mean()), 1),
        "mean_wait_by_op_type": {k: round(float(v), 1) for k, v in wait.groupby(m["op_type"]).mean().items()},
        "dock_utilization_24h_mean": {
            t: round(float(util[by_type == t].mean()), 3) for t in ("general", "hazmat")
        },
        "dock_utilization_24h_min_max_general": [
            round(float(util[by_type == "general"].min()), 3),
            round(float(util[by_type == "general"].max()), 3),
        ],
    }
