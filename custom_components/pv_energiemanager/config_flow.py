"""UI onboarding and consumer management for PV Energiemanager."""
from __future__ import annotations

from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import section
from homeassistant.core import callback
from homeassistant.helpers import selector

from .modbus_codec import TYPE_WIDTH, WORD_ORDER, decode_registers
from .modbus_validation import validate_connection, validate_read_point
from .modbus_writer import validate_write_point
from .setup_wizard import check_consumer_setup, source_power_w, signed_grid_preview, actuator_compatibility_error, suggested_minimum_power

from .const import (
    DEFAULT_INTERVAL, DEFAULT_RESERVE, DEFAULT_SETTLE,
    DOMAIN, TYPE_CONTINUOUS, TYPE_ONOFF, TYPE_STEPPED, TYPES,
)


def _entity(domains: list[str]):
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domains))


def _num(lo: int, hi: int, step: int = 1):
    return selector.NumberSelector(selector.NumberSelectorConfig(min=lo, max=hi, step=step, mode="box"))


def _initial_setup_schema():
    """Allow adding the hub before any locally created Modbus sensor exists.

    Existing HA grid sensors may be selected on first install, but this
    integration cannot create its native Modbus sensors before the hub exists.
    """
    return vol.Schema({
        vol.Optional("grid_entity"):
            _entity(["sensor", "number", "input_number"]),
    })


def _global_schema(settings: dict):
    return vol.Schema({
        vol.Required("grid_entity", default=settings.get("grid_entity", "")):
            _entity(["sensor", "number", "input_number"]),
        vol.Optional("battery_entity", description={"suggested_value": settings.get("battery_entity")})
            if settings.get("battery_entity") else vol.Optional("battery_entity"):
            _entity(["sensor", "number", "input_number"]),
        vol.Optional("pv_entity", description={"suggested_value": settings.get("pv_entity")})
            if settings.get("pv_entity") else vol.Optional("pv_entity"):
            _entity(["sensor", "number", "input_number"]),
        vol.Required("grid_export_positive", default=settings.get("grid_export_positive", True)):
            selector.BooleanSelector(),
        vol.Required("battery_charge_positive", default=settings.get("battery_charge_positive", True)):
            selector.BooleanSelector(),
        vol.Required("interval_s", default=settings.get("interval_s", DEFAULT_INTERVAL)):
            _num(5, 300),
        vol.Required("reserve_w", default=settings.get("reserve_w", DEFAULT_RESERVE)):
            _num(0, 10000, 10),
        vol.Required("feedback_settle_s", default=settings.get("feedback_settle_s", DEFAULT_SETTLE)):
            _num(0, 180),
    })


def _device_schema(values: dict | None = None):
    d = values or {}
    schema = {
        vol.Required("name", default=d.get("name", "Neuer Verbraucher")):
            selector.TextSelector(),
        vol.Required("priority", default=d.get("priority", 2)):
            _num(1, 10),
        vol.Required("subpriority", default=d.get("subpriority", 1)):
            _num(1, 99),
        vol.Required("kind", default=d.get("kind", TYPE_CONTINUOUS)):
            selector.SelectSelector(selector.SelectSelectorConfig(
                options=TYPES, mode="dropdown")),
        vol.Required("min_w", default=d.get("min_w", 1400)):
            _num(0, 100000, 10),
        vol.Required("max_w", default=d.get("max_w", 11000)):
            _num(1, 100000, 10),
        vol.Optional("steps_w", default=d.get("steps_w", "500,1000,1500,2000")):
            selector.TextSelector(),
        vol.Optional("demand_entity", description={"suggested_value": d.get("demand_entity")})
            if d.get("demand_entity") else vol.Optional("demand_entity"):
            _entity(["binary_sensor", "switch", "input_boolean"]),
        vol.Optional("actual_entity", description={"suggested_value": d.get("actual_entity")})
            if d.get("actual_entity") else vol.Optional("actual_entity"):
            _entity(["sensor", "number", "input_number"]),
        vol.Optional("power_output", description={"suggested_value": d.get("power_output")})
            if d.get("power_output") else vol.Optional("power_output"):
            _entity(["number", "input_number"]),
        vol.Optional("switch_output", description={"suggested_value": d.get("switch_output")})
            if d.get("switch_output") else vol.Optional("switch_output"):
            _entity(["switch", "input_boolean"]),
        vol.Required("output_unit", default=d.get("output_unit", "W")):
            selector.SelectSelector(selector.SelectSelectorConfig(options=["W", "kW", "A"])),
        vol.Required("phases", default=str(d.get("phases", 1))):
            selector.SelectSelector(selector.SelectSelectorConfig(options=["1", "3"])),
        vol.Required("voltage", default=d.get("voltage", 230)):
            _num(100, 260),
        vol.Required("start_delay_s", default=d.get("start_delay_s", 0)):
            _num(0, 3600),
        vol.Required("min_on_s", default=d.get("min_on_s", 0)):
            _num(0, 86400),
        vol.Required("min_off_s", default=d.get("min_off_s", 0)):
            _num(0, 86400),
    }
    return vol.Schema(schema)


def _validate_device(d):
    result = dict(d)
    kind = result["kind"]
    low, high = int(result["min_w"]), int(result["max_w"])
    if high < low or (kind != TYPE_STEPPED and high < 1):
        return None, "limits"
    if kind == TYPE_ONOFF:
        if not result.get("switch_output"):
            return None, "missing_switch"
        result["min_w"] = high
    elif not result.get("power_output"):
        return None, "missing_power_output"
    if kind == TYPE_STEPPED:
        try:
            stages = sorted(set(int(x.strip()) for x in result.get("steps_w", "").split(",") if x.strip()))
        except ValueError:
            return None, "invalid_steps"
        if not stages or any(x <= 0 or x > high for x in stages):
            return None, "invalid_steps"
        result["min_w"] = stages[0]
        result["max_w"] = stages[-1]
    # UI selector returns numeric fields as floats; normalize once in config.
    for key in ("priority", "subpriority", "min_w", "max_w", "voltage",
                "start_delay_s", "min_on_s", "min_off_s"):
        result[key] = int(result[key])
    result["phases"] = int(result["phases"])
    return result, None


