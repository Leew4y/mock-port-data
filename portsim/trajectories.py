"""GPS pings for inbound linehaul trucks over the last 3 hours before the gate, with labelled anomalies.

Trucks move on a straight line from their origin city toward the port; this is a toy geometry, not a road network.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import reference as ref

KM_PER_DEG_LAT = 110.57
ANOMALY_TYPES = ["long_stop", "route_deviation", "signal_gap"]


def make_trajectories(ops: pd.DataFrame, lines: pd.DataFrame, rng: np.random.Generator, p_anomaly: float = 0.06):
    city_xy = {c: (lat, lon) for c, lat, lon, _, _ in ref.DESTINATIONS}
    dest_of = lines.set_index("line_id")["destination"]
    km_per_deg_lon = 111.32 * math.cos(math.radians(ref.PORT_LAT))

    def to_km(lat, lon):
        return (lon - ref.PORT_LON) * km_per_deg_lon, (lat - ref.PORT_LAT) * KM_PER_DEG_LAT

    inbound = ops[(ops["op_type"] == "linehaul_in") & ops["gate_in"].notna()].sort_values("op_id")
    pings, truth = [], []
    taus = np.arange(0, 181, 5)
    for r in inbound.itertuples(index=False):
        ox, oy = to_km(*city_xy[dest_of[r.line_id]])
        dist = math.hypot(ox, oy)
        ux, uy = ox / dist, oy / dist
        v = 65 / 60 * rng.uniform(0.85, 1.15)  # km per minute
        kind, t0, dur, amp = None, 0, 0, 0.0
        if rng.random() < p_anomaly:
            kind = ANOMALY_TYPES[int(rng.integers(len(ANOMALY_TYPES)))]
            dur = int({"long_stop": rng.integers(45, 91), "route_deviation": rng.integers(30, 61),
                       "signal_gap": rng.integers(40, 91)}[kind])
            t0 = int(rng.integers(30, 181 - dur))
            amp = float(rng.uniform(8, 15))
            truth.append({"op_id": r.op_id, "plate": r.plate, "anomaly_type": kind,
                          "start": int(r.gate_in) - t0 - dur, "end": int(r.gate_in) - t0})
        noise = rng.normal(0, 0.03, size=(len(taus), 2))
        spd_noise = rng.normal(0, 5, size=len(taus))
        for i, tau in enumerate(taus):
            in_window = kind is not None and t0 <= tau <= t0 + dur
            if kind == "signal_gap" and in_window:
                continue
            moving = tau
            if kind == "long_stop":
                moving = tau - max(0, min(tau, t0 + dur) - t0)
            rem = min(v * moving, dist)
            x, y = ux * rem, uy * rem
            if kind == "route_deviation" and in_window:
                off = amp * math.sin(math.pi * (tau - t0) / dur)
                x, y = x - uy * off, y + ux * off
            x, y = x + noise[i, 0], y + noise[i, 1]
            stopped = (kind == "long_stop" and in_window) or rem >= dist
            speed = 0.0 if stopped else max(0.0, v * 60 + spd_noise[i])
            pings.append({
                "op_id": r.op_id,
                "plate": r.plate,
                "ts": int(r.gate_in) - int(tau),
                "lat": round(ref.PORT_LAT + y / KM_PER_DEG_LAT, 5),
                "lon": round(ref.PORT_LON + x / km_per_deg_lon, 5),
                "speed_kmh": round(speed, 1),
            })
    traj = pd.DataFrame(pings).sort_values(["op_id", "ts"]).reset_index(drop=True)
    return traj, pd.DataFrame(truth, columns=["op_id", "plate", "anomaly_type", "start", "end"])
