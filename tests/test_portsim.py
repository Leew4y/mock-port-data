from __future__ import annotations

import hashlib
import os
import subprocess
import sys

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


def test_output_does_not_depend_on_hash_seed(tmp_path):
    """Two processes with different PYTHONHASHSEED must write the same bytes (no set or dict order leaks)."""
    digests = []
    for hs in ("1", "12345"):
        out = tmp_path / hs
        env = {**os.environ, "PYTHONHASHSEED": hs}
        subprocess.run([sys.executable, "-m", "portsim", "--days", "2", "--out", str(out)], check=True, env=env,
                       capture_output=True)
        digests.append({p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(out.rglob("*.*"))})
    assert digests[0] == digests[1]


def test_formerly_crashing_seed_builds():
    """Seed 1 used to produce a 37 m3 order that fit no truck."""
    ds = build_dataset(Config(seed=1, trajectories=False, messy=False))
    assert len(ds["clean"]["orders"]) > 0


def test_every_order_fits_its_lines_standard_truck(ds):
    cfg = Config()
    o = ds["clean"]["orders"].merge(ds["clean"]["lines"][["line_id", "standard_vehicle"]], on="line_id")
    assert o["volume_m3"].max() <= cfg.max_order_volume_m3
    cap = o["standard_vehicle"].map(lambda vt: ref.VEHICLE_TYPES[vt][2] * cfg.volume_fill_limit)
    kg = o["standard_vehicle"].map(lambda vt: ref.VEHICLE_TYPES[vt][1])
    assert (o["volume_m3"] <= cap).all() and (o["weight_kg"] <= kg).all()


@pytest.mark.parametrize("days", [0, 366])
def test_days_out_of_range_is_refused(days):
    with pytest.raises(ValueError):
        Config(days=days)


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


def test_conflict_function_on_literal_cases():
    assert conflicts({"5.1", "3"}, set()) == ["5.1+3"]
    assert conflicts({"6.1"}, {"食品饮料", "服装鞋帽"}) == ["6.1+食品饮料"]
    assert conflicts({"3", "8"}, {"食品饮料"}) == []


def test_conflict_flags_match_the_trucks_contents(ds):
    o, t = ds["clean"]["orders"], ds["clean"]["baseline_dispatch"].set_index("truck_id")
    for tid, grp in o.groupby("baseline_truck_id"):
        present = {c for c in grp["hazmat_class"] if c} | set(grp["category"])
        flags = {f for f in t.at[tid, "illustrative_conflicts"].split(";") if f}
        for a, b in ref.ILLUSTRATIVE_INCOMPATIBLE:
            assert (f"{a}+{b}" in flags) == (a in present and b in present), tid


def test_packing_follows_the_stated_rules(ds):
    """Own standard trucks first; only an extra truck is hired, at the smallest allowed size that fits, and never
    below 6.8m on long routes. Squeezing may fill a truck past the 90% volume limit, never past 100%."""
    cfg = Config()
    t = ds["internal"]["trucks"]
    lines = ds["clean"]["lines"].set_index("line_id")
    order = ["4.2m", "6.8m", "9.6m", "13m", "17.5m"]
    for (date, lid), g in t.groupby(["date", "line_id"]):
        g = g.sort_values("x_truck_no")
        std = lines.at[lid, "standard_vehicle"]
        assert (g["vehicle_type"].iloc[:-1] == std).all()
        last = g.iloc[-1]
        if len(g) == 1:
            assert last["vehicle_type"] == std and not last["x_hired"]
            continue
        assert last["x_hired"]
        floor = 0 if lines.at[lid, "distance_km"] <= cfg.min_overflow_km_for_small_truck else 1
        assert order.index(last["vehicle_type"]) >= floor
        smaller = order[floor:order.index(last["vehicle_type"])]
        for vt in smaller:  # nothing smaller would have taken the load
            _, kg, m3 = ref.VEHICLE_TYPES[vt]
            assert last["weight_kg"] > kg or last["volume_m3"] > m3 * cfg.volume_fill_limit
    assert (t["load_factor_volume"] <= 1.0 + 1e-9).all()


