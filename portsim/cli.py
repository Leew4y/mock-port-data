"""Command line: python -m portsim --out out"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build import build_dataset, write_dataset
from .config import Config


def main(argv=None) -> None:
    d = Config()
    p = argparse.ArgumentParser(prog="portsim", description=__doc__)
    p.add_argument("--out", default="out", help="output folder (default: out)")
    p.add_argument("--seed", type=int, default=d.seed)
    p.add_argument("--days", type=int, default=d.days)
    p.add_argument("--start-date", default=d.start_date)
    p.add_argument("--no-trajectories", action="store_true")
    p.add_argument("--no-messy", action="store_true")
    a = p.parse_args(argv)
    cfg = Config(seed=a.seed, days=a.days, start_date=a.start_date,
                 trajectories=not a.no_trajectories, messy=not a.no_messy)
    ds = build_dataset(cfg)
    write_dataset(ds, Path(a.out))
    s = ds["summary"]
    print(json.dumps({"out": a.out, **s["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
