"""Fast grid import protection, separate from the normal PV allocator.

Only curtails, using the physically measured grid meter as authority.
A charging automatic battery may not stop charging instantly during import.
"""
from __future__ import annotations

from .engine import Consumer, distribute


def budget_with_grid_priority(
    grid_w: float, battery_charge_w: float,
    accounted_w: float, reserve_w: float, *, urgent_import_w: float = 1000,
) -> float:
    """Signed grid: export positive, import negative; charge positive."""
    battery_credit = (min(0.0, battery_charge_w)
                      if grid_w <= -urgent_import_w else battery_charge_w)
    return grid_w + battery_credit + accounted_w - reserve_w


def safety_targets(
    grid_w: float, consumers: list[Consumer], previous: dict[str, int],
    *, threshold_w: float = 1000, margin_w: float = 300,
) -> dict[str, int]:
    """Reduce active outputs; never increase any output in the safety lane."""
    old = {d.id: max(0, int(previous.get(d.id, 0))) for d in consumers}
    if grid_w > -threshold_w or sum(old.values()) <= 0:
        return old
    target_budget = max(0.0, sum(old.values()) + grid_w - margin_w)
    allocation = distribute(target_budget, consumers).targets
    return {ident: min(old[ident], allocation[ident]) for ident in old}