def test_undeclared_hazmat_is_hidden_in_general_lines(ds):
    o, lines = ds["clean"]["orders"], ds["clean"]["lines"]
    key = ds["answer_key"]["undeclared_hazmat"]
    assert len(key) > 0
    hidden = o[o["order_id"].isin(key["order_id"])]
    assert (hidden["hazmat_class"] == "").all()
    assert (hidden["category"] != ref.HAZMAT_CATEGORY).all()
    assert not lines.set_index("line_id").loc[hidden["line_id"], "hazmat_qualified"].any()
    assert all(item in d for item, d in zip(key.sort_values("order_id")["item"], hidden.sort_values("order_id")["description"]))


def test_pooled_reference_charges_the_cross_dock_penalty(ds):
    cfg = Config()
    ops = ds["internal"]["ops"].set_index("op_id")
    pooled = ds["internal"]["pooled"].set_index("op_id")
    owner = ds["clean"]["docks"].set_index("dock_id")["owner"]
    extra = pooled["dock_end"] - pooled["dock_start"] - ops.loc[pooled.index, "service_min"]
    foreign = (owner.loc[pooled["dock_id"]].to_numpy() != ops.loc[pooled.index, "line_id"].to_numpy()) & \
        ~ops.loc[pooled.index, "hazmat"].to_numpy()
    assert foreign.any()
    assert (extra[foreign] == cfg.cross_dock_penalty_min).all()
    assert (extra[~foreign] == 0).all()


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


def test_loading_waits_for_every_delivery_on_the_truck(ds):
    c = ds["clean"]
    g = c["gate_events"].set_index("event_id")
    o = c["orders"]
    drop_end = pd.to_datetime(g.loc[o["dropoff_event_id"], "dock_end"]).to_numpy()
    load = g[g["op_type"] == "linehaul_out"].reset_index().set_index("truck_id")
    load_start = pd.to_datetime(load.loc[o["baseline_truck_id"], "dock_start"]).to_numpy()
    assert (drop_end <= load_start).all()


def test_pickup_waits_for_its_inbound_truck(ds):
    ops = ds["internal"]["ops"]
    sim = ds["internal"]["sim"].set_index("op_id")
    pick = ops[(ops["op_type"] == "pickup_out") & ops["gate_in"].notna()]
    assert (pick["after"] != "").all()
    assert (sim.loc[pick["op_id"], "dock_start"].to_numpy() >= sim.loc[pick["after"], "dock_end"].to_numpy()).all()


def test_no_shows_are_booked_pickups_without_a_gate_event(ds):
    ops = ds["internal"]["ops"]
    ns = ops[ops["no_show"]]
    assert len(ns) > 0
    assert (ns["op_type"] == "pickup_out").all() and (ns["appointment_id"] != "").all()
    assert set(ns["op_id"]).isdisjoint(ds["clean"]["gate_events"]["event_id"])
    assert set(ns["appointment_id"]) <= set(ds["clean"]["appointments"]["appointment_id"])


def test_booked_slot_holds_the_planned_time(ds):
    ops = ds["internal"]["ops"]
    b = ops[ops["appointment_id"] != ""]
    assert ((b["slot_start"] <= b["planned"]) & (b["planned"] < b["slot_end"])).all()
    assert (b["slot_end"] - b["slot_start"] == 30).all()


def test_each_plate_is_one_vehicle_in_one_place(ds):
    c = ds["clean"]
    both = pd.concat([c["gate_events"][["plate", "vehicle_type"]], c["appointments"][["plate", "vehicle_type"]]])
    assert (both.groupby("plate")["vehicle_type"].nunique() == 1).all()
    g = c["gate_events"].assign(i=lambda d: pd.to_datetime(d["gate_in"]), o=lambda d: pd.to_datetime(d["gate_out"]))
    for _, d in g.sort_values("i").groupby("plate"):
        assert (d["i"].to_numpy()[1:] >= d["o"].to_numpy()[:-1]).all()


