"""Pure UI wizard helpers. No device addresses or protocol-specific defaults."""
from __future__ import annotations

import math

VALID_UNITS = ("W", "kW", "A")


def merge_consumer(old: dict, basics: dict, output: dict, feedback: dict, conversion: dict | None = None) -> dict:
    """Combine wizard steps without discarding advanced settings or stable IDs."""
    merged = {
        "priority": 2, "subpriority": 1, "kind": "continuous",
        "min_w": 1400, "max_w": 11000, "steps_w": "500,1000,1500,2000",
        "output_unit": "W", "phases": 1, "voltage": 230,
        "start_delay_s": 0, "min_on_s": 0, "min_off_s": 0,
    }
    merged.update(old)
    merged.update(basics)
    for field in ("power_output", "switch_output"):
        merged.pop(field, None)
    merged.update({k: v for k, v in output.items() if k != "connection_type" and v})
    merged["output_unit"] = output.get("output_unit", "W")
    if conversion:
        merged.update(conversion)
    for field in ("actual_entity", "demand_entity"):
        merged.pop(field, None)
    merged.update({k: v for k, v in feedback.items() if v})
    return merged


def check_consumer_setup(config: dict, *, output_state=None, actual_state=None) -> list[str]:
    """Return user-actionable setup warnings, not fictitious measured values."""
    warnings = []
    is_switch = config.get("kind") == "onoff"
    entity = config.get("switch_output" if is_switch else "power_output")
    if not entity:
        warnings.append("Kein passender Schaltausgang bzw. Sollwertaktor ausgewählt.")
    elif output_state is None:
        warnings.append("Der ausgewählte Ausgang ist in Home Assistant noch nicht vorhanden.")
    elif output_state == "unavailable":
        warnings.append("Der ausgewählte Ausgang ist momentan nicht verfügbar.")
    elif output_state == "unknown":
        warnings.append("Der Ausgang hat noch keinen bestätigten Sollwert. Modbus-Schreibaktoren starten so nach einem Neustart.")
    if not config.get("actual_entity"):
        warnings.append("Kein Istleistungssensor zugeordnet. Die tatsächliche Leistungsaufnahme bleibt unbekannt.")
    elif actual_state in (None, "unknown", "unavailable"):
        warnings.append("Der zugeordnete Istleistungssensor liefert noch keinen gültigen Wert.")
    if not config.get("demand_entity"):
        warnings.append("Keine Anforderungsquelle: Der Verbraucher gilt immer als anfordernd.")
    if config.get("output_unit") == "A":
        try:
            volts = float(config["voltage"])
            phases = int(config["phases"])
            if volts <= 0 or phases not in (1, 3):
                warnings.append("Phasenanzahl oder Spannung für die Ampere-Umrechnung ist ungültig.")
        except (KeyError, ValueError, TypeError):
            warnings.append("Angaben zur Ampere-Umrechnung fehlen.")
    return warnings


def source_power_w(state) -> float | None:
    """Read and normalize HA power for UI preview only; ignore non-power units."""
    if state is None or getattr(state, "state", None) in ("unknown", "unavailable", None):
        return None
    try:
        value = float(state.state)
        unit = str(state.attributes.get("unit_of_measurement", "W")).strip().lower()
        factor = {"w": 1, "": 1, "kw": 1_000, "mw": 1_000_000}.get(unit)
        if factor is None or not math.isfinite(value):
            return None
        return value * factor
    except (TypeError, ValueError, AttributeError):
        return None


def signed_grid_preview(value_w: float | None, export_positive: bool) -> str:
    if value_w is None:
        return "Noch kein gültiger Netzleistungswert (Einheit muss W/kW/MW sein)."
    balance = value_w if export_positive else -value_w
    if balance >= 0:
        return f"Einspeisung: {balance:,.0f} W".replace(",", ".")
    return f"Netzbezug: {abs(balance):,.0f} W".replace(",", ".")


def actuator_compatibility_error(cfg: dict, state) -> str | None:
    """Reject provably unsafe/wrong entity bindings before saving a consumer.

    Unknown is accepted only for own write-only Modbus numbers that have never
    been commanded. Runtime independently checks ownership before writing.
    """
    is_switch = cfg.get("kind") == "onoff"
    if state is None:
        return "missing_actuator"
    status = state.state
    if status == "unavailable":
        return "unavailable_actuator"
    if status == "unknown" and not (
        not is_switch and state.attributes.get("feedback_status") == "unknown_after_start"
        and state.attributes.get("off_value_configured") is True
        and state.attributes.get("last_write_error") is None
    ):
        return "unavailable_actuator"
    if is_switch:
        return None
    unit = cfg.get("output_unit", "W")
    actual_unit = str(state.attributes.get("unit_of_measurement") or "").strip()
    if actual_unit in VALID_UNITS and actual_unit != unit:
        return "actuator_unit_mismatch"
    if unit not in VALID_UNITS:
        return "actuator_unit_mismatch"
    try:
        factor = 1 if unit == "W" else (1000 if unit == "kW"
                    else float(cfg["voltage"]) * int(cfg["phases"]))
        if factor <= 0:
            return "actuator_limits_mismatch"
        maximum = state.attributes.get("max")
        minimum = state.attributes.get("min")
        step = float(state.attributes.get("step", 0.01))
        lo = float(cfg["min_w"]) / factor
        hi = float(cfg["max_w"]) / factor
        if step <= 0:
            return "actuator_limits_mismatch"
        if minimum is not None and lo < float(minimum) - 1e-7:
            return "actuator_limits_mismatch"
        if maximum is not None and hi > float(maximum) + 1e-7:
            return "actuator_limits_mismatch"
        # A controller rounds *down* to avoid consuming more than budgeted.
        # If that makes the minimum impossible, changing just the minimum is required.
        if lo > 0:
            rounded = math.floor((lo + 1e-8) / step) * step
            if rounded * factor < float(cfg["min_w"]) - 10:
                return "actuator_step_mismatch"
    except (KeyError, ValueError, TypeError, OverflowError):
        return "actuator_limits_mismatch"
    return None
