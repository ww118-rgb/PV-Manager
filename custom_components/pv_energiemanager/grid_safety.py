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
    """Physical budget is continuous across any grid-import threshold.

    Positive battery power means charging. The safety lane independently
    decides whether active loads must be reduced to prevent grid import.
    Never discard the entire charging term at a 1-kW threshold: doing so
    turns a two-watt meter change into a multi-kilowatt budget jump.
    The urgent_import_w argument is retained for backward compatibility.
    """
    return grid_w + battery_charge_w + accounted_w - reserve_w


def cap_budget_on_import(
    grid_w: float, physical_budget_w: float, commanded_w: float,
    *, deadband_w: float = 150,
) -> float:
    """Do not INCREASE controlled load while currently importing power.

    Already-commanded load may be reassigned to higher priorities, but the
    combined targets must not grow. The independent safety lane still
    handles large imports by immediately curtailing.
    """
    if grid_w < -deadband_w:
        return min(physical_budget_w, max(0.0, commanded_w))
    return physical_budget_w


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
