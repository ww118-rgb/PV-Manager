"""Monitoring entities for budget, group allocation and consumers."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfPower
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .modbus_sensors import create_modbus_sensor_entities

GLOBAL = {
    "grid": ("Netzleistung", UnitOfPower.WATT),
    "battery": ("Batterieleistung", UnitOfPower.WATT),
    "pv": ("PV-Erzeugung", UnitOfPower.WATT),
    "budget": ("Verteilungsbudget", UnitOfPower.WATT),
    "allocation_budget": ("Für Steuerung freigegebenes Budget", UnitOfPower.WATT),
    "assigned": ("Zugewiesene Leistung", UnitOfPower.WATT),
    "unallocated": ("Nicht weitergereichte Leistung", UnitOfPower.WATT),
    "ramp_delayed": ("Wegen Anstiegsbegrenzung zurückgehalten", UnitOfPower.WATT),
    "safety_interventions": ("Netzbezug-Schutz Eingriffe", None),
    "safety_last_import": ("Netzbezug beim letzten Schutz-Eingriff", UnitOfPower.WATT),
    "safety_curtailment": ("Letzte Sicherheitsreduzierung", UnitOfPower.WATT),
    "deficit": ("Leistungsdefizit", UnitOfPower.WATT),
    "status": ("Regelstatus", None),
    "cycle_count": ("Regelzyklen", None),
    "error": ("Letzter Fehler", None),
}


async def async_setup_entry(hass, entry, async_add_entities):
    manager = entry.runtime_data
    entities = [EMSSensor(manager, key) for key in GLOBAL]
    for d in manager.devices:
        entities.extend(ConsumerSensor(manager, d, field) for field in
                        ("target", "actual", "accounted", "demand"))
    entities.extend(create_modbus_sensor_entities(hass, entry))
    async_add_entities(entities)


class EMSBaseSensor(SensorEntity):
    _attr_should_poll = False

    def __init__(self, manager):
        self.manager = manager
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry.entry_id)},
            name="PV Energiemanager",
            manufacturer="Lokale Custom Integration",
            model="Zyklischer Leistungsverteiler",
        )

    async def async_added_to_hass(self):
        self.async_on_remove(self.manager.subscribe(self.async_write_ha_state))


class EMSSensor(EMSBaseSensor):
    def __init__(self, manager, key):
        super().__init__(manager)
        self.key = key
        self._attr_unique_id = f"{manager.entry.entry_id}_{key}"
        self._attr_name = GLOBAL[key][0]
        self._attr_native_unit_of_measurement = GLOBAL[key][1]
        if GLOBAL[key][1] is not None:
            self._attr_suggested_display_precision = 0

    @property
    def native_value(self):
        if self.key == "status":
            return self.manager.status
        if self.key == "cycle_count":
            return self.manager.cycle_count
        if self.key == "error":
            return self.manager.error or "Kein Fehler"
        return self.manager.values.get(self.key)

    @property
    def extra_state_attributes(self):
        if self.key == "budget":
            return {"groups": self.manager.group_records}
        return None


class ConsumerSensor(EMSBaseSensor):
    FIELDS = {"target": "Sollleistung", "actual": "Istleistung",
              "accounted": "Angerechnete Leistung", "demand": "Leistungsanforderung"}

    def __init__(self, manager, device, field):
        super().__init__(manager)
        self.device = device
        self.field = field
        self._attr_unique_id = f"{manager.entry.entry_id}_{device['id']}_{field}"
        self._attr_name = f"{device['name']} {self.FIELDS[field]}"
        if field != "demand":
            self._attr_native_unit_of_measurement = UnitOfPower.WATT
            self._attr_suggested_display_precision = 0

    @property
    def native_value(self):
        value = self.manager.per_device[self.device["id"]][self.field]
        if self.field == "demand":
            return "Ja" if value else "Nein"
        return value

    @property
    def extra_state_attributes(self):
        if self.field == "target":
            return {"priority": self.device["priority"],
                    "subpriority": self.device["subpriority"],
                    "regulation": self.device["kind"]}
        return None
