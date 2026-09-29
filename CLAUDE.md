# portsim: mock data for one simulated highway port

Seeded generator of two weeks of synthetic records for one highway freight port (公路港), built for team 不系舟's
24-hour rehearsal on 2026-10-03 and as a fallback if the official data is late. Its own local git repository,
nested in `~/Desktop/hackathon` and ignored there. Not on GitHub: putting it in the team org `Leew4y` is the owner's
call. `README.md` is the user guide; `docs/data_dictionary.md` and `docs/scenario_brief_zh.md` (the mock brief, in
Chinese) are copied into every output folder.

## Commands

Every Python or uv command runs through the memory guard (a hook refuses it otherwise):

```bash
python3 ~/.claude/scripts/local_guard.py --max-gb 2 --wait 600 -- uv run pytest -q       # 31 tests, about 15 s
python3 ~/.claude/scripts/local_guard.py --max-gb 1 --wait 600 -- uv run python -m portsim --out out   # about 5 s, 6 MB
```

Options: `--seed`, `--days` (1 to 365), `--start-date`, `--no-trajectories`, `--no-messy`. `out/` is ignored.

## How a build runs (`portsim/build.py`)

1. `entities.py`: lines, docks, orders; every plate comes from one `PlateBook`, so no two vehicles share a plate.
2. `dispatch.py`: today's practice, each line packing its own orders (first-fit-decreasing; only an extra truck is
   hired and downsized).
3. `operations.py`: truck visits. A visit's `after` lists the visits it waits for: loading waits for the deliveries
   of its orders, a pickup van for the inbound truck it collects from.
4. `docksim.py`: event-driven first-come-first-served queue, run twice: own docks (today, which writes the gate
   records) and pooled (a naive reference, not a solution). KPIs split the wait into queueing and waiting for cargo.
5. `operations.assign_local_plates`: van plates are issued after the simulation, so a van is never at the port twice
   at once.
6. `trajectories.py`, `messy.py` (messy copies plus a ledger of every changed cell), then the summary.

Random streams: `np.random.SeedSequence(seed).spawn(6)`, one stream per stage in a fixed order. Appending a stream
keeps the others; reordering them changes every output.

## Conventions

- Every port parameter is an invented assumption and lives in `config.py` or `reference.py`; the docs say so.
  `hazmat_rules_illustrative` is not the JT/T 617.6 table.
- The same seed gives byte-identical files in any process (`test_output_does_not_depend_on_hash_seed`): output must
  not depend on set or dict iteration order.
- Internal columns start with `x_` (pandas `itertuples` renames columns that start with `_`) and are dropped from
  the written tables. `build_dataset(...)["internal"]` exposes the visits and simulations to tests only.
- A change that moves the default-run numbers updates the table in `README.md`, the figures in
  `docs/data_dictionary.md`, and the one-line summary in the parent repo's event `NOTES.md` (Files table).
- The tests added with the 2026-09-29 fixes were checked by breaking the code on purpose in scratch copies: each
  failed on the broken code and passed on the fixed code.
