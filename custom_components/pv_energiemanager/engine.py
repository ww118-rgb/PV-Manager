"""Pure calculation core of PV Energiemanager (no Home Assistant dependencies)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Consumer:
    id: str
    priority: int
    subpriority: int
    kind: str
    minimum: int
    maximum: int
    steps: tuple[int, ...] = ()
    requested: bool = True
    allowed_to_start: bool = True
    locked_on: bool = False
    old_target: int = 0
    actual: float | None = None
    feedback_settled: bool = False

    @property
    def levels(self) -> tuple[int, ...]:
        if self.kind == "onoff":
            return (0, self.maximum)
        if self.kind == "stepped":
            return (0, *tuple(sorted(set(x for x in self.steps if x > 0))))
        return (0, self.minimum, self.maximum)


@dataclass
class Distribution:
    targets: dict[str, int]
    group_records: list[dict]
    unallocated: float


def _min_on(device: Consumer) -> int:
    if device.kind == "continuous":
        return device.minimum
    return min((x for x in device.levels if x > 0), default=device.maximum)


def _next_increase(device: Consumer, current: int, quantum: int) -> int | None:
    if device.kind == "continuous":
        if current >= device.maximum:
            return None
        return min(quantum, device.maximum - current)
    next_levels = [x for x in device.levels if x > current]
    return min(next_levels) - current if next_levels else None


def _allocate_group(
    devices: list[Consumer], budget: float, quantum: int
) -> dict[str, int]:
    """Admit by subpriority, then distribute as evenly as valid stages allow."""
    result = {d.id: 0 for d in devices}
    remaining = max(0.0, budget)
    active: list[Consumer] = []

    # Fixed minimum runtimes must be respected first. Their budget is still
    # accounted for; never create power from a forced runtime.
    for d in sorted(devices, key=lambda x: (x.subpriority, x.id)):
        if not d.locked_on:
            continue
        floor = _min_on(d)
        result[d.id] = floor
        remaining -= floor
        active.append(d)

    if remaining < -0.01:
        return result  # Controller will flag a power deficit.

    for d in sorted(devices, key=lambda x: (x.subpriority, x.id)):
        if d.locked_on or not d.requested or not d.allowed_to_start:
            continue
        min_on = _min_on(d)
        if remaining + 0.01 >= min_on:
            result[d.id] = min_on
            remaining -= min_on
            active.append(d)

    # A small, deterministic power quantum provides reasonably balanced
    # allocation while respecting stepped and fixed on/off loads.
    # A discrete step is only taken when its whole size fits.
    while remaining >= 0.5 and active:
        candidates: list[tuple[int, int, str, Consumer, int]] = []
        for d in active:
            inc = _next_increase(d, result[d.id], quantum)
            if inc is not None and inc <= remaining + 0.01:
                candidates.append((result[d.id], d.subpriority, d.id, d, inc))
        if not candidates:
            break
        _, _, _, selected, increase = min(candidates, key=lambda x: x[:3])
        result[selected.id] += increase
        remaining -= increase

    return result


def distribute(
    budget: float, devices: list[Consumer], quantum: int = 100
) -> Distribution:
    """Distribute a virtual power budget through priorities 1..10.

    Higher groups get first opportunity. When a group is not fully supplied,
    unallocated fractional power stays held unless confirmed feedback proves
    that an unchanged setpoint is only partly consumed.
    """
    if quantum < 1:
        raise ValueError("quantum must be >= 1 W")

    targets = {d.id: 0 for d in devices}
    records: list[dict] = []
    remainder = max(0.0, budget)

    for group_id in range(1, 11):
        group = [d for d in devices if d.priority == group_id]
        if not group:
            continue
        demand = sum(d.maximum for d in group if d.locked_on or
                     (d.requested and (d.allowed_to_start or d.old_target > 0)))
        if demand <= 0:
            records.append({"priority": group_id, "demand": 0, "setpoint": 0,
                            "passed": round(remainder, 1), "measured_unused": 0})
            continue
        nominal_budget = min(remainder, demand)
        allocated = _allocate_group(group, nominal_budget, quantum)
        used = sum(allocated.values())
        targets.update(allocated)

        unused_measured = 0.0
        for d in group:
            # Only use measured underconsumption if target has not changed.
            # All measurements and reserves must refer to this same cycle.
            if (d.actual is not None and d.feedback_settled
                    and allocated[d.id] == d.old_target
                    and allocated[d.id] > 0):
                unused_measured += max(0.0, allocated[d.id] - d.actual)

        # Group not fully provided: hold unallocatable remainder instead of
        # allowing a lower priority to bypass the group's configured max.
        # Confirmed underuse may pass to lower groups as a revocable loan.
        normal_rest = max(0.0, remainder - demand)
        remainder = max(0.0, normal_rest + unused_measured)
        records.append({"priority": group_id, "demand": demand,
                        "setpoint": used, "passed": round(remainder, 1),
                        "measured_unused": round(unused_measured, 1)})

    return Distribution(targets, records, max(0.0, budget - sum(targets.values())))
