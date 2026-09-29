from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from portsim import Config, build_dataset, write_dataset
from portsim import messy as mz
from portsim.dispatch import conflicts, first_fit_decreasing
from portsim import reference as ref


@pytest.fixture(scope="module")
def ds():
    return build_dataset(Config())


def _digest(out, cfg):
    write_dataset(build_dataset(cfg), out)
    return {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob("*.*"))}


def test_same_seed_gives_identical_files(tmp_path):
    a = _digest(tmp_path / "a", Config(days=2))
    b = _digest(tmp_path / "b", Config(days=2))
    assert a == b


def test_other_seed_differs(tmp_path):
    a = _digest(tmp_path / "a", Config(days=2))
    b = _digest(tmp_path / "b", Config(days=2, seed=7))
    assert a["clean/orders.csv"] != b["clean/orders.csv"]


def test_referential_integrity(ds):
    c = ds["clean"]
    lines = set(c["lines"]["line_id"])
    for t in ("orders", "gate_events", "appointments", "baseline_dispatch"):
        assert set(c[t]["line_id"]) <= lines, t
    assert set(c["gate_events"]["dock_id"]) <= set(c["docks"]["dock_id"])
    vts = set(c["vehicle_types"]["vehicle_type"])
    for t in ("gate_events", "appointments", "baseline_dispatch"):
        assert set(c[t]["vehicle_type"]) <= vts, t
    assert set(c["gate_events"]["appointment_id"]) - {""} <= set(c["appointments"]["appointment_id"])
    assert set(c["gate_events"]["truck_id"]) - {""} == set(c["baseline_dispatch"]["truck_id"])


def test_every_order_dropped_off_and_shipped_once(ds):
    o, t = ds["clean"]["orders"], ds["clean"]["baseline_dispatch"]
    assert o["order_id"].is_unique
    assert (o["dropoff_event_id"] != "").all()
    assert set(o["dropoff_event_id"]) <= set(ds["clean"]["gate_events"]["event_id"])
    per_truck = o.groupby("baseline_truck_id").size().reindex(t["truck_id"]).to_numpy()
    assert (per_truck == t["n_orders"].to_numpy()).all()
    merged = o.merge(t[["truck_id", "line_id"]], left_on="baseline_truck_id", right_on="truck_id", suffixes=("", "_t"))
    assert (merged["line_id"] == merged["line_id_t"]).all()


def test_gate_event_times_are_ordered(ds):
    g = ds["clean"]["gate_events"]
    ts = {c: pd.to_datetime(g[c]) for c in ("gate_in", "dock_start", "dock_end", "gate_out")}
    assert (ts["gate_in"] + pd.Timedelta(minutes=Config().approach_min) <= ts["dock_start"]).all()
    assert (ts["dock_start"] < ts["dock_end"]).all()
    assert (ts["dock_end"] < ts["gate_out"]).all()


def test_no_dock_serves_two_trucks_at_once(ds):
    g = ds["clean"]["gate_events"].assign(
        s=lambda d: pd.to_datetime(d["dock_start"]), e=lambda d: pd.to_datetime(d["dock_end"])
    )
    for _, d in g.sort_values("s").groupby("dock_id"):
        assert (d["s"].to_numpy()[1:] >= d["e"].to_numpy()[:-1]).all()


def test_trucks_use_own_or_hazmat_docks(ds):
    c = ds["clean"]
    g = c["gate_events"].merge(c["docks"], on="dock_id")
    assert (g.loc[g["hazmat"], "dock_type"] == "hazmat").all()
    general = g[~g["hazmat"]]
    assert (general["owner"] == general["line_id"]).all()


def test_dispatch_within_vehicle_capacity(ds):
    t = ds["clean"]["baseline_dispatch"].merge(
        ds["clean"]["vehicle_types"], on="vehicle_type", suffixes=("", "_cap")
    )
    assert (t["weight_kg"] <= t["max_load_kg"] + 0.1).all()
    assert (t["volume_m3"] <= t["volume_m3_cap"] + 0.01).all()


def test_conflict_flags_match_rules(ds):
    o, t = ds["clean"]["orders"], ds["clean"]["baseline_dispatch"]
    for tid, grp in o.groupby("baseline_truck_id"):
        expected = ";".join(conflicts({c for c in grp["hazmat_class"] if c}, set(grp["category"])))
        assert t.loc[t["truck_id"] == tid, "illustrative_conflicts"].item() == expected


def test_undeclared_hazmat_is_hidden_in_general_lines(ds):
    o, lines = ds["clean"]["orders"], ds["clean"]["lines"]
    key = ds["answer_key"]["undeclared_hazmat"]
    assert len(key) > 0
    hidden = o[o["order_id"].isin(key["order_id"])]
    assert (hidden["hazmat_class"] == "").all()
    assert (hidden["category"] != ref.HAZMAT_CATEGORY).all()
    assert not lines.set_index("line_id").loc[hidden["line_id"], "hazmat_qualified"].any()
    assert all(item in d for item, d in zip(key.sort_values("order_id")["item"], hidden.sort_values("order_id")["description"]))


