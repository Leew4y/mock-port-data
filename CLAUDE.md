# portsim: mock data for one simulated highway port

Seeded generator of two weeks of synthetic records for one highway freight port (公路港), built for team 不系舟's
24-hour rehearsal on 2026-10-03 and as a fallback if the official data is late. Private repository in the team's
GitHub organization, https://github.com/Leew4y/mock-port-data (the owner's decision, 2026-09-29). `README.md` is
the user guide; `docs/data_dictionary.md` and `docs/scenario_brief_zh.md` (the mock brief, in Chinese) are copied
into every output folder. Numbers from this data go into a pitch or README only as the README's "Using the numbers"
section allows.

On the owner's Mac this folder sits inside `~/Desktop/hackathon`, a separate repository that ignores it. Open
sessions there, not here: a session opened here gets a separate, empty memory store and misses the event's
`NOTES.md`. In a teammate's clone, this file and the README are the whole context.

## Commands

```bash
uv run pytest -q                       # 42 tests, about 20 s to a minute depending on load
uv run python -m portsim --out out     # about 5 s, 6 MB
```

On the owner's Mac, run both through the memory guard (the owner's user-level hook refuses `uv run` without it):

```bash
python3 ~/.claude/scripts/local_guard.py --max-gb 2 --wait 600 -- uv run pytest -q
python3 ~/.claude/scripts/local_guard.py --max-gb 1 --wait 600 -- uv run python -m portsim --out out
```

The guard's lock is shared with other sessions' long jobs; a call waiting for it can outlast the Bash tool's
2-minute default, so run it in the background or give it a 600000 ms timeout. Options: `--seed`, `--days` (1 to 365),
`--start-date` (YYYY-MM-DD), `--no-trajectories`, `--no-messy`; a bad `--days` or `--start-date` is a usage
error. `out/` is ignored.

## How a build runs (`portsim/build.py`)

1. `entities.py`: lines, docks, orders; every plate comes from one `PlateBook`, so no two vehicles share a plate.
2. `dispatch.py`: today's practice, each line packing its own orders (first-fit-decreasing; a leftover under 3 m3
   is squeezed into the earlier trucks up to their full volume; only an extra truck is hired and downsized).
3. `operations.py`: truck visits. A visit's `after` lists the visits it waits for: loading waits for the deliveries
   of its orders, a pickup van for the inbound truck it collects from.
4. `docksim.py`: event-driven first-come-first-served queue, run twice: own docks (today, which writes the gate
   records) and pooled (a naive reference, not a solution). KPIs split the wait into queueing and waiting for cargo.
5. `operations.free_busy_fleet_plates`, then `operations.assign_local_plates`: after the simulation a linehaul
   visit whose plate is still inside gets another (only on a saturated port), and van plates are issued, so no
   vehicle is at the port twice at once.
6. `trajectories.py`, `messy.py` (messy copies plus a ledger of every injected issue; the export's systematic
   changes, such as Chinese headers and GB18030 for orders, are not in the ledger), then the summary.

Random streams: `np.random.SeedSequence(seed).spawn(6)`, unpacked in this order: static (lines and their fleet
plates; docks draw nothing), orders, ops, traj, messy, plates. Appending a stream keeps the others; reordering
them changes every output.

## Conventions

- Every port parameter is an invented assumption; the docs say so. The main ones live in `config.py` and
  `reference.py`; the rest are hard-coded in the other modules, and `docs/data_dictionary.md` (top) lists by module
  the ones that shape the data (small noise terms, such as GPS jitter, are left out). A new one goes into that
  list. `hazmat_rules_illustrative` is not the JT/T 617 table.
- The same seed gives byte-identical files in any process (`test_output_does_not_depend_on_hash_seed`): output must
  not depend on set or dict iteration order.
- Internal columns start with `x_` (pandas `itertuples` renames columns that start with `_`) and are dropped from
  the written tables. `build_dataset(...)["internal"]` exposes the visits and simulations to tests only.
- A change that moves the default-run numbers updates the table in `README.md`, the figures in
  `docs/data_dictionary.md`, and, on the owner's Mac, the one-line summary in the parent repo's event `NOTES.md`
  (Files table).
- The tests added with the 2026-09-29 fixes were checked by breaking the code on purpose in scratch copies: each
  fails on its broken copy and passes on the clean one. First round (ledger, visit dependencies, the short-trip
  trajectory horizon, plate clash check, downsizing, hidden hazmat unit): the trajectory test was strengthened after
  its first attempt missed; one first run failed on a bug in the mutation script and passed when rerun. Second round
  (hidden hazmat weight and density, dock tie-break, the 3 m3 squeeze, hazmat line sizing, the saturated-port plate
  fix, internal columns, the CLI usage error, fleet plates): each test failed on the broken copy aimed at it. The
  one-line-one-day plate test first ran on the default port, where no line sends more than one own truck a day, and
  missed a bug that gave every own truck the same plate; it now builds with small standard trucks and the
  post-simulation plate fix switched off. That same bug leaves the default-port fleet test passing, as expected: it
  checks that plates come from the right fleet, and fails when inbound trucks take outbound plates. Third round,
  after the second review: the hazmat sizing test, which on the default seed could not tell the weight rule from a
  fixed 6.8m or from the volume rule, now also builds busier hazmat lines; the start-date check is new. The rounds
  ran on the working tree just before each commit (scratch harness `mut3.py`, not kept in the repository). Older
  tests were not checked this way.
