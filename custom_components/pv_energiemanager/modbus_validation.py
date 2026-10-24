"""Protocol-neutral-ish validation for user-defined Modbus read points.

The simulator is intentionally not mentioned here: every device definition is
user data.  These checks run before an entry can be persisted and are covered
by tests without Home Assistant or a live Modbus endpoint.
"""
from __future__ import annotations

import math

from .modbus_codec import TYPE_WIDTH, WORD_ORDER


def validate_connection(value: dict) -> tuple[dict, str | None]:
    """Normalize one TCP endpoint. Return (normalized_config, error_code)."""
    try:
        c = dict(value)
        c["name"] = str(c["name"]).strip()
        c["host"] = str(c["host"]).strip()
        c["port"] = int(c["port"])
        c["unit_id"] = int(c["unit_id"])
        if not c["name"] or not c["host"] or len(c["host"]) > 255:
            return c, "invalid_endpoint"
        if not 1 <= c["port"] <= 65535 or not 0 <= c["unit_id"] <= 255:
            return c, "invalid_endpoint"
        if any(char.isspace() for char in c["host"]):
            return c, "invalid_endpoint"
        return c, None
    except (ValueError, TypeError, KeyError, OverflowError):
        return {}, "invalid_endpoint"


def validate_read_point(value: dict, known_connection_ids: set[str]) -> tuple[dict, str | None]:
    """Normalize one sensor definition and check the register boundary."""
    try:
        d = dict(value)
        d["name"] = str(d["name"]).strip()
        d["connection_id"] = str(d["connection_id"])
        d["address"] = int(d["address"])
        d["function_code"] = int(d["function_code"])
        d["poll_seconds"] = int(d["poll_seconds"])
        d["scale"] = float(d["scale"])
        d["offset"] = float(d["offset"])
        d["unit"] = str(d.get("unit") or "").strip()
        if d["connection_id"] not in known_connection_ids:
            return d, "invalid_endpoint"
        if not d["name"] or len(d["name"]) > 128:
            return d, "invalid_register"
        width = TYPE_WIDTH.get(d["data_type"])
        if width is None or d["function_code"] not in (3, 4):
            return d, "invalid_register"
        if d["address"] < 0 or d["address"] + width > 65536:
            return d, "invalid_register"
        if not 5 <= d["poll_seconds"] <= 3600:
            return d, "invalid_register"
        if d["byte_order"] not in WORD_ORDER:
            return d, "invalid_register"
        # ABCD: high byte first; BADC: low byte first on 16-bit values.
        if width == 1 and d["byte_order"] not in ("ABCD", "BADC"):
            return d, "invalid_register"
        if not math.isfinite(d["scale"]) or d["scale"] == 0:
            return d, "invalid_scale"
        if not math.isfinite(d["offset"]):
            return d, "invalid_scale"
        if len(d["unit"]) > 32:
            return d, "invalid_register"
        return d, None
    except (ValueError, TypeError, KeyError, OverflowError):
        return {}, "invalid_register"
