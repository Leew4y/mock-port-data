"""Tests of portsim.evaluate: today's practice, scored as a plan, must reproduce the generator's baseline, and plans
that break a rule must be refused with a readable message."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from portsim import Config, build_dataset, write_dataset
from portsim import evaluate as ev
from portsim import reference as ref
from portsim.build import _times
from portsim.dispatch import first_fit_decreasing

CFG = Config(trajectories=False, messy=False)


@pytest.fixture(scope="module")
def built():
    return build_dataset(CFG)


@pytest.fixture(scope="module")
def ctx(built):
    return ev.context_from_dataset(CFG, built)


def _drop_extra(k: dict) -> dict:
    return {key: v for key, v in k.items() if key != "visits_at_another_lines_dock"}


# ----------------------------------------------------------------------------------------------------- docks


def test_today_as_a_dock_plan_reproduces_the_baseline(ctx):
    res = ev.evaluate_docks(ctx, ev.today_dock_plan(ctx))
    assert _drop_extra(res["plan"]) == ctx["summary"]["baseline_owned_docks"]
    assert res["plan"] == res["today"]
    assert res["plan"]["visits_at_another_lines_dock"] == 0


def test_pooled_reference_as_a_plan_reproduces_its_numbers(ctx, built):
    pooled = built["internal"]["pooled"]
    plan = pd.DataFrame({"event_id": pooled["op_id"], "dock_id": pooled["dock_id"],
                         "planned_start": _times(CFG, pooled["dock_start"])})
    res = ev.evaluate_docks(ctx, plan)
    assert _drop_extra(res["plan"]) == ctx["summary"]["reference_pooled_fcfs_not_a_solution"]
    assert res["plan"]["visits_at_another_lines_dock"] > 0


def test_a_one_day_plan_scores_that_day_only(ctx):
    g = ctx["gate_events"]
    day = g["date"].iloc[0]
    plan = ev.today_dock_plan(ctx)[g["date"] == day]
    res = ev.evaluate_docks(ctx, plan)
    assert res["dates"] == [day]
    assert res["today"]["dock_visits"] == int((g["date"] == day).sum())


def test_a_day_with_a_visit_left_out_is_refused(ctx):
    g = ctx["gate_events"]
    plan = ev.today_dock_plan(ctx)[g["date"] == g["date"].iloc[0]].iloc[1:]
    with pytest.raises(ev.PlanError, match="leaves out 1 visit"):
        ev.evaluate_docks(ctx, plan)


def test_a_hazmat_truck_at_a_general_dock_is_refused(ctx):
    plan = ev.today_dock_plan(ctx)
    i = ctx["gate_events"].index[ctx["gate_events"]["hazmat"]][0]
    plan.loc[i, "dock_id"] = "G01"
    with pytest.raises(ev.PlanError, match="hazmat trucks must use hazmat docks"):
        ev.evaluate_docks(ctx, plan)


def test_loading_placed_before_its_own_delivery_on_one_dock_is_refused(ctx):
    ops = ctx["ops"].set_index("op_id")
    g = ctx["gate_events"]
    load = g[(g["op_type"] == "linehaul_out") & ~g["hazmat"]].iloc[0]
    delivery = ops.at[load["event_id"], "after"].split(";")[0]
    plan = ev.today_dock_plan(ctx).set_index("event_id")
    plan.loc[delivery, "dock_id"] = load["dock_id"]
    t = pd.Timestamp(plan.loc[delivery, "planned_start"]) - pd.Timedelta(seconds=1)
    plan.loc[load["event_id"], "planned_start"] = t.strftime("%Y-%m-%d %H:%M:%S")
    with pytest.raises(ev.PlanError, match="contradicts which visit waits for which"):
        ev.evaluate_docks(ctx, plan.reset_index())


def test_another_lines_dock_costs_the_extra_handling(ctx):
    g = ctx["gate_events"]
    docks = ctx["docks"].set_index("dock_id")
    v = g[(g["op_type"] == "delivery_in") & ~g["hazmat"]].iloc[0]
    other = next(d for d in docks.index if docks.at[d, "dock_type"] == "general" and docks.at[d, "owner"] != v["line_id"])
    plan = ev.today_dock_plan(ctx)
    plan.loc[plan["event_id"] == v["event_id"], ["dock_id", "planned_start"]] = [other, f"{v['date']} 23:59:59"]
    sim, _ = ev.schedule_docks(ctx, plan)
    row = sim.set_index("op_id").loc[v["event_id"]]
    service = int(ctx["ops"].set_index("op_id").at[v["event_id"], "service_min"])
    assert row["dock_end"] - row["dock_start"] == service + CFG.cross_dock_penalty_min
    assert sim["x_cross_dock"].sum() == 1


def test_two_visits_with_the_same_dock_and_start_are_refused(ctx):
    plan = ev.today_dock_plan(ctx)
    a, b = plan[plan["dock_id"] == "G01"].index[:2]
    plan.loc[b, "planned_start"] = plan.loc[a, "planned_start"]
    with pytest.raises(ev.PlanError, match="share a dock and a planned start"):
        ev.evaluate_docks(ctx, plan)


# ----------------------------------------------------------------------------------------------------- loads


def test_today_as_a_load_plan_reproduces_the_baseline(ctx):
    res = ev.evaluate_loads(ctx, ev.today_load_plan(ctx))
    base, got = ctx["summary"]["baseline_dispatch"], res["plan"]
    assert got["mean_load_factor"] == base["mean_load_factor"]
    assert got["share_trucks_below_60pct_load"] == base["share_trucks_below_60pct_load"]
    assert got["trucks_per_day"] == base["trucks_per_day"]
    assert got["trucks_with_illustrative_conflict"] == base["trucks_with_illustrative_conflict"]
    assert got["trucks_carrying_hidden_hazmat"] == base["trucks_carrying_undeclared_hazmat"]
    assert got["of_which_illustrative_conflict_with_hidden"] == base["of_which_illustrative_conflict_with_food"]
    assert got == res["today"]


def _pooled_by_destination(ctx, day: str) -> pd.DataFrame:
    """A simple pooled plan: one evening's orders to each city packed together into that city's largest standard
    truck (declared hazmat apart), first-fit-decreasing at the 90% fill limit."""
    o = ctx["orders"][ctx["orders"]["date"] == day]
    std = ctx["lines"].set_index("line_id")["standard_vehicle"]
    rows = []
    for (dest, hz), grp in o.groupby([o["destination"], o["hazmat_class"] != ""], sort=True):
        vt = max(set(std[grp["line_id"]]), key=lambda t: ref.VEHICLE_TYPES[t][2])
        _, kg, m3 = ref.VEHICLE_TYPES[vt]
        for k, idx in enumerate(first_fit_decreasing(grp, kg, m3 * CFG.volume_fill_limit)):
            for i in idx:
                rows.append({"order_id": grp.at[i, "order_id"], "truck_id": f"{dest}-{int(hz)}-{k}",
                             "vehicle_type": vt})
    return pd.DataFrame(rows)


def test_pooling_by_destination_needs_fewer_and_fuller_trucks(ctx):
    day = ctx["orders"]["date"].iloc[0]
    res = ev.evaluate_loads(ctx, _pooled_by_destination(ctx, day))
    assert res["dates"] == [day]
    assert res["plan"]["trucks"] < res["today"]["trucks"]
    assert res["plan"]["mean_load_factor"] > res["today"]["mean_load_factor"]


def _one_day_today(ctx):
    day = ctx["orders"]["date"].iloc[0]
    plan = ev.today_load_plan(ctx)
    return plan[ctx["orders"]["date"] == day].reset_index(drop=True)


def test_two_destinations_on_one_truck_are_refused(ctx):
    plan = _one_day_today(ctx)
    o = ctx["orders"].set_index("order_id")
    a = plan.index[0]
    b = next(i for i in plan.index if o.at[plan.at[i, "order_id"], "destination"] !=
             o.at[plan.at[a, "order_id"], "destination"] and o.at[plan.at[i, "order_id"], "hazmat_class"] == "")
    plan.loc[b, ["truck_id", "vehicle_type"]] = plan.loc[a, ["truck_id", "vehicle_type"]].to_list()
    with pytest.raises(ev.PlanError, match="more than one destination"):
        ev.evaluate_loads(ctx, plan)


def test_an_overloaded_truck_is_refused(ctx):
    plan = _one_day_today(ctx)
    o = ctx["orders"].set_index("order_id")
    busiest = plan.groupby("truck_id")["order_id"].count().idxmax()
    plan.loc[plan["truck_id"] == busiest, "vehicle_type"] = "4.2m"
    assert o.loc[plan.loc[plan["truck_id"] == busiest, "order_id"], "volume_m3"].sum() > ref.VEHICLE_TYPES["4.2m"][2]
    with pytest.raises(ev.PlanError, match="exceed a 4.2m truck"):
        ev.evaluate_loads(ctx, plan)


def test_declared_hazmat_with_other_goods_is_refused(ctx):
    o = ctx["orders"].set_index("order_id")
    day = next(d for d in sorted(set(o["date"])) if ((o["date"] == d) & (o["hazmat_class"] != "")).any())
    plan = ev.today_load_plan(ctx)
    plan = plan[ctx["orders"]["date"] == day].reset_index(drop=True)
    declared = o.loc[plan["order_id"], "hazmat_class"].to_numpy() != ""
    h = plan.index[declared][0]
    hz_dest = o.at[plan.at[h, "order_id"], "destination"]
    same = [i for i in plan.index[~declared] if o.at[plan.at[i, "order_id"], "destination"] == hz_dest]
    i = same[0] if same else plan.index[~declared][0]
    if not same:  # no general order to that city this day: move the hazmat order onto a general truck instead
        plan.loc[h, ["truck_id", "vehicle_type"]] = plan.loc[i, ["truck_id", "vehicle_type"]].to_list()
        match = "declared hazmat orders together with other goods|more than one destination"
    else:
        plan.loc[i, ["truck_id", "vehicle_type"]] = plan.loc[h, ["truck_id", "vehicle_type"]].to_list()
        match = "declared hazmat orders together with other goods"
    with pytest.raises(ev.PlanError, match=match):
        ev.evaluate_loads(ctx, plan)


def test_an_empty_plan_is_refused(ctx):
    with pytest.raises(ev.PlanError, match="no rows"):
        ev.evaluate_docks(ctx, ev.today_dock_plan(ctx).iloc[:0])
    with pytest.raises(ev.PlanError, match="no rows"):
        ev.evaluate_loads(ctx, ev.today_load_plan(ctx).iloc[:0])


def test_orders_listed_twice_or_left_out_are_refused(ctx):
    plan = _one_day_today(ctx)
    with pytest.raises(ev.PlanError, match="listed twice"):
        ev.evaluate_loads(ctx, pd.concat([plan, plan.iloc[:1]]))
    with pytest.raises(ev.PlanError, match="leaves out 1 order"):
        ev.evaluate_loads(ctx, plan.iloc[1:])


def test_holding_orders_is_scored_against_the_hidden_hazmat(ctx):
    hidden = set(ctx["undeclared"]["order_id"])
    o = ctx["orders"]
    day = next(d for d in sorted(set(o["date"])) if o.loc[o["date"] == d, "order_id"].isin(hidden).any())
    plan = ev.today_load_plan(ctx)
    plan = plan[o["date"] == day].reset_index(drop=True)
    ordinary = plan.index[~plan["order_id"].isin(hidden)][0]
    hold = plan["order_id"].isin(hidden)
    hold[ordinary] = True
    plan.loc[hold, "hold"] = "1"
    got = ev.evaluate_loads(ctx, plan)["plan"]
    n = int(plan["order_id"].isin(hidden).sum())
    assert got["hidden_hazmat_orders"] == n and got["hidden_hazmat_held"] == n
    assert got["ordinary_orders_held"] == 1 and got["orders_held"] == n + 1
    assert got["trucks_carrying_hidden_hazmat"] == 0


# ------------------------------------------------------------------------------------------------------- CLI


def test_cli_scores_a_plan_and_refuses_a_bad_one(tmp_path, capsys):
    cfg = Config(days=2, trajectories=False)
    out = tmp_path / "out"
    write_dataset(build_dataset(cfg), out)
    g = pd.read_csv(out / "clean" / "gate_events.csv", dtype=str, keep_default_na=False)
    plan = tmp_path / "plan.csv"
    g.rename(columns={"dock_start": "planned_start"})[["event_id", "dock_id", "planned_start"]].to_csv(plan, index=False)
    ev.main(["docks", str(plan), "--data", str(out), "--json"])
    res = json.loads(capsys.readouterr().out)
    assert res["plan"] == res["today"]
    pd.read_csv(plan, dtype=str).iloc[1:].to_csv(plan, index=False)
    with pytest.raises(SystemExit) as e:
        ev.main(["docks", str(plan), "--data", str(out)])
    assert e.value.code == 1
    assert "leaves out" in capsys.readouterr().err


def test_cli_refuses_a_folder_that_does_not_match_its_config(tmp_path, capsys):
    out = tmp_path / "out"
    write_dataset(build_dataset(Config(days=2, trajectories=False, messy=False)), out)
    s = json.loads((out / "answer_key" / "baseline_summary.json").read_text(encoding="utf-8"))
    s["config"]["seed"] += 1
    (out / "answer_key" / "baseline_summary.json").write_text(json.dumps(s), encoding="utf-8")
    plan = tmp_path / "plan.csv"
    plan.write_text("event_id,dock_id,planned_start\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        ev.main(["docks", str(plan), "--data", str(out)])
    assert e.value.code == 1
    assert "does not match" in capsys.readouterr().err
