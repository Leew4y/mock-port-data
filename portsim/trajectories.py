"""GPS pings for inbound linehaul trucks over the last 3 hours before the gate, with labelled anomalies.

Trucks move on a straight line from their origin city toward the port at a constant speed; this is a toy geometry,
not a road network, and there is no slowdown near the port. A truck whose trip is shorter than 3 hours has pings
only from its departure onwards. Every ping with speed 0 lies inside a labelled long_stop.
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
    for r in inbound.itertuples(index=False):
        ox, oy = to_km(*city_xy[dest_of[r.line_id]])
        dist = math.hypot(ox, oy)
        ux, uy = ox / dist, oy / dist
        v = 65 / 60 * rng.uniform(0.85, 1.15)  # km per minute
        horizon = min(180, int(dist / v) // 5 * 5)  # minutes of driving shown before the gate
        taus = np.arange(0, horizon + 1, 5)
        kind, t0, dur, amp = None, 0, 0, 0.0
        if rng.random() < p_anomaly:
            kind = ANOMALY_TYPES[int(rng.integers(len(ANOMALY_TYPES)))]
            dur = int({"long_stop": rng.integers(45, 91), "route_deviation": rng.integers(30, 61),
                       "signal_gap": rng.integers(40, 91)}[kind])
            if horizon - dur < 35:  # too short a trip to show this anomaly
                kind = None
            else:
                t0 = int(rng.integers(30, horizon - dur))
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
            stopped = kind == "long_stop" and in_window
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
