"""Pure safety check for actuator states during EMS cycles.

HA write-only number entities have state 'unknown' until their first command.
This is not the same as 'unavailable'. Allow initial control only for an
explicitly configured, registered PV-Manager Modbus write entity with a safe
pause mapping. Other unknown/unavailable actuators always block commands.
"""
from __future__ import annotations


def actuator_can_receive_command(
    entity_id: str,
    state,
    *,
    registry_entry=None,
    entry_id: str,
    write_points: list[dict],
    domain: str = "pv_energiemanager",
) -> bool:
    """Evaluate readiness; no network calls and no implicit device commands."""
    if state is None:
        return False
    current = getattr(state, "state", None)
    if current == "unavailable":
        return False
    if current != "unknown":
        return current not in (None, "none", "")

    # This is the only exception to the unknown-state guard: own write-only
    # native number entity before its first command, not another HA number.
    if not entity_id.startswith("number.") or registry_entry is None:
        return False
    if getattr(registry_entry, "domain", None) != "number":
        return False
    if getattr(registry_entry, "platform", None) != domain:
        return False
    if getattr(registry_entry, "config_entry_id", None) != entry_id:
        return False
    valid_unique_ids = {
        f"{entry_id}_mb_write_{cfg['id']}"
        for cfg in write_points
        if cfg.get("id") and cfg.get("off_value") is not None
    }
    if getattr(registry_entry, "unique_id", None) not in valid_unique_ids:
        return False
    attrs = getattr(state, "attributes", {}) or {}
    return (
        attrs.get("off_value_configured") is True
        and attrs.get("feedback_status") == "unknown_after_start"
        and attrs.get("last_write_error") is None
    )
