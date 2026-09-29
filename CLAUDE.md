# portsim: mock data for one simulated highway port

Seeded generator of two weeks of synthetic records for one highway freight port (公路港), built for team 不系舟's
24-hour rehearsal on 2026-10-03 and as a fallback if the official data is late. Its own local git repository,
nested in `~/Desktop/hackathon` and ignored there. Not on GitHub: putting it in the team org `Leew4y` is the owner's
call. `README.md` is the user guide; `docs/data_dictionary.md` and `docs/scenario_brief_zh.md` (the mock brief, in
Chinese) are copied into every output folder. Open sessions in `~/Desktop/hackathon`, not here: this folder is its
own git repository, so a session opened here gets a separate, empty memory store and misses the event's `NOTES.md`.

## Commands

Run Python through the memory guard (the user-level hook refuses `uv run` without it):

```bash
python3 ~/.claude/scripts/local_guard.py --max-gb 2 --wait 600 -- uv run pytest -q       # 40 tests, about 35 s
python3 ~/.claude/scripts/local_guard.py --max-gb 1 --wait 600 -- uv run python -m portsim --out out   # about 5 s, 6 MB
```

The lock is shared with other sessions' long jobs; a call waiting for it can outlast the Bash tool's 2-minute
default, so run it in the background or give it a 600000 ms timeout. Options: `--seed`, `--days` (1 to 365),
`--start-date`, `--no-trajectories`, `--no-messy`. `out/` is ignored.

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
  `reference.py`; the rest are hard-coded in the other modules, and `docs/data_dictionary.md` (top) lists them by
  module. A new hard-coded value goes into that list. `hazmat_rules_illustrative` is not the JT/T 617 table.
- The same seed gives byte-identical files in any process (`test_output_does_not_depend_on_hash_seed`): output must
  not depend on set or dict iteration order.
- Internal columns start with `x_` (pandas `itertuples` renames columns that start with `_`) and are dropped from
  the written tables. `build_dataset(...)["internal"]` exposes the visits and simulations to tests only.
- A change that moves the default-run numbers updates the table in `README.md`, the figures in
  `docs/data_dictionary.md`, and the one-line summary in the parent repo's event `NOTES.md` (Files table).
- The tests added with the 2026-09-29 fixes were checked by breaking the code on purpose in scratch copies: each
  fails on its broken copy and passes on the clean one. First round (ledger, visit dependencies, the short-trip
  trajectory horizon, plate clash check, downsizing, hidden hazmat unit): the trajectory test was strengthened after
  its first attempt missed; one first run failed on a bug in the mutation script and passed when rerun. Second round
  (hidden hazmat weight and density, dock tie-break, the 3 m3 squeeze, hazmat line sizing, the saturated-port plate
  fix, internal columns, the CLI usage error, fleet plates): all caught. The fleet-plate test first ran on the
  default port, where no line sends more than one own truck a day, and missed a bug that gave every own truck the
  same plate; it now builds with small standard trucks and the post-simulation plate fix switched off. Older tests
  were not checked this way.
