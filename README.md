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

Options: `--seed`, `--days` (1 to 365, default 14), `--start-date` (default 2026-09-14), `--no-trajectories`,
`--no-messy`. The same seed gives byte-identical files, whatever `PYTHONHASHSEED` is, with the versions locked in
`uv.lock` under Python 3.13 (`.python-version`; numpy 2.5.3, pandas 3.0.6); other versions may change the numbers.
A 14-day run takes a few
seconds and under 0.2 GB of memory; output is about 6 MB.

Read the CSVs with `dtype=str` (e.g. `pd.read_csv(path, dtype=str, keep_default_na=False)`): otherwise pandas turns
hazmat classes such as `3` into `3.0` and empty cells into NaN.

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
`data_dictionary.md` and `scenario_brief_zh.md`. Keep the other clean tables and `answer_key/` for scoring. The messy
orders carry each order's delivery visit (送货作业编号) and baseline truck (干线车次), as real exports do, so today's
dispatch can be rebuilt from them; the clean tables are withheld for the data-cleaning part, not to hide it.

## What the default seed produces (14 days; simulated, 模拟数据)

From `answer_key/baseline_summary.json`:

| | Value |
|---|---|
| orders | 9,292 |
| dock visits | 7,738 (about 550 a day) |
| mean wait before service, own docks only (today) | 28 min (26 queueing for a dock, 2 waiting for cargo); p90 92 min; 16% wait over an hour |
| same arrivals, any dock, 15 min extra on another line's dock (naive reference) | 8 min |
| linehaul trucks leaving after their planned departure (today) | 20%, 77 min late on average when late |
| linehaul trucks, lines load only their own orders (today) | 34 a day, mean load factor 0.58, 53% under 0.6 |
| trucks carrying hidden hazardous goods | 34 (36 orders) |

The simulated baseline leaves both skeletons of the team's thesis something to improve on: own-dock queues (skeleton A)
and half-empty trucks to the same city (skeleton B). The pooled figure is a naive reference, not a solution and not
a claimed saving; the parameters were chosen so that these problems appear, so the size of any saving on this data
says nothing about a real port. The late-departure share hardly depends on the docks: the pooled reference still
gives 17.7%, and a check on 2026-09-29 found about 19% would leave late with no dock queue at all. Lateness here comes
mostly from when trucks arrive to load and how long loading takes, so do not claim a dock-scheduling saving from it.

## Known simplifications

- One port, straight-line truck movements at constant speed, no road network, no slowdown near the port.
- Every order is loaded the same evening (15 of the 480 linehaul trucks in the default run leave after midnight),
  and loading starts only after every order on the truck has been unloaded; no carry-over. A line with one
  truck that day runs its own standard truck however empty; only an extra truck is hired, at the smallest size that
  fits (at least 6.8m beyond 600 km).
- Inbound cargo has no order records; each pickup van loads from one inbound truck, after it is unloaded.
- Dock service time depends only on cargo volume and operation type; no crew or forklift limits.
- Appointments are not checked against dock capacity; about 30% of booked trucks arrive after their slot ends.
- `hazmat_rules_illustrative.csv` is not the JT/T 617.6 mixing table (not read; check the 2018 text together with its 2024-05-07 amendment No. 1); replace it before any claim.
- Real hazardous-goods transport needs qualified vehicles and operators; here hazmat lines simply use H docks.

## Code

| File | Role |
|---|---|
| `portsim/config.py`, `portsim/reference.py` | the main assumptions (the rest are hard-coded in the other modules; `docs/data_dictionary.md` lists them) |
| `portsim/entities.py` | lines, docks, plates, orders (incl. hidden hazmat) |
| `portsim/dispatch.py` | today's per-line linehaul packing |
| `portsim/operations.py` | truck visits, appointments, arrival delays, service times |
| `portsim/docksim.py` | first-come-first-served dock queue (own docks, or pooled reference) and KPIs |
| `portsim/trajectories.py` | GPS pings with labelled anomalies |
| `portsim/messy.py` | messy copies and the issue ledger |
| `portsim/build.py`, `portsim/cli.py` | assembly and writing |
