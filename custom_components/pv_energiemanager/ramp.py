"""Output slew limiting for coarse-step devices in the normal EMS cycle.

Leave high-resolution and switched outputs unchanged; the rate limit applies
only to upward movements on controllable devices with coarse native steps.
Downward adjustments, priority eviction and explicit pauses remain immediate.
"""
from __future__ import annotations

from .engine import Consumer

# Two native steps per normal (15-s by default) EMS cycle. This caps a
# three-phase 230-V EVSE with 1-A steps to +1,380 W per consumer per cycle.
# This is a technology-neutral threshold in watts, not an EVSE assumption.
COARSE_STEP_THRESHOLD_W = 300
MAX_UP_STEPS_PER_CYCLE = 2


def limit_increases(
    targets: dict[str, int],
    devices: list[Consumer],
    previous: dict[str, int],
    *,
    coarse_threshold_w: int = COARSE_STEP_THRESHOLD_W,
    max_steps: int = MAX_UP_STEPS_PER_CYCLE,
) -> dict[str, int]:
    """Restrict increases without ever adding power beyond the planned target.

    A device that is off may start at its configured minimum (if allowed by
    the distributor). Subsequent steps can be rate-limited. Never obstruct
    decreases or stops; those are the main safety response to a PV drop.
    """
    if max_steps < 1:
        raise ValueError("max_steps must be positive")
    limited = dict(targets)
    for device in devices:
        ident = device.id
        target = targets[ident]
        old = max(0, int(previous.get(ident, 0)))
        if (device.kind != "continuous" or device.step_w < coarse_threshold_w
                or target <= old):
            continue
        if old == 0:
            # Start is all-or-nothing at minimum for e.g. an EVSE.
            limited[ident] = min(target, device.minimum)
        else:
            limited[ident] = min(target, old + max_steps * device.step_w)
    return limited
