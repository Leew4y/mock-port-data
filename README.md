# portsim: mock data for one simulated highway freight port

Seeded generator of two weeks of synthetic records for one highway freight port (公路港): LTL lines renting docks,
LTL orders, appointments, gate and dock events, today's linehaul dispatch, GPS pings of inbound trucks, messy
copies of the business tables, and an answer key. Built for team 不系舟 (Leew4y)'s 24-hour rehearsal on
2026-10-03 for the 传化 × 动势 AI Architect Challenge (AI + 物流 track), and as a fallback dataset if the official
data arrives late or incomplete.

**All data is synthetic and every port parameter is an invented assumption.** Nothing here describes a real
Transfar port. Label any number taken from it as simulated.

## Run

```bash
uv sync
uv run python -m portsim --out out
uv run pytest
```

Options: `--seed`, `--days` (default 14), `--start-date` (default 2026-09-14), `--no-trajectories`, `--no-messy`.
The same seed gives byte-identical files. A 14-day run takes a few seconds and under 0.2 GB of memory; output is
about 6 MB.

## Output

```
out/
  clean/        tidy tables (English headers, UTF-8)
  messy/        orders, gate_events, appointments as exported business data (Chinese headers, injected problems)
  answer_key/   baseline_summary.json, undeclared_hazmat.csv, trajectory_anomalies.csv, messy_injected_issues.csv
  data_dictionary.md
  scenario_brief_zh.md   the mock brief for the rehearsal (Chinese)
```

For the rehearsal, hand out `messy/`, `clean/{lines,docks,vehicle_types,hazmat_rules_illustrative,trajectories}.csv`,
`data_dictionary.md` and `scenario_brief_zh.md`. Keep the other clean tables and `answer_key/` for scoring.

## What the default seed produces (14 days)

From `answer_key/baseline_summary.json`:

| | Value |
|---|---|
| orders | 9,206 |
| dock visits | 7,878 (about 560 a day) |
| mean queue wait, own docks only (today) | 35 min; p90 126 min; 20% wait over an hour |
| same arrivals, any dock, 15 min extra on another line's dock (naive reference) | 10 min |
| linehaul trucks, lines load only their own orders (today) | 35 a day, mean load factor 0.68, 31% under 0.6 |
| trucks carrying hidden hazardous goods | 30 |

So both skeletons of the team's thesis have room to show a saving: pooling docks at port level (skeleton A) and
pooling orders across lines to the same city (skeleton B).

## Known simplifications

- One port, straight-line truck movements, no road network.
- Every order leaves the same evening; no carry-over, no capacity sold on the 配载 market.
- Dock service time depends only on cargo volume and operation type; no crew or forklift limits.
- `hazmat_rules_illustrative.csv` is not the JT/T 617.6 mixing table (not read); replace it before any claim.
- Real hazardous-goods transport needs qualified vehicles and operators; here hazmat lines simply use H docks.

## Code

| File | Role |
|---|---|
| `portsim/config.py`, `portsim/reference.py` | all assumptions |
| `portsim/entities.py` | lines, docks, plates, orders (incl. hidden hazmat) |
| `portsim/dispatch.py` | today's per-line linehaul packing |
| `portsim/operations.py` | truck visits, appointments, arrival delays, service times |
| `portsim/docksim.py` | first-come-first-served dock queue (own docks, or pooled reference) and KPIs |
| `portsim/trajectories.py` | GPS pings with labelled anomalies |
| `portsim/messy.py` | messy copies and the issue ledger |
| `portsim/build.py`, `portsim/cli.py` | assembly and writing |