# Modbus configuration is stored in options; existing consumer and system
# settings retain their IDs and schema.
def _modbus_connection_schema(values=None):
    values = values or {}
    return vol.Schema({
        vol.Required("name", default=values.get("name", "")): selector.TextSelector(),
        vol.Required("host", default=values.get("host", "")): selector.TextSelector(),
        vol.Required("port", default=values.get("port", 502)): _num(1, 65535),
        vol.Required("unit_id", default=values.get("unit_id", 1)): _num(0, 255),
    })


def _modbus_register_schema(connections: list[dict], values=None):
    values = values or {}
    return vol.Schema({
        vol.Required("connection_id", default=values.get("connection_id", connections[0]["id"])): selector.SelectSelector(
            selector.SelectSelectorConfig(options=[
                selector.SelectOptionDict(value=c["id"], label=c["name"])
                for c in connections
            ])),
        vol.Required("name", default=values.get("name", "")): selector.TextSelector(),
        vol.Required("address", default=values.get("address", 0)): _num(0, 65535),
        vol.Required("function_code", default=str(values.get("function_code", 3))): selector.SelectSelector(
            selector.SelectSelectorConfig(options=["3", "4"])),
        vol.Required("data_type", default=values.get("data_type", "int16")): selector.SelectSelector(
            selector.SelectSelectorConfig(options=list(TYPE_WIDTH))),
        vol.Required("byte_order", default=values.get("byte_order", "ABCD")): selector.SelectSelector(
            selector.SelectSelectorConfig(options=list(WORD_ORDER))),
        vol.Required("scale", default=values.get("scale", 1.0)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=-1000000, max=1000000,
                                          step="any", mode="box")),
        vol.Required("offset", default=values.get("offset", 0.0)): selector.NumberSelector(
            selector.NumberSelectorConfig(min=-1000000, max=1000000,
                                          step="any", mode="box")),
        # Do not force W on unit-less numerical status sensors.
        vol.Optional("unit", description={"suggested_value": values.get("unit", "W")}):
            selector.TextSelector(),
        vol.Required("poll_seconds", default=values.get("poll_seconds", 15)): _num(5, 3600),
    })



def _modbus_write_schema(connections: list[dict], values=None):
    """Separate active demand from explicit STOP command mapping."""
    values = values or {}
    return vol.Schema({
        vol.Required("connection_id", default=values.get("connection_id", connections[0]["id"])):
            selector.SelectSelector(selector.SelectSelectorConfig(options=[
                selector.SelectOptionDict(value=c["id"], label=c["name"]) for c in connections
            ])),
        vol.Required("name", default=values.get("name", "")): selector.TextSelector(),
        vol.Required("address", default=values.get("address", 0)): _num(0, 65535),
        vol.Required("function_code", default=str(values.get("function_code", 16))):
            selector.SelectSelector(selector.SelectSelectorConfig(options=["6", "16"])),
        vol.Required("data_type", default=values.get("data_type", "float32")):
            selector.SelectSelector(selector.SelectSelectorConfig(options=list(TYPE_WIDTH))),
        vol.Required("byte_order", default=values.get("byte_order", "ABCD")):
            selector.SelectSelector(selector.SelectSelectorConfig(options=list(WORD_ORDER))),
        vol.Required("unit", default=values.get("unit", "A")): selector.TextSelector(),
        vol.Required("active_min", default=values.get("active_min", 6)):
            selector.NumberSelector(selector.NumberSelectorConfig(min=0.001, max=1000000, step="any", mode="box")),
        vol.Required("active_max", default=values.get("active_max", 16)):
            selector.NumberSelector(selector.NumberSelectorConfig(min=0.001, max=1000000, step="any", mode="box")),
        vol.Required("step", default=values.get("step", 1)):
            selector.NumberSelector(selector.NumberSelectorConfig(min=0.001, max=1000000, step="any", mode="box")),
        # Must be typed explicitly. 0 is unsafe on devices where it means unlimited.
        vol.Required("off_value", description={"suggested_value": values.get("off_value")}):
            selector.NumberSelector(selector.NumberSelectorConfig(min=-1000000, max=1000000, step="any", mode="box")),
        vol.Optional("scale", default=values.get("scale", 1)):
            selector.NumberSelector(selector.NumberSelectorConfig(min=-1000000, max=1000000, step="any", mode="box")),
        vol.Optional("offset", default=values.get("offset", 0)):
            selector.NumberSelector(selector.NumberSelectorConfig(min=-1000000, max=1000000, step="any", mode="box")),
    })

class PVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create a single local EMS instance."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            # Create the hub before configuring native Modbus sensor sources.
            # Without a valid grid input the EMS stays paused/inhibited.
            entry_data = {
                "grid_export_positive": True,
                "battery_charge_positive": True,
                "interval_s": DEFAULT_INTERVAL,
                "reserve_w": DEFAULT_RESERVE,
                "feedback_settle_s": DEFAULT_SETTLE,
            }
            if user_input.get("grid_entity"):
                entry_data["grid_entity"] = user_input["grid_entity"]
            return self.async_create_entry(title="PV Energiemanager", data=entry_data)
        return self.async_show_form(step_id="user", data_schema=_initial_setup_schema())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PVOptionsFlow()


