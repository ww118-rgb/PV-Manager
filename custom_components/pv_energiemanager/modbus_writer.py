"""Generic configuration-to-register encoder, independent of HA or device brand.

A zero command from the EMS is a *semantic* pause/stop. The caller must have
explicitly configured which register value represents that action. Never infer
that sending a raw zero is safe.
"""
from __future__ import annotations

import math
import struct

from .modbus_codec import TYPE_WIDTH, WORD_ORDER


class CommandValueError(ValueError):
    """Unsafe, out-of-range or unrepresentable outbound command."""


def register_words(value: float, *, data_type: str, byte_order: str = "ABCD",
                   scale: float = 1.0, offset: float = 0.0) -> list[int]:
    """Encode physical device units using physical = register*scale + offset."""
    if data_type not in TYPE_WIDTH:
        raise CommandValueError("Nicht unterstützter Schreibdatentyp")
    if not all(math.isfinite(float(x)) for x in (value, scale, offset)) or scale == 0:
        raise CommandValueError("Ungültiger Wert oder Skalierung")
    raw = (float(value) - offset) / scale
    if not math.isfinite(raw):
        raise CommandValueError("Registerwert ist nicht endlich")
    if data_type != "float32":
        nearest = round(raw)
        if abs(raw - nearest) > 1e-7:
            raise CommandValueError("Ganzzahlregister kann den Wert nicht exakt abbilden")
        raw = int(nearest)
        bounds = {
            "uint16": (0, 65535), "int16": (-32768, 32767),
            "uint32": (0, 4294967295), "int32": (-2147483648, 2147483647),
        }[data_type]
        if not bounds[0] <= raw <= bounds[1]:
            raise CommandValueError("Registerwert außerhalb des Datentyps")
    fmt = {"uint16": ">H", "int16": ">h", "uint32": ">I",
           "int32": ">i", "float32": ">f"}[data_type]
    try:
        packed = struct.pack(fmt, raw)
    except (OverflowError, ValueError, struct.error) as exc:
        raise CommandValueError("Wert nicht in Register darstellbar") from exc
    if len(packed) == 4:
        if byte_order not in WORD_ORDER:
            raise CommandValueError("Ungültige Byte-/Wortreihenfolge")
        packed = bytes(dict(zip("ABCD", packed))[letter] for letter in byte_order)
    elif byte_order in ("BADC", "BA"):
        packed = packed[::-1]
    elif byte_order not in ("ABCD", "AB"):
        raise CommandValueError("Ungültige 16-Bit-Bytefolge")
    return [int.from_bytes(packed[i:i+2], "big") for i in range(0, len(packed), 2)]


def command_for_setpoint(request: float, cfg: dict) -> tuple[float, list[int]]:
    """Map a HA requested unit value to a device command.

    request=0 means STOP; raw command is the configured `off_value`, even if
    a device uses 0 for unlimited output. A positive request must be within
    the configured active range and aligned to step.
    """
    if not math.isfinite(request):
        raise CommandValueError("Nicht endlicher Sollwert")
    if request == 0:
        if cfg.get("off_value") is None:
            raise CommandValueError("Kein sicherer Pause-/Aus-Wert konfiguriert")
        physical = float(cfg["off_value"])
    else:
        lo, hi, step = (float(cfg[k]) for k in ("active_min", "active_max", "step"))
        if request < lo - 1e-7 or request > hi + 1e-7:
            raise CommandValueError(f"Aktive Vorgabe außerhalb {lo:g}–{hi:g}")
        steps = (request - lo) / step
        if abs(steps - round(steps)) > 1e-6:
            raise CommandValueError(f"Sollwert passt nicht auf Schrittweite {step:g}")
        physical = request
    words = register_words(
        physical, data_type=cfg["data_type"],
        byte_order=cfg.get("byte_order", "ABCD"),
        scale=float(cfg.get("scale", 1.0)), offset=float(cfg.get("offset", 0.0)),
    )
    return physical, words


def validate_write_point(data: dict, connection_ids: set[str]) -> tuple[dict, str | None]:
    """Validate output configuration. Never allow an implicit stop mapping."""
    try:
        d = dict(data)
        d["name"] = str(d["name"]).strip()
        d["connection_id"] = str(d["connection_id"])
        d["unit"] = str(d.get("unit") or "").strip()
        d["address"] = int(d["address"])
        d["function_code"] = int(d["function_code"])
        d["active_min"] = float(d["active_min"])
        d["active_max"] = float(d["active_max"])
        d["step"] = float(d["step"])
        d["off_value"] = float(d["off_value"])
        d["scale"] = float(d.get("scale", 1.0))
        d["offset"] = float(d.get("offset", 0.0))
        width = TYPE_WIDTH.get(d["data_type"])
        if (d["connection_id"] not in connection_ids or not d["name"]
                or len(d["name"]) > 128 or len(d["unit"]) > 32):
            return {}, "invalid_endpoint"
        if (width is None or d["address"] < 0 or d["address"] + width > 65536
                or d["function_code"] not in (6, 16)
                or (d["function_code"] == 6 and width != 1)):
            return {}, "invalid_register"
        vals = (d["active_min"], d["active_max"], d["step"],
                d["off_value"], d["scale"], d["offset"])
        if not all(math.isfinite(v) for v in vals) or d["scale"] == 0:
            return {}, "invalid_scale"
        if (d["active_min"] <= 0 or d["active_max"] < d["active_min"]
                or d["step"] <= 0 or d["step"] > d["active_max"]):
            return {}, "invalid_limits"
        # Reject registration if the configured physical min/max or pause
        # command is not encodable. Off value need not be in the active range.
        for v in (d["active_min"], d["active_max"], d["off_value"]):
            register_words(v, data_type=d["data_type"],
                           byte_order=d.get("byte_order", "ABCD"),
                           scale=d["scale"], offset=d["offset"])
        return d, None
    except (TypeError, ValueError, KeyError, OverflowError, CommandValueError):
        return {}, "invalid_write_command"
