"""Messy copies of three clean tables, the way exported business data often arrives.

Every injected problem is listed in answer_key/messy_injected_issues.csv (table, key, column, issue), so a
data health-check tool can be scored. Headers and category values are in Chinese; orders are GB18030-encoded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

OP_TYPE_ZH = {"delivery_in": "送货卸车", "linehaul_out": "干线装车", "linehaul_in": "干线卸车", "pickup_out": "提货装车"}

HEADERS_ZH = {
    "orders": {
        "order_id": "运单号", "date": "日期", "line_id": "专线编号", "shipper_id": "发货方编号",
        "destination": "目的地", "category": "货物类别", "description": "货物描述", "weight_kg": "重量",
        "volume_m3": "体积(方)", "pieces": "件数", "hazmat_class": "危险品类别",
        "dropoff_event_id": "送货作业编号", "baseline_truck_id": "干线车次",
    },
    "gate_events": {
        "event_id": "作业编号", "date": "日期", "plate": "车牌号", "appointment_id": "预约号", "line_id": "专线编号",
        "op_type": "作业类型", "vehicle_type": "车型", "cargo_volume_m3": "货物体积(方)", "hazmat": "是否危险品",
        "truck_id": "干线车次", "gate_in": "入场时间", "dock_id": "月台号", "dock_start": "开始作业时间",
        "dock_end": "结束作业时间", "gate_out": "出场时间",
    },
    "appointments": {
        "appointment_id": "预约号", "plate": "车牌号", "line_id": "专线编号", "op_type": "作业类型",
        "vehicle_type": "车型", "slot_start": "预约开始时间", "slot_end": "预约结束时间",
    },
}
KEYS = {"orders": "order_id", "gate_events": "event_id", "appointments": "appointment_id"}
TIME_COLS = {
    "orders": [],
    "gate_events": ["gate_in", "dock_start", "dock_end", "gate_out"],
    "appointments": ["slot_start", "slot_end"],
}
MISSING_COLS = {
    "orders": ["shipper_id", "category", "pieces", "volume_m3"],
    "gate_events": ["dock_id", "gate_out", "plate"],
    "appointments": ["vehicle_type"],
}
PLATE_COLS = {"orders": [], "gate_events": ["plate"], "appointments": ["plate"]}


def _alt_time(s: str, k: int) -> str:
    t = pd.Timestamp(s)
    if k == 0:
        return f"{t.year}/{t.month}/{t.day} {t.hour}:{t.minute:02d}"
    if k == 1:
        return t.strftime("%d-%m-%Y %H:%M")
    return t.strftime("%Y%m%d%H%M%S")


def _alt_plate(p: str, k: int) -> str:
    if k == 0:
        return p[:2] + "·" + p[2:]
    if k == 1:
        return p.lower()
    return f" {p[:2]} {p[2:]} "


class _Injector:
    def __init__(self, name: str, df: pd.DataFrame, rng: np.random.Generator, ledger: list):
        self.name, self.rng, self.ledger = name, rng, ledger
        self.df = df.astype(object).copy()
        self.key = KEYS[name]
        self.used: dict[str, set] = {}

    def pick(self, col: str, frac: float, eligible=None) -> list:
        pool = self.df.index if eligible is None else eligible
        pool = [i for i in pool if i not in self.used.setdefault(col, set())]
        n = int(round(len(self.df) * frac))
        if n == 0 or not pool:
            return []
        chosen = sorted(self.rng.choice(pool, size=min(n, len(pool)), replace=False).tolist())
        self.used[col].update(chosen)
        return chosen

    def log(self, i, col: str, issue: str):
        self.ledger.append({"table": self.name, "key": self.df.at[i, self.key], "column": col, "issue": issue})


def make_messy(tables: dict, rng: np.random.Generator):
    """tables: clean output-format frames 'orders', 'gate_events', 'appointments'. Returns (messy, ledger)."""
    ledger: list = []
    messy = {}
    for name in ("orders", "gate_events", "appointments"):
        inj = _Injector(name, tables[name], rng, ledger)
        df = inj.df

        if name == "gate_events":
            nonempty = df.index[(df["dock_start"] != "") & (df["dock_end"] != "")]
            for i in inj.pick("dock_end", 0.003, nonempty):
                df.at[i, "dock_start"], df.at[i, "dock_end"] = df.at[i, "dock_end"], df.at[i, "dock_start"]
                inj.used.setdefault("dock_start", set()).add(i)
                inj.log(i, "dock_end", "end_before_start")
            for i in inj.pick("gate_in", 0.002):
                df.at[i, "gate_in"] = "2025" + df.at[i, "gate_in"][4:]
                inj.log(i, "gate_in", "wrong_year")
        if name == "orders":
            for i in inj.pick("volume_m3", 0.002):
                df.at[i, "volume_m3"] = -float(df.at[i, "volume_m3"])
                inj.log(i, "volume_m3", "negative_value")

        for col in MISSING_COLS[name]:
            for i in inj.pick(col, 0.02):
                df.at[i, col] = ""
                inj.log(i, col, "missing")

        for col in TIME_COLS[name]:
            eligible = df.index[df[col] != ""]
            for i in inj.pick(col, 0.15, eligible):
                df.at[i, col] = _alt_time(df.at[i, col], int(rng.integers(3)))
                inj.log(i, col, "time_format")

        for col in PLATE_COLS[name]:
            eligible = df.index[df[col] != ""]
            for i in inj.pick(col, 0.05, eligible):
                df.at[i, col] = _alt_plate(df.at[i, col], int(rng.integers(3)))
                inj.log(i, col, "plate_format")

        if name == "orders":
            eligible = df.index
            unit_idx = inj.pick("weight_kg", 0.16, eligible)
            for n, i in enumerate(unit_idx):
                kg = float(df.at[i, "weight_kg"])
                style = n % 3
                df.at[i, "weight_kg"] = (f"{kg / 1000:.3f}t", f"{kg:g}kg", f"{kg:g}公斤")[style]
                inj.log(i, "weight_kg", "weight_unit")

        if "op_type" in df.columns:
            df["op_type"] = df["op_type"].map(OP_TYPE_ZH)
        if "hazmat" in df.columns:
            df["hazmat"] = df["hazmat"].map({True: "是", False: "否", "True": "是", "False": "否"})

        dup = inj.pick("__row__", 0.01)
        for i in dup:
            inj.log(i, "", "duplicate_row")
        if dup:
            extra = df.loc[dup]
            positions = rng.integers(0, len(df) + 1, size=len(extra))
            parts, last = [], 0
            order = np.argsort(positions, kind="stable")
            for j in order:
                p = int(positions[j])
                parts.append(df.iloc[last:p])
                parts.append(extra.iloc[[j]])
                last = p
            parts.append(df.iloc[last:])
            df = pd.concat(parts)
        messy[name] = df.rename(columns=HEADERS_ZH[name]).reset_index(drop=True)

    return messy, pd.DataFrame(ledger, columns=["table", "key", "column", "issue"])
