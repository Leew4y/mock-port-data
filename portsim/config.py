"""Generation parameters. Every default is an invented assumption for rehearsal, not a measured figure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Config:
    seed: int = 20261003
    start_date: str = "2026-09-14"  # a Monday
    days: int = 14

    # Tenants (LTL lines) and docks
    n_general_lines: int = 28
    n_hazmat_lines: int = 2
    n_general_docks: int = 36
    n_hazmat_docks: int = 4

    # Demand
    mean_orders_per_line_day: float = 25.0
    mean_order_volume_m3: float = 1.7  # used only to size each line's standard truck
    max_order_volume_m3: float = 12.0  # an LTL order above this would ship as a full truck, so none is generated
    p_undeclared_hazmat: float = 0.004  # share of general-line orders that hide hazardous goods

    # Loading
    volume_fill_limit: float = 0.9  # usable share of a vehicle's volume
    min_overflow_km_for_small_truck: int = 600  # beyond this distance an overflow truck is at least 6.8m

    # Appointments and arrivals
    p_no_show: float = 0.05  # booked pickup vans that never come
    approach_min: int = 5  # gate to dock drive time
    cross_dock_penalty_min: int = 15  # extra handling when a truck uses another line's dock (pooled reference only)
    local_van_turnaround_min: int = 30  # a local van seen at the gate cannot come back sooner than this

    # Optional outputs
    trajectories: bool = True
    messy: bool = True

    def __post_init__(self):
        # ids carry the date as MMDD, so a run longer than a year would repeat them
        if not 1 <= self.days <= 365:
            raise ValueError(f"days must be between 1 and 365, got {self.days}")
        try:
            date.fromisoformat(self.start_date)
        except (TypeError, ValueError):
            raise ValueError(f"start_date must be a date as YYYY-MM-DD, got {self.start_date!r}") from None
        if self.n_general_docks < self.n_general_lines:
            raise ValueError("every general line needs at least one dock")