class PVOptionsFlow(config_entries.OptionsFlow):
    """Add, update and remove consumers without editing YAML."""

    def _devices(self):
        return list(self.config_entry.options.get("devices", []))

    def _save(self, *, devices=None, general=None):
        options = dict(self.config_entry.options)
        if devices is not None:
            options["devices"] = devices
        if general is not None:
            options.update(general)
        return self.async_create_entry(title="", data=options)

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["quick_system_sources", "quick_consumer_choose",
                          "quick_data_points", "quick_connections",
                          "quick_diagnostics", "advanced"],
        )

    async def async_step_quick_modbus_setup(self, user_input=None):
        """Compatibility route for an earlier setup entry point."""
        return self.async_show_menu(
            step_id="quick_modbus_setup",
            menu_options=["quick_connections", "quick_read_point_choose",
                          "quick_system_sources"],
        )

    async def async_step_quick_data_points(self, user_input=None):
        """Manage read and write points from one comprehensible location."""
        choices = ["quick_read_point_choose"]
        if self._connections():
            choices.append("modbus_write")
        if self._write_points():
            choices.append("modbus_edit_write")
            choices.append("modbus_remove_write")
        return self.async_show_menu(step_id="quick_data_points", menu_options=choices)

    async def async_step_quick_connections(self, user_input=None):
        """Connections are a separate object, not fifteen advanced actions."""
        choices = ["modbus_connection"]
        if self._connections():
            choices.extend(["modbus_edit_connection", "modbus_remove_connection"])
        return self.async_show_menu(step_id="quick_connections", menu_options=choices)

    async def async_step_advanced_consumers(self, user_input=None):
        return self.async_show_menu(
            step_id="advanced_consumers", menu_options=["add", "edit", "remove"],
        )

    async def async_step_advanced(self, user_input=None):
        """Specialist choices are grouped instead of overwhelming the user."""
        return self.async_show_menu(
            step_id="advanced", menu_options=[
                "general", "advanced_consumers", "quick_connections",
                "quick_data_points", "modbus_test_register",
                "modbus_remove_register",
            ],
        )

    # --- Guided, non-destructive setup (all changes saved only at the end) ---

    async def async_step_quick_system_sources(self, user_input=None):
        merged = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            self._quick_sources = {
                "grid_entity": user_input["grid_entity"],
                "pv_entity": user_input.get("pv_entity"),
                "battery_entity": user_input.get("battery_entity"),
            }
            return await self.async_step_quick_system_direction()
        return self.async_show_form(
            step_id="quick_system_sources",
            data_schema=vol.Schema({
                vol.Required("grid_entity", default=merged.get("grid_entity", "")):
                    _entity(["sensor", "number", "input_number"]),
                vol.Optional("pv_entity", description={"suggested_value": merged.get("pv_entity")})
                    if merged.get("pv_entity") else vol.Optional("pv_entity"):
                    _entity(["sensor", "number", "input_number"]),
                vol.Optional("battery_entity", description={"suggested_value": merged.get("battery_entity")})
                    if merged.get("battery_entity") else vol.Optional("battery_entity"):
                    _entity(["sensor", "number", "input_number"]),
            }),
        )

    async def async_step_quick_system_direction(self, user_input=None):
        merged = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            self._quick_system_opts = {
                **self._quick_sources,
                "grid_export_positive": user_input["grid_sign"] == "plus_export",
                "battery_charge_positive": user_input["battery_sign"] == "plus_charge",
                "interval_s": int(user_input["interval_s"]),
                "reserve_w": int(user_input["reserve_w"]),
            }
            return await self.async_step_quick_system_review()
        return self.async_show_form(
            step_id="quick_system_direction",
            data_schema=vol.Schema({
                vol.Required("grid_sign", default=("plus_export" if merged.get("grid_export_positive", True) else "minus_export")):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="plus_export", label="Positiver Wert = Einspeisung"),
                            selector.SelectOptionDict(value="minus_export", label="Negativer Wert = Einspeisung"),
                        ], mode="dropdown")),
                vol.Required("battery_sign", default=("plus_charge" if merged.get("battery_charge_positive", True) else "minus_charge")):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="plus_charge", label="Positiver Wert = Laden"),
                            selector.SelectOptionDict(value="minus_charge", label="Negativer Wert = Laden"),
                        ], mode="dropdown")),
                vol.Required("interval_s", default=merged.get("interval_s", DEFAULT_INTERVAL)):
                    _num(5, 300),
                vol.Required("reserve_w", default=merged.get("reserve_w", DEFAULT_RESERVE)):
                    _num(0, 10000, 10),
            }),
        )

    async def async_step_quick_system_review(self, user_input=None):
        cfg = self._quick_system_opts
        if user_input is not None:
            if user_input.get("confirm"):
                options = dict(self.config_entry.options)
                options.update(cfg)
                return self.async_create_entry(title="", data=options)
            return self.async_show_form(
                step_id="quick_system_review", data_schema=vol.Schema({
                    vol.Required("confirm", default=False): selector.BooleanSelector()}),
                errors={"base": "confirm_required"},
                description_placeholders=self._quick_system_preview(),
            )
        return self.async_show_form(
            step_id="quick_system_review",
            data_schema=vol.Schema({
                vol.Required("confirm", default=False): selector.BooleanSelector(),
            }),
            description_placeholders=self._quick_system_preview(),
        )

    def _quick_system_preview(self):
        cfg = self._quick_system_opts
        raw = source_power_w(self.hass.states.get(cfg["grid_entity"]))
        net = signed_grid_preview(raw, cfg["grid_export_positive"])
        battery = cfg.get("battery_entity") or "Kein Sensor (0 W angenommen)"
        pv = cfg.get("pv_entity") or "Kein Sensor"
        return {
            "net": net, "grid": cfg["grid_entity"],
            "battery": battery, "pv": pv,
            "interval": str(cfg["interval_s"]), "reserve": str(cfg["reserve_w"]),
        }

    async def async_step_quick_consumer_choose(self, user_input=None):
        """New and existing consumers use exactly the same editable form."""
        devices = self._devices()
        if user_input is not None:
            chosen = user_input["consumer"]
            old = next((dict(d) for d in devices if d["id"] == chosen), None)
                  if chosen != "new" else None
            if chosen != "new" and old is None:
                return self.async_abort(reason="no_devices")
            self._quick_consumer_old = old or {}
            self._quick_consumer_draft = dict(self._quick_consumer_old)
            return await self.async_step_quick_consumer_form()
        choices = [selector.SelectOptionDict(
            value="new", label="Neuen Verbraucher anlegen")]
        choices.extend(selector.SelectOptionDict(
            value=d["id"], label=f"{d['name']} bearbeiten") for d in devices)
        return self.async_show_form(
            step_id="quick_consumer_choose",
            data_schema=vol.Schema({
                vol.Required("consumer", default="new"):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=choices, mode="dropdown"))
            }),
        )

    @staticmethod
    def _quick_consumer_schema(values: dict):
        """Native Home Assistant expandable sections; no navigation dropdown.

        Required section keys intentionally have NO outer default={}. Home
        Assistant must use the defaults of the nested fields when editing.
        """
        d = values
        def optional_entity(key, domains):
            marker = (vol.Optional(key, description={
                "suggested_value": d[key],
            }) if d.get(key) else vol.Optional(key))
            return marker, _entity(domains)

        return vol.Schema({
            vol.Required("basics"): section(vol.Schema({
                vol.Required("name", default=d.get("name", "Neuer Verbraucher")):
                    selector.TextSelector(),
                vol.Required("kind", default=d.get("kind", TYPE_CONTINUOUS)):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=TYPE_CONTINUOUS,
                                label="Stufenlos (Watt/Ampere)"),
                            selector.SelectOptionDict(
                                value=TYPE_STEPPED,
                                label="Feste Leistungsstufen"),
                            selector.SelectOptionDict(
                                value=TYPE_ONOFF, label="Nur Ein / Aus"),
                        ], mode="dropdown")),
                vol.Required("priority", default=d.get("priority", 2)):
                    _num(1, 10),
                vol.Required("subpriority", default=d.get("subpriority", 1)):
                    _num(1, 99),
                vol.Required("min_w", default=d.get("min_w", 1400)):
                    _num(0, 100000, 10),
                vol.Required("max_w", default=d.get("max_w", 11000)):
                    _num(1, 100000, 10),
                vol.Optional("steps_w", default=d.get(
                    "steps_w", "500,1000,1500,2000")):
                    selector.TextSelector(),
            }), {"collapsed": False}),
            vol.Required("actuator"): section(vol.Schema({
                optional_entity("power_output", ["number", "input_number"])[0]:
                    optional_entity("power_output", ["number", "input_number"])[1],
                optional_entity("switch_output", ["switch", "input_boolean"])[0]:
                    optional_entity("switch_output", ["switch", "input_boolean"])[1],
                vol.Required("output_unit", default=d.get("output_unit", "W")):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=["W", "kW", "A"], mode="dropdown")),
                vol.Required("phases", default=str(d.get("phases", 1))):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=["1", "3"], mode="dropdown")),
                vol.Required("voltage", default=d.get("voltage", 230)):
                    _num(100, 260),
            }), {"collapsed": True}),
            vol.Required("feedback"): section(vol.Schema({
                optional_entity("actual_entity", [
                    "sensor", "number", "input_number"])[0]:
                    optional_entity("actual_entity", [
                        "sensor", "number", "input_number"])[1],
                optional_entity("demand_entity", [
                    "binary_sensor", "switch", "input_boolean"])[0]:
                    optional_entity("demand_entity", [
                        "binary_sensor", "switch", "input_boolean"])[1],
            }), {"collapsed": True}),
            vol.Required("timing"): section(vol.Schema({
                vol.Required("start_delay_s", default=d.get("start_delay_s", 0)):
                    _num(0, 3600),
                vol.Required("min_on_s", default=d.get("min_on_s", 0)):
                    _num(0, 86400),
                vol.Required("min_off_s", default=d.get("min_off_s", 0)):
                    _num(0, 86400),
            }), {"collapsed": True}),
            vol.Required("confirm", default=False): selector.BooleanSelector(),
        })

    @staticmethod
    def _quick_consumer_flatten(old: dict, nested: dict) -> dict:
        """Merge a complete sectioned submission without restoring cleared IDs."""
        candidate = dict(old)
        # Closed sections may not submit keys on some HA frontend versions.
        # Preserve their previous values unless that section was submitted.
        for section_name, optional_keys in (
            ("actuator", ("power_output", "switch_output")),
            ("feedback", ("actual_entity", "demand_entity")),
        ):
            if section_name in nested:
                for key in optional_keys:
                    candidate.pop(key, None)
        for section_name in ("basics", "actuator", "feedback", "timing"):
            candidate.update(nested.get(section_name, {}))
        if candidate.get("kind") == TYPE_ONOFF:
            candidate.pop("power_output", None)
            candidate["output_unit"] = "W"
        candidate["id"] = old.get("id", uuid4().hex[:12])
        return candidate

    async def async_step_quick_consumer_form(self, user_input=None):
        """Single screen: expand, edit, validate, save. No next/back fields."""
        if not hasattr(self, "_quick_consumer_old"):
            return await self.async_step_quick_consumer_choose()
        errors = {}
        description = ("Bitte Ausgang, Gerätegrenzen und ggf. Aus-/Pausewert "
                       "vor dem Speichern prüfen.")
        if user_input is not None:
            candidate = self._quick_consumer_flatten(
                self._quick_consumer_old, user_input)
            # Re-render the same editable form on errors, preserving changes.
            self._quick_consumer_draft = candidate
            try:
                normalized, error = _validate_device(candidate)
            except (KeyError, ValueError, TypeError, OverflowError):
                normalized, error = None, "limits"
            if error:
                errors["base"] = error
            else:
                actor = normalized.get(
                    "switch_output" if normalized["kind"] == TYPE_ONOFF
                    else "power_output")
                actor_state = self.hass.states.get(actor) if actor else None
                mismatch = actuator_compatibility_error(normalized, actor_state)
                if mismatch:
                    errors["base"] = mismatch
                    if mismatch == "actuator_step_mismatch":
                        minimum = suggested_minimum_power(
                            normalized, actor_state)
                        if minimum is not None:
                            description = (
                                f"Die konfigurierte Mindestleistung ist nicht "
                                f"darstellbar. Nächster zulässiger Wert: "
                                f"{minimum} W. Im Bereich Grundlagen korrigieren."
                            )
                others = {
                    d.get(key)
                    for d in self._devices()
                    if d["id"] != normalized["id"]
                    for key in ("power_output", "switch_output")
                    if d.get(key)
                }
                if actor in others or any(
                    normalized.get(key) in others
                    for key in ("power_output", "switch_output")
                    if normalized.get(key)
                ):
                    errors["base"] = "duplicate_output"
                if not errors and not user_input.get("confirm"):
                    errors["base"] = "confirm_required"
                if not errors:
                    if self._quick_consumer_old:
                        devices = [
                            normalized if d["id"] == normalized["id"] else d
                            for d in self._devices()
                        ]
                    else:
                        devices = [*self._devices(), normalized]
                    return self._save(devices=devices)

        return self.async_show_form(
            step_id="quick_consumer_form",
            data_schema=self._quick_consumer_schema(self._quick_consumer_draft),
            errors=errors,
            description_placeholders={"hint": description},
        )

    async def async_step_quick_diagnostics(self, user_input=None):
        if user_input is not None:
            return await self.async_step_init()
        cfg = {**self.config_entry.data, **self.config_entry.options}
        grid_name = cfg.get("grid_entity")
        grid = source_power_w(self.hass.states.get(grid_name)) if grid_name else None
        preview = signed_grid_preview(grid, cfg.get("grid_export_positive", True))
        manager = getattr(self.config_entry, "runtime_data", None)
        rows = []
        for d in self._devices():
            actor_id = d.get("switch_output") if d.get("kind") == TYPE_ONOFF else d.get("power_output")
            actor_state = self.hass.states.get(actor_id) if actor_id else None
            actual_id = d.get("actual_entity")
            actual_state = self.hass.states.get(actual_id) if actual_id else None
            warnings = check_consumer_setup(d,
                output_state=actor_state.state if actor_state else None,
                actual_state=actual_state.state if actual_state else None)
            rows.append(f"{d['name']}: {actor_id or 'kein Ausgang'}; " +
                        (" | ".join(warnings) if warnings else "Zuordnung plausibel"))
        return self.async_show_form(
            step_id="quick_diagnostics", data_schema=vol.Schema({}),
            description_placeholders={
                "grid": preview,
                "sensor": grid_name or "Nicht konfiguriert",
                "status": getattr(manager, "status", "Nicht verfügbar"),
                "error": getattr(manager, "error", "") or "Kein Fehler gemeldet",
                "devices": " || ".join(rows) if rows else "Noch keine Verbraucher",
            },
        )

    async def async_step_general(self, user_input=None):
        if user_input is not None:
            # Persist explicit None for cleared optional selectors.  Otherwise
            # an entity from entry.data would reappear when data/options merge.
            options = dict(self.config_entry.options)
            options.update({"battery_entity": None, "pv_entity": None})
            options.update(user_input)
            return self.async_create_entry(title="", data=options)
        merged = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="general", data_schema=_global_schema(merged))

    async def async_step_add(self, user_input=None):
        errors = {}
        if user_input is not None:
            device, error = _validate_device(user_input)
            if error:
                errors["base"] = error
            else:
                other_outputs = {
                    d.get(key) for d in self._devices()
                    for key in ("power_output", "switch_output") if d.get(key)
                }
                if any(device.get(key) in other_outputs for key in
                       ("power_output", "switch_output") if device.get(key)):
                    errors["base"] = "duplicate_output"
                else:
                    device["id"] = uuid4().hex[:12]
                    return self._save(devices=[*self._devices(), device])
        return self.async_show_form(
            step_id="add", data_schema=_device_schema(), errors=errors
        )

    async def async_step_edit(self, user_input=None):
        devices = self._devices()
        if not devices:
            return self.async_abort(reason="no_devices")
        if user_input is not None:
            self._selected = user_input["device_id"]
            return await self.async_step_edit_form()
        return self.async_show_form(step_id="edit", data_schema=vol.Schema({
            vol.Required("device_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    selector.SelectOptionDict(value=d["id"], label=d["name"])
                    for d in devices
                ])
            )
        }))

    async def async_step_edit_form(self, user_input=None):
        devices = self._devices()
        old = next((d for d in devices if d["id"] == self._selected), None)
        if old is None:
            return self.async_abort(reason="no_devices")
        errors = {}
        if user_input is not None:
            updated, error = _validate_device(user_input)
            if error:
                errors["base"] = error
            else:
                other_outputs = {
                    d.get(key) for d in devices if d["id"] != old["id"]
                    for key in ("power_output", "switch_output") if d.get(key)
                }
                if any(updated.get(key) in other_outputs for key in
                       ("power_output", "switch_output") if updated.get(key)):
                    errors["base"] = "duplicate_output"
                else:
                    updated["id"] = old["id"]
                    return self._save(devices=[updated if d["id"] == old["id"] else d
                                               for d in devices])
        return self.async_show_form(
            step_id="edit_form", data_schema=_device_schema(old), errors=errors
        )

    async def async_step_remove(self, user_input=None):
        devices = self._devices()
        if not devices:
            return self.async_abort(reason="no_devices")
        if user_input is not None:
            return self._save(devices=[d for d in devices
                                       if d["id"] != user_input["device_id"]])
        return self.async_show_form(step_id="remove", data_schema=vol.Schema({
            vol.Required("device_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    selector.SelectOptionDict(value=d["id"], label=d["name"])
                    for d in devices
                ])
            )
        }))

    def _connections(self):
        return list(self.config_entry.options.get("modbus_connections", []))

    def _registers(self):
        return list(self.config_entry.options.get("modbus_registers", []))

    def _write_points(self):
        return list(self.config_entry.options.get("modbus_write_points", []))

    async def async_step_quick_read_point_choose(self, user_input=None):
        """Choose new or existing read sensor; keep its stable ID when editing."""
        connections = self._connections()
        if not connections:
            return self.async_show_menu(
                step_id="quick_read_point_choose",
                menu_options=["modbus_connection", "quick_connections"],
            )
        if user_input is not None:
            ident = user_input["register_id"]
            old = next((dict(point) for point in self._registers()
                        if point["id"] == ident), None) if ident != "new" else None
            if ident != "new" and old is None:
                return self.async_abort(reason="no_modbus_registers")
            self._quick_read_id = old["id"] if old else None
            self._quick_read_draft = old or {}
            self._quick_read_result = ""
            self._quick_read_tested = None
            return await self.async_step_quick_read_point_form()
        options = [selector.SelectOptionDict(
            value="new", label="Neuen Modbus-Lesesensor anlegen",
        )]
        options.extend(selector.SelectOptionDict(
            value=r["id"], label=f"{r['name']} bearbeiten",
        ) for r in self._registers())
        return self.async_show_form(
            step_id="quick_read_point_choose",
            data_schema=vol.Schema({
                vol.Required("register_id", default="new"):
                    selector.SelectSelector(selector.SelectSelectorConfig(
                        options=options, mode="dropdown")),
            }),
        )

    @staticmethod
    def _quick_read_signature(config: dict) -> tuple:
        """An edited draft must be retested before it can be saved."""
        return tuple(sorted((key, value) for key, value in config.items()
                            if key != "id"))

    def _quick_read_schema(self, values: dict):
        """Existing register fields plus one explicit workflow action."""
        base_schema = _modbus_register_schema(self._connections(), values)
        schema = dict(base_schema.schema if hasattr(base_schema, "schema")
                      else base_schema)
        schema[vol.Required("wizard_action", default="test")] = (
            selector.SelectSelector(selector.SelectSelectorConfig(options=[
                selector.SelectOptionDict(value="test", label="Verbindung und Register testen"),
                selector.SelectOptionDict(value="save", label="Geprüfte Einstellungen speichern"),
                selector.SelectOptionDict(value="back", label="Zur Sensor-Auswahl zurück"),
            ], mode="dropdown")))
        return vol.Schema(schema)

    async def _quick_read_test(self, reg: dict) -> tuple[bool, str]:
        """Read only the current unsaved draft, never touch write registers."""
        from homeassistant.components.modbus import async_get_temporary_unit
        from modbus_connection import ModbusTcpParams
        import asyncio

        connection = next((conn for conn in self._connections()
                           if conn["id"] == reg["connection_id"]), None)
        if connection is None:
            return False, "Verbindung nicht mehr vorhanden."
        try:
            async with asyncio.timeout(10):
                async with async_get_temporary_unit(
                    self.hass,
                    ModbusTcpParams(
                        host=connection["host"], port=int(connection["port"])),
                    int(connection["unit_id"]),
                ) as unit:
                    read = (unit.read_holding_registers
                            if int(reg["function_code"]) == 3
                            else unit.read_input_registers)
                    registers = list(await read(
                        int(reg["address"]), TYPE_WIDTH[reg["data_type"]]))
                decoded = decode_registers(
                    registers, reg["data_type"], reg["byte_order"],
                    reg["scale"], reg["offset"],
                )
            return True, (
                f"Lesetest erfolgreich: {decoded:g} {reg.get('unit', '')} "
                f"(Rohregister: {registers}; FC{reg['function_code']}; "
                f"Adresse {reg['address']}). "
                "Bitte prüfen, ob der Wert physikalisch sinnvoll ist."
            )
        except Exception as exc:
            return False, (
                f"Lesetest fehlgeschlagen: {type(exc).__name__}: {exc}. "
                "Angaben korrigieren und erneut testen; nichts gespeichert."
            )

    async def async_step_quick_read_point_form(self, user_input=None):
        """Configure, test, correct, retest and save in the SAME form.

        A test only performs Modbus reads. The options entry, existing entity
        ID and runtime sensor are untouched until Save is explicitly selected.
        """
        if not self._connections():
            return self.async_abort(reason="no_modbus_connections")
        if not hasattr(self, "_quick_read_draft"):
            return await self.async_step_quick_read_point_choose()

        errors = {}
        if user_input is not None:
            action = user_input.get("wizard_action", "test")
            if action == "back":
                return await self.async_step_quick_read_point_choose()
            draft = {key: value for key, value in user_input.items()
                     if key != "wizard_action"}
            normalized, error = validate_read_point(
                draft, {conn["id"] for conn in self._connections()})
            self._quick_read_draft = normalized if not error else draft
            if error:
                errors["base"] = error
                self._quick_read_result = (
                    "Eingaben prüfen und korrigieren; noch nicht gespeichert."
                )
            elif action == "test":
                success, result = await self._quick_read_test(normalized)
                self._quick_read_result = result
                self._quick_read_tested = (
                    self._quick_read_signature(normalized) if success else None
                )
                if not success:
                    errors["base"] = "read_test_failed"
            elif action == "save":
                if self._quick_read_tested != self._quick_read_signature(normalized):
                    errors["base"] = "read_test_required"
                    self._quick_read_result = (
                        "Bitte diese Einstellungen zuerst erfolgreich testen. "
                        "Nach jeder Änderung ist ein erneuter Test erforderlich."
                    )
                else:
                    point = dict(normalized)
                    point["id"] = self._quick_read_id or uuid4().hex[:12]
                    options = dict(self.config_entry.options)
                    current = self._registers()
                    if self._quick_read_id:
                        if not any(p["id"] == self._quick_read_id for p in current):
                            return self.async_abort(reason="no_modbus_registers")
                        options["modbus_registers"] = [
                            point if p["id"] == self._quick_read_id else p
                            for p in current
                        ]
                    else:
                        options["modbus_registers"] = [*current, point]
                    return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="quick_read_point_form",
            data_schema=self._quick_read_schema(self._quick_read_draft),
            errors=errors,
            description_placeholders={
                "result": self._quick_read_result or (
                    "Noch nicht getestet. Du kannst Eingaben ändern und "
                    "beliebig oft einen neuen Lesetest durchführen. "
                    "Vor dem erfolgreichen Test wird nichts gespeichert."
                ),
            },
        )

    async def async_step_modbus_write(self, user_input=None):
        """Create a write-only number with explicitly defined stop semantics."""
        connections = self._connections()
        if not connections:
            return self.async_abort(reason="no_modbus_connections")
        errors = {}
        if user_input is not None:
            point, error = validate_write_point(user_input, {c["id"] for c in connections})
            if error:
                errors["base"] = error
            else:
                point["id"] = uuid4().hex[:12]
                options = dict(self.config_entry.options)
                options["modbus_write_points"] = [*self._write_points(), point]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_write", data_schema=_modbus_write_schema(connections), errors=errors
        )

    async def async_step_modbus_edit_write(self, user_input=None):
        points = self._write_points()
        if not points:
            return self.async_abort(reason="no_modbus_write_points")
        if user_input is not None:
            self._chosen_write_point = user_input["write_id"]
            return await self.async_step_modbus_edit_write_form()
        return self.async_show_form(step_id="modbus_edit_write", data_schema=vol.Schema({
            vol.Required("write_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    selector.SelectOptionDict(value=p["id"], label=p["name"]) for p in points
                ])
            )
        }))

    async def async_step_modbus_edit_write_form(self, user_input=None):
        points = self._write_points()
        old = next((p for p in points if p["id"] == self._chosen_write_point), None)
        if old is None:
            return self.async_abort(reason="no_modbus_write_points")
        errors = {}
        if user_input is not None:
            point, error = validate_write_point(user_input, {c["id"] for c in self._connections()})
            if error:
                errors["base"] = error
            else:
                point["id"] = old["id"]
                options = dict(self.config_entry.options)
                options["modbus_write_points"] = [
                    point if x["id"] == old["id"] else x for x in points
                ]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(step_id="modbus_edit_write_form",
                                    data_schema=_modbus_write_schema(self._connections(), old),
                                    errors=errors)

    async def async_step_modbus_remove_write(self, user_input=None):
        points = self._write_points()
        if not points:
            return self.async_abort(reason="no_modbus_write_points")
        if user_input is not None:
            options = dict(self.config_entry.options)
            options["modbus_write_points"] = [
                p for p in points if p["id"] != user_input["write_id"]
            ]
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(step_id="modbus_remove_write", data_schema=vol.Schema({
            vol.Required("write_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    selector.SelectOptionDict(value=p["id"], label=p["name"]) for p in points
                ])
            )
        }))

    async def async_step_modbus_connection(self, user_input=None):
        """Register a Modbus-TCP endpoint, no network I/O until a register is read."""
        errors = {}
        if user_input is not None:
            conn, error = validate_connection(user_input)
            existing = self._connections()
            if error:
                errors["base"] = error
            elif any((c["host"].lower(), c["port"], c["unit_id"]) ==
                     (conn["host"].lower(), conn["port"], conn["unit_id"]) for c in existing):
                errors["base"] = "duplicate_endpoint"
            else:
                conn["id"] = uuid4().hex[:12]
                options = dict(self.config_entry.options)
                options["modbus_connections"] = [*existing, conn]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_connection",
            data_schema=_modbus_connection_schema(),
            errors=errors,
        )

    async def async_step_modbus_register(self, user_input=None):
        """Create a read-only native HA sensor from one Modbus register range."""
        connections = self._connections()
        if not connections:
            return self.async_abort(reason="no_modbus_connections")
        errors = {}
        if user_input is not None:
            reg, error = validate_read_point(
                user_input, {c["id"] for c in connections}
            )
            if error:
                errors["base"] = error
            else:
                reg["id"] = uuid4().hex[:12]
                options = dict(self.config_entry.options)
                options["modbus_registers"] = [*self._registers(), reg]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_register",
            data_schema=_modbus_register_schema(connections),
            errors=errors,
        )

    async def async_step_modbus_edit_connection(self, user_input=None):
        connections = self._connections()
        if not connections:
            return self.async_abort(reason="no_modbus_connections")
        if user_input:
            self._chosen_modbus_connection = user_input["connection_id"]
            return await self.async_step_modbus_edit_connection_form()
        return self.async_show_form(
            step_id="modbus_edit_connection",
            data_schema=vol.Schema({
                vol.Required("connection_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=c["id"], label=c["name"])
                        for c in connections
                    ])),
            }),
        )

    async def async_step_modbus_edit_connection_form(self, user_input=None):
        connections = self._connections()
        old = next((c for c in connections if c["id"] == self._chosen_modbus_connection), None)
        if old is None:
            return self.async_abort(reason="no_modbus_connections")
        errors = {}
        if user_input:
            new, error = validate_connection(user_input)
            if error:
                errors["base"] = error
            elif any(c["id"] != old["id"] and
                     (c["host"].lower(), c["port"], c["unit_id"]) ==
                     (new["host"].lower(), new["port"], new["unit_id"]) for c in connections):
                errors["base"] = "duplicate_endpoint"
            else:
                new["id"] = old["id"]
                options = dict(self.config_entry.options)
                options["modbus_connections"] = [
                    new if c["id"] == old["id"] else c for c in connections
                ]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_edit_connection_form",
            data_schema=_modbus_connection_schema(old), errors=errors,
        )

    async def async_step_modbus_edit_register(self, user_input=None):
        registers = self._registers()
        if not registers:
            return self.async_abort(reason="no_modbus_registers")
        if user_input:
            self._chosen_modbus_register = user_input["register_id"]
            return await self.async_step_modbus_edit_register_form()
        return self.async_show_form(
            step_id="modbus_edit_register",
            data_schema=vol.Schema({
                vol.Required("register_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=r["id"], label=r["name"])
                        for r in registers
                    ])),
            }),
        )

    async def async_step_modbus_edit_register_form(self, user_input=None):
        registers = self._registers()
        old = next((r for r in registers if r["id"] == self._chosen_modbus_register), None)
        if old is None:
            return self.async_abort(reason="no_modbus_registers")
        errors = {}
        if user_input:
            new, error = validate_read_point(
                user_input, {c["id"] for c in self._connections()}
            )
            if error:
                errors["base"] = error
            else:
                new["id"] = old["id"]
                options = dict(self.config_entry.options)
                options["modbus_registers"] = [
                    new if r["id"] == old["id"] else r for r in registers
                ]
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_edit_register_form",
            data_schema=_modbus_register_schema(self._connections(), old), errors=errors,
        )

    async def async_step_modbus_test_register(self, user_input=None):
        """Run an explicitly requested register read without changing options."""
        regs = self._registers()
        if not regs:
            return self.async_abort(reason="no_modbus_registers")
        if user_input is not None:
            from homeassistant.components.modbus import async_get_temporary_unit
            from modbus_connection import ModbusTcpParams
            import asyncio

            reg = next((r for r in regs if r["id"] == user_input["register_id"]), None)
            conn = next((c for c in self._connections()
                         if reg and c["id"] == reg["connection_id"]), None)
            if not reg or not conn:
                return self.async_abort(reason="no_modbus_connections")
            try:
                async with asyncio.timeout(10):
                    async with async_get_temporary_unit(
                        self.hass,
                        ModbusTcpParams(host=conn["host"], port=int(conn["port"])),
                        int(conn["unit_id"]),
                    ) as unit:
                        if int(reg["function_code"]) == 3:
                            raw = await unit.read_holding_registers(
                                int(reg["address"]), TYPE_WIDTH[reg["data_type"]]
                            )
                        else:
                            raw = await unit.read_input_registers(
                                int(reg["address"]), TYPE_WIDTH[reg["data_type"]]
                            )
                    value = decode_registers(
                        list(raw), reg["data_type"], reg["byte_order"],
                        reg["scale"], reg["offset"],
                    )
                self._test_result = (
                    f"{reg['name']}: {value:g} {reg.get('unit', '')}; "
                    f"Rohregister: {list(raw)}"
                )
            except Exception as exc:
                self._test_result = (
                    f"Testlesen fehlgeschlagen: {type(exc).__name__}: {exc}"
                )
            return await self.async_step_modbus_test_result()
        return self.async_show_form(
            step_id="modbus_test_register",
            data_schema=vol.Schema({
                vol.Required("register_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=r["id"], label=r["name"])
                        for r in regs
                    ]))
            }),
        )

    async def async_step_modbus_test_result(self, user_input=None):
        """Show the last explicit read result without persisting it."""
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(
            step_id="modbus_test_result",
            data_schema=vol.Schema({}),
            description_placeholders={"result": getattr(self, "_test_result", "")},
        )

    async def async_step_modbus_remove_register(self, user_input=None):
        registers = self._registers()
        if not registers:
            return self.async_abort(reason="no_modbus_registers")
        if user_input:
            options = dict(self.config_entry.options)
            options["modbus_registers"] = [
                r for r in registers if r["id"] != user_input["register_id"]
            ]
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_remove_register",
            data_schema=vol.Schema({
                vol.Required("register_id"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[
                        selector.SelectOptionDict(value=r["id"], label=r["name"])
                        for r in registers
                    ])),
            }),
        )

    async def async_step_modbus_remove_connection(self, user_input=None):
        connections = self._connections()
        if not connections:
            return self.async_abort(reason="no_modbus_connections")
        if user_input:
            chosen = user_input["connection_id"]
            if (any(r["connection_id"] == chosen for r in self._registers())
                    or any(w["connection_id"] == chosen for w in self._write_points())):
                return self.async_show_form(
                    step_id="modbus_remove_connection",
                    data_schema=self._modbus_remove_connection_schema(),
                    errors={"base": "connection_has_registers"},
                )
            options = dict(self.config_entry.options)
            options["modbus_connections"] = [c for c in connections
                                             if c["id"] != chosen]
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="modbus_remove_connection",
            data_schema=self._modbus_remove_connection_schema(),
        )

    def _modbus_remove_connection_schema(self):
        return vol.Schema({
            vol.Required("connection_id"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=[
                    selector.SelectOptionDict(value=c["id"], label=c["name"])
                    for c in self._connections()
                ])),
        })
