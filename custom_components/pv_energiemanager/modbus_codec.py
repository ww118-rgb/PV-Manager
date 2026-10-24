"""Pure Modbus register decoding; no Home Assistant or network dependencies."""
from __future__ import annotations

import math
import struct

TYPE_WIDTH = {
    "uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2,
}
WORD_ORDER = ("ABCD", "BADC", "CDAB", "DCBA")


def decode_registers(registers: list[int], data_type: str, order: str = "ABCD",
                     scale: float = 1.0, offset: float = 0.0) -> float:
    """Convert Modbus register words to physical value.

    Received bytes are tagged in named order relative to canonical ABCD.
    For example, CDAB is a word-swapped 32-bit value.
    """
    if data_type not in TYPE_WIDTH:
        raise ValueError("Unbekannter Datentyp")
    width = TYPE_WIDTH[data_type]
    if len(registers) != width:
        raise ValueError("Falsche Registeranzahl")
    if any(not isinstance(v, int) or not 0 <= v <= 65535 for v in registers):
        raise ValueError("Ungültiger Modbus-Rohwert")
    if not math.isfinite(scale) or not math.isfinite(offset) or scale == 0:
        raise ValueError("Ungültige Skalierung")
    packed = b"".join(v.to_bytes(2, "big") for v in registers)
    if width == 2:
        if order not in WORD_ORDER:
            raise ValueError("Unbekannte Byte-/Wortreihenfolge")
        tagged = dict(zip(order, packed))
        packed = bytes(tagged[letter] for letter in "ABCD")
    elif order not in ("ABCD", "BADC", "AB", "BA"):
        raise ValueError("Ungültige Bytefolge für 16 Bit")
    elif order in ("BADC", "BA"):
        packed = packed[::-1]
    fmt = {"uint16": ">H", "int16": ">h",
           "uint32": ">I", "int32": ">i", "float32": ">f"}[data_type]
    raw = struct.unpack(fmt, packed)[0]
    result = raw * scale + offset
    if not math.isfinite(result):
        raise ValueError("Nicht endlicher Messwert")
    return result
