"""A small budget hysteresis for cyclic PV surplus control.

Never relax demand/priority restrictions: holding previous outputs is only
allowed when the priority allocator considers them valid at the old budget.
Hardware emergency reductions bypass both the deadband and confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass

from .engine import Consumer, distribute


# Conservative initial defaults for the 15-second controller. No device
# protocol, address or charging-current assumption is baked into this module.
UP_RESERVE_W = 100
DOWN_TOLERANCE_W = 150
DOWN_CONFIRM_CYCLES = 2
URGENT_SHORTFALL_W = 1000


@dataclass(frozen=True)
class Decision:
    targets: dict[str, int]
    shortage_cycles: int
    reason: str


def stabilize(
    budget: float,
    consumers: list[Consumer],
    previous: dict[str, int],
    shortage_cycles: int,
    *,
    up_reserve_w: float = UP_RESERVE_W,
    down_tolerance_w: float = DOWN_TOLERANCE_W,
    confirmation_cycles: int = DOWN_CONFIRM_CYCLES,
    urgent_shortfall_w: float = URGENT_SHORTFALL_W,
) -> Decision:
    """Select physically reachable targets without reacting to every 1-W dip.

    A small shortage may be accepted without making a 690-W ampere step.
    A moderate shortage requires consecutive cycle confirmation; a large
    shortage or changing demand/priority is acted on immediately.
    Increases need additional headroom and cannot exceed the nominal plan.
    """
    nominal = distribute(budget, consumers).targets
    old = {d.id: max(0, int(previous.get(d.id, 0))) for d in consumers}
    old_total = sum(old.values())
    gap = max(0.0, old_total - budget)
    needs_reduction = any(nominal[k] < old[k] for k in old)

    if (needs_reduction and gap > 0 and gap < urgent_shortfall_w):
        # Do not hold outdated targets if higher priorities, demand, hardware
        # lockouts or a changed set of consumers requires a redistribution.
        reference = distribute(max(budget, float(old_total)), consumers).targets
        structurally_valid = all(old[k] <= reference[k] for k in old)
        if structurally_valid:
            if gap <= down_tolerance_w:
                return Decision(old, 0, "Toleranzbereich")
            if shortage_cycles + 1 < max(1, confirmation_cycles):
                return Decision(old, shortage_cycles + 1, "Defizit bestätigen")

    # An extra buffer must be available before increasing a discrete level.
    # Allow any required downward adjustment immediately, even if an upward
    # allocation elsewhere is temporarily deferred.
    conservative = distribute(max(0.0, budget - up_reserve_w), consumers).targets
    targets = {}
    for ident, planned in nominal.items():
        current = old[ident]
        targets[ident] = (
            min(planned, max(current, conservative[ident]))
            if planned > current else planned
        )
    return Decision(targets, 0, "Verteilen")
