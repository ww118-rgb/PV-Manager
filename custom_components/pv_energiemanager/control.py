"""One deterministic EMS calculation per cycle; no timing and no I/O."""
from __future__ import annotations

from dataclasses import dataclass

from .engine import Consumer, distribute

# Minor import from a fluctuating house load is not worth an entire EVSE step.
GRID_DEADBAND_W = 150


@dataclass(frozen=True)
class CyclePlan:
    physical_budget: float
    allowed_budget: float
    targets: dict[str, int]
    group_records: list[dict]


def plan_cycle(
    grid_w: float,
    battery_charge_w: float,
    accounted_w: float,
    reserve_w: float,
    consumers: list[Consumer],
    previous: dict[str, int],
    *,
    grid_deadband_w: float = GRID_DEADBAND_W,
) -> CyclePlan:
    """Create a complete output plan from one Home Assistant state snapshot.

    Positive grid means export; negative grid means import.
    Positive battery means charging; negative means discharging.

    Measured charging remains in the *physical* budget, which is continuous.
    Import limits the permitted load in this same calculation. No second
    safety timer or competing writer is needed.
    """
    physical = grid_w + battery_charge_w + accounted_w - reserve_w
    old = {d.id: max(0, int(previous.get(d.id, 0))) for d in consumers}
    old_total = sum(old.values())
    allowed = physical

    if grid_w < 0:
        # Do not increase while importing. Larger deficits directly reduce
        # controlled load. Tiny deviations are tolerated, not amplified.
        permitted_from_grid = max(
            0.0, old_total + (grid_w if grid_w < -grid_deadband_w else 0.0)
        )
        allowed = min(allowed, permitted_from_grid)

    allowed = max(0.0, allowed)
    nominal = distribute(allowed, consumers)

    # A small measurement deviation may leave existing steps unchanged, but
    # NEVER override a new higher priority, removed demand or physical lock.
    if 0 <= old_total - allowed <= grid_deadband_w:
        structural = distribute(max(allowed, float(old_total)), consumers)
        if all(old[key] <= structural.targets[key] for key in old):
            return CyclePlan(physical, allowed, old, structural.group_records)

    return CyclePlan(physical, allowed, nominal.targets, nominal.group_records)