def test_thesis_is_visible_in_the_data(ds):
    """Port-level coordination must have room to help, or the rehearsal cannot show a saving."""
    s = ds["summary"]
    assert s["reference_pooled_fcfs_not_a_solution"]["mean_wait_min"] < 0.6 * s["baseline_owned_docks"]["mean_wait_min"]
    t, o = ds["clean"]["baseline_dispatch"], ds["clean"]["orders"]
    general = o[o["hazmat_class"] == ""]
    _, cap_kg, vol = ref.VEHICLE_TYPES["17.5m"]
    pooled = sum(len(first_fit_decreasing(g, cap_kg, vol * 0.9)) for _, g in general.groupby(["date", "destination"]))
    baseline = int(t["truck_id"].isin(general["baseline_truck_id"]).sum())
    assert pooled < 0.8 * baseline


def test_scale_is_in_the_intended_range(ds):
    s = ds["summary"]
    days = s["config"]["days"]
    assert 400 <= s["counts"]["dock_visits"] / days <= 800
    assert 15 <= s["baseline_owned_docks"]["mean_wait_min"] <= 90
    assert 0.5 <= s["baseline_dispatch"]["mean_load_factor"] <= 0.85


def test_trajectories_agree_with_labels(ds):
    traj = ds["clean"]["trajectories"].assign(ts=lambda d: pd.to_datetime(d["ts"]))
    g = ds["clean"]["gate_events"]
    inbound = g[g["op_type"] == "linehaul_in"].set_index("event_id")
    assert set(traj["event_id"]) <= set(inbound.index)
    last = traj.groupby("event_id")["ts"].max()
    assert (last <= pd.to_datetime(inbound.loc[last.index, "gate_in"])).all()
    for a in ds["answer_key"]["trajectory_anomalies"].itertuples(index=False):
        p = traj[traj["event_id"] == a.event_id]
        inside = p[(p["ts"] > pd.Timestamp(a.start)) & (p["ts"] < pd.Timestamp(a.end))]
        if a.anomaly_type == "signal_gap":
            assert inside.empty
        elif a.anomaly_type == "long_stop":
            assert (inside["speed_kmh"] == 0).all() and not inside.empty


def _parse_weight(s: str) -> float:
    s = str(s)
    if s.endswith("公斤"):
        return float(s[:-2])
    if s.endswith("kg"):
        return float(s[:-2])
    if s.endswith("t"):
        return float(s[:-1]) * 1000
    return float(s)


def _parse_time(s: str) -> pd.Timestamp:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%d-%m-%Y %H:%M", "%Y%m%d%H%M%S"):
        try:
            return pd.to_datetime(s, format=fmt)
        except ValueError:
            continue
    raise ValueError(s)


def test_messy_tables_match_the_ledger(ds):
    led = ds["answer_key"]["messy_injected_issues"]
    for name in ("orders", "gate_events", "appointments"):
        zh = mz.HEADERS_ZH[name]
        key = zh[mz.KEYS[name]]
        m, clean = ds["messy"][name], ds["clean"][name]
        mine = led[led["table"] == name]
        dups = mine[mine["issue"] == "duplicate_row"]
        assert len(m) == len(clean) + len(dups)
        assert set(m.loc[m[key].duplicated(), key]) == set(dups["key"])
        dedup = m.drop_duplicates().set_index(key)
        assert dedup.index.is_unique
        for col, grp in mine[mine["issue"] == "missing"].groupby("column"):
            assert set(dedup.index[dedup[zh[col]] == ""]) == set(grp["key"])


def test_messy_values_recover_to_clean(ds):
    led = ds["answer_key"]["messy_injected_issues"]
    broken = set(zip(led["key"], led["column"], led["issue"]))
    o = ds["messy"]["orders"].drop_duplicates().set_index("运单号")
    c = ds["clean"]["orders"].set_index("order_id")
    ok = o["重量"] != ""
    diff = (o.loc[ok, "重量"].map(_parse_weight) - c.loc[o.index[ok], "weight_kg"]).abs()
    assert diff.max() <= 0.51

    g = ds["messy"]["gate_events"].drop_duplicates().set_index("作业编号")
    cg = ds["clean"]["gate_events"].set_index("event_id")
    for col in ("gate_in", "dock_start", "dock_end", "gate_out"):
        zh = mz.HEADERS_ZH["gate_events"][col]
        for k, v in g[zh].items():
            if v == "" or (k, col, "wrong_year") in broken or (k, "dock_end", "end_before_start") in broken:
                continue
            assert _parse_time(v) == pd.Timestamp(cg.at[k, col]), (k, col, v)