def test_hidden_hazmat_looks_like_its_declared_category(ds):
    o = ds["clean"]["orders"]
    key = ds["answer_key"]["undeclared_hazmat"]
    hidden = o[o["order_id"].isin(key["order_id"])]
    unit = hidden["description"].str.extract(r"\d+(\D+)$")[0]
    assert (unit == hidden["category"].map(lambda c: ref.CATEGORIES[c][3])).all()


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
        elif a.anomaly_type == "route_deviation":
            assert not inside.empty
    # a moving truck moves: two pings 5 minutes apart, both with speed above 0, are at least 2 km apart
    t = traj.sort_values(["event_id", "ts"])
    same = t["event_id"].eq(t["event_id"].shift())
    km = (((t["lat"] - t["lat"].shift()) * 110.57) ** 2 + ((t["lon"] - t["lon"].shift()) * 96.2) ** 2) ** 0.5
    gap = (t["ts"] - t["ts"].shift()).dt.total_seconds() / 60
    moving = same & (gap == 5) & (t["speed_kmh"] > 0) & (t["speed_kmh"].shift() > 0)
    assert moving.any() and (km[moving] >= 2).all()
    # every stop is labelled: a zero-speed ping lies inside a long_stop window of its truck
    stops = ds["answer_key"]["trajectory_anomalies"].query("anomaly_type == 'long_stop'")
    zero = traj[traj["speed_kmh"] == 0]
    win = zero.merge(stops, on="event_id", how="left")
    assert ((win["ts"] >= pd.to_datetime(win["start"])) & (win["ts"] <= pd.to_datetime(win["end"]))).all()


def test_route_deviation_leaves_the_straight_line(ds):
    traj = ds["clean"]["trajectories"].assign(ts=lambda d: pd.to_datetime(d["ts"]))
    for a in ds["answer_key"]["trajectory_anomalies"].query("anomaly_type == 'route_deviation'").itertuples():
        p = traj[traj["event_id"] == a.event_id].sort_values("ts")
        first, last = p.iloc[0], p.iloc[-1]
        dx, dy = last["lon"] - first["lon"], last["lat"] - first["lat"]
        norm = (dx * dx + dy * dy) ** 0.5
        off = ((p["lon"] - first["lon"]) * dy - (p["lat"] - first["lat"]) * dx).abs() / norm
        inside = (p["ts"] > pd.Timestamp(a.start)) & (p["ts"] < pd.Timestamp(a.end))
        assert off[inside].max() > 3 * off[~inside].max()


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


def _clean_as_exported(name, df):
    df = df.astype(object).copy()
    if "op_type" in df:
        df["op_type"] = df["op_type"].map(mz.OP_TYPE_ZH)
    if "hazmat" in df:
        df["hazmat"] = df["hazmat"].map({True: "是", False: "否"})
    return df.rename(columns=mz.HEADERS_ZH[name])


def test_ledger_lists_exactly_the_changed_cells(ds):
    led = ds["answer_key"]["messy_injected_issues"]
    listed = {(r.table, r.key, r.column) for r in led.itertuples() if r.issue != "duplicate_row"}
    changed = set()
    for name in ("orders", "gate_events", "appointments"):
        zh = mz.HEADERS_ZH[name]
        back = {v: k for k, v in zh.items()}
        key = zh[mz.KEYS[name]]
        m = ds["messy"][name].drop_duplicates().set_index(key)
        c = _clean_as_exported(name, ds["clean"][name]).set_index(key).loc[m.index]
        for col in m.columns:
            diff = m[col].astype(str) != c[col].astype(str)
            changed |= {(name, k, back[col]) for k in m.index[diff.to_numpy()]}
    assert changed == listed


def test_messy_values_recover_to_clean(ds):
    led = ds["answer_key"]["messy_injected_issues"]
    broken = set(zip(led["key"], led["column"], led["issue"]))
    o = ds["messy"]["orders"].drop_duplicates().set_index("运单号")
    c = ds["clean"]["orders"].set_index("order_id")
    ok = o["重量"] != ""
    diff = (o.loc[ok, "重量"].map(_parse_weight) - c.loc[o.index[ok], "weight_kg"]).abs()
    assert diff.max() <= 0.051

    g = ds["messy"]["gate_events"].drop_duplicates().set_index("作业编号")
    cg = ds["clean"]["gate_events"].set_index("event_id")
    for col in ("gate_in", "dock_start", "dock_end", "gate_out"):
        zh = mz.HEADERS_ZH["gate_events"][col]
        for k, v in g[zh].items():
            if v == "" or (k, col, "wrong_year") in broken or (k, col, "end_before_start") in broken:
                continue
            assert _parse_time(v) == pd.Timestamp(cg.at[k, col]), (k, col, v)
