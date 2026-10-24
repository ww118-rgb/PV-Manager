"""Read-only native HA sensor entities backed by shared Modbus connections."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging

from homeassistant.components.modbus import async_get_unit
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from modbus_connection import ModbusTcpParams

from .const import DOMAIN
from .modbus_codec import TYPE_WIDTH, decode_registers

_LOGGER = logging.getLogger(__name__)


def create_modbus_sensor_entities(hass, entry):
    """Bind each configured register to the HA core shared Modbus transport.

    async_get_unit is intentionally called only at config-entry setup, never
    from a pure calculation routine or by building a second socket manager.
    """
    connections = {c["id"]: c for c in entry.options.get("modbus_connections", [])}
    units = {}
    entities = []
    for cfg in entry.options.get("modbus_registers", []):
        conn = connections.get(cfg["connection_id"])
        if conn is None:
            _LOGGER.warning("Modbus-Datenpunkt %s ohne gültige Verbindung", cfg.get("name"))
            continue
        ident = (conn["host"].lower(), conn["port"], conn["unit_id"])
        if ident not in units:
            units[ident] = async_get_unit(
                hass, entry,
                ModbusTcpParams(host=conn["host"], port=int(conn["port"])),
                int(conn["unit_id"]),
            )
        entities.append(PVModbusReadSensor(hass, entry, conn, cfg, units[ident]))
    return entities


class PVModbusReadSensor(SensorEntity):
    """Poll one configured Modbus register at a per-datapoint interval."""

    _attr_should_poll = False

    def __init__(self, hass, entry, connection, cfg, unit):
        self.hass = hass
        self.cfg = cfg
        self.unit = unit
        self._attr_unique_id = f"{entry.entry_id}_mb_{cfg['id']}"
        self._attr_name = cfg["name"]
        self._attr_native_unit_of_measurement = cfg.get("unit") or None
        self._attr_suggested_display_precision = 2
        self._attr_native_value = None
        self._attr_available = False
        self._raw_registers = None
        self._last_success = None
        self._last_attempt = None
        self._read_attempts = 0
        self._successful_reads = 0
        self._last_error = None
        self._poll_lock = asyncio.Lock()
        self._removed = False
        self._pending_tasks = set()
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"modbus_{entry.entry_id}_{connection['id']}")},
            name=connection["name"],
            manufacturer="PV Energiemanager",
            model="Modbus TCP Datenpunkte",
        )

    @property
    def extra_state_attributes(self):
        return {
            "function_code": self.cfg["function_code"],
            "register_address_zero_based": self.cfg["address"],
            "raw_registers": self._raw_registers,
            "data_type": self.cfg["data_type"],
            "byte_order": self.cfg.get("byte_order", "ABCD"),
            "last_success": self._last_success,
            "last_attempt": self._last_attempt,
            "read_attempts": self._read_attempts,
            "successful_reads": self._successful_reads,
            "last_error": self._last_error,
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_interval(
            self.hass, self._schedule_refresh,
            timedelta(seconds=int(self.cfg["poll_seconds"])),
        ))
        # Do not block entity setup or the HA start on unreachable TCP endpoints.
        self.async_on_remove(self._cancel_tasks)
        self._schedule_refresh(None)

    async def async_will_remove_from_hass(self):
        self._removed = True
        await super().async_will_remove_from_hass()

    def _cancel_tasks(self):
        for task in self._pending_tasks:
            task.cancel()
        self._pending_tasks.clear()

    def _schedule_refresh(self, _now):
        if self._removed or self._poll_lock.locked():
            return
        task = self.hass.async_create_task(self._refresh())
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _refresh(self):
        if self._poll_lock.locked():
            return
        async with self._poll_lock:
            self._read_attempts += 1
            self._last_attempt = datetime.now(timezone.utc).isoformat()
            try:
                address = int(self.cfg["address"])
                count = TYPE_WIDTH[self.cfg["data_type"]]
                # Bound stalled reads so the next polling interval can retry.
                async with asyncio.timeout(10):
                    if int(self.cfg["function_code"]) == 3:
                        raw = await self.unit.read_holding_registers(address, count)
                    else:
                        raw = await self.unit.read_input_registers(address, count)
                value = decode_registers(
                    list(raw),
                    self.cfg["data_type"],
                    self.cfg.get("byte_order", "ABCD"),
                    float(self.cfg["scale"]),
                    float(self.cfg["offset"]),
                )
                self._raw_registers = list(raw)
                self._attr_native_value = value
                self._attr_available = True
                self._successful_reads += 1
                self._last_success = datetime.now(timezone.utc).isoformat()
                self._last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._attr_available = False
                new_error = f"{type(exc).__name__}: {exc}"
                if new_error != self._last_error:
                    _LOGGER.warning(
                        "Modbus-Datenpunkt %s nicht verfügbar: %s",
                        self.cfg["name"], new_error,
                    )
                self._last_error = new_error
            if not self._removed:
                self.async_write_ha_state()
