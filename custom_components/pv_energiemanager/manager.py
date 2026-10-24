"""Runtime bridge between Home Assistant entities and the EMS calculation core."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import math
import time
from typing import Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN, DEFAULT_INTERVAL, DEFAULT_RESERVE, DEFAULT_SETTLE
from .engine import Consumer, distribute

_LOGGER = logging.getLogger(__name__)


class PowerManager:
    """Run one full calculation and actuator update every configured interval."""

    def __init__(self, hass: HomeAssistant, entry):
        self.hass = hass
        self.entry = entry
        self.settings = {**entry.data, **entry.options}
        self.devices = list(entry.options.get("devices", []))
        self.enabled = False  # Explicit enable required after every HA restart.
        self.running = False
        self.status = "Pausiert"
        self.error = ""
        self.cycle_count = 0
        self.values: dict[str, float | str | None] = {
            "grid": None, "battery": 0, "pv": None, "budget": None,
            "assigned": 0, "unallocated": 0, "deficit": 0,
        }
        self.per_device: dict[str, dict] = {
            d["id"]: {"target": 0, "actual": None, "demand": False, "accounted": 0}
            for d in self.devices
        }
        self.last_targets: dict[str, int] = {}
        self.last_change: dict[str, float] = {}
        self.last_started: dict[str, float] = {}
        self.last_stopped: dict[str, float] = {}
        self.request_since: dict[str, float] = {}
        self.group_records: list[dict] = []
        self._listeners: list[Callable] = []
        self._unsubscribe = None
        self._lock = asyncio.Lock()
        self._bootstrapped = False

    @callback
    def subscribe(self, listener: Callable):
        self._listeners.append(listener)

        @callback
        def unsubscribe():
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    @callback
    def notify(self):
        for fn in tuple(self._listeners):
            fn()

    def start(self):
        interval = int(self.settings.get("interval_s", DEFAULT_INTERVAL))
        self._unsubscribe = async_track_time_interval(
            self.hass,
            lambda _: self.hass.async_create_task(self.async_cycle()),
            timedelta(seconds=interval),
        )

    def stop(self):
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        self.enabled = False

    def enable(self, value: bool):
        self.enabled = value
        self.status = "Bereit" if value else "Pausiert"
        self.error = ""
        self.notify()

    def _read_watts(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", "none"):
            return None
        try:
            val = float(state.state)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(val):
            return None
        unit = str(state.attributes.get("unit_of_measurement", "W")).strip().lower()
        if unit == "kw":
            return val * 1000
        if unit == "mw":
            return val * 1_000_000
        if unit in ("w", "", "watt"):
            return val
        return None  # Do not accidentally treat Wh/A as W.

    def _read_actual(self, entity_id: str | None) -> float | None:
        val = self._read_watts(entity_id)
        if val is None or val < -1:
            return None
        state = self.hass.states.get(entity_id)
        if state:
            freshness = getattr(state, "last_reported", None)
            if freshness is None:
                freshness = state.last_updated
            if freshness is not None:
                age = (datetime.now(timezone.utc) - freshness).total_seconds()
                if age > 180:
                    return None
        return max(0, val)

    def _read_demand(self, device: dict) -> bool:
        entity = device.get("demand_entity")
        if not entity:
            return True
        state = self.hass.states.get(entity)
        return state is not None and state.state == "on"

    def _conversion_factor(self, device: dict) -> float:
        unit = device.get("output_unit", "W")
        if unit == "kW":
            return 1000.0
        if unit == "A":
            return float(device.get("voltage", 230)) * int(device.get("phases", 1))
        return 1.0

    def _observed_target(self, device: dict) -> int:
        """Read initial actuator state to avoid an unreserved startup load."""
        switch = device.get("switch_output")
        if switch:
            state = self.hass.states.get(switch)
            if state is None or state.state not in ("on", "off"):
                return 0
            if state.state == "off":
                return 0
        if device["kind"] == "onoff":
            return int(device["max_w"]) if switch and self.hass.states.get(switch).state == "on" else 0
        entity = device.get("power_output")
        if not entity:
            return 0
        state = self.hass.states.get(entity)
        if state is None:
            return 0
        try:
            power = float(state.state) * self._conversion_factor(device)
            if not math.isfinite(power):
                return 0
            return max(0, min(int(power), int(device["max_w"])))
        except (ValueError, TypeError):
            return 0

    def _startup(self):
        if self._bootstrapped:
            return
        for d in self.devices:
            self.last_targets[d["id"]] = self._observed_target(d)
            self.per_device[d["id"]]["target"] = self.last_targets[d["id"]]
        self._bootstrapped = True

    def _build_consumers(self, now: float, *, preview: bool) -> list[Consumer]:
        result = []
        settle = int(self.settings.get("feedback_settle_s", DEFAULT_SETTLE))
        for d in self.devices:
            key = d["id"]
            old = self.last_targets.get(key, 0)
            demand = self._read_demand(d)
            actual = self._read_actual(d.get("actual_entity"))
            self.per_device[key]["actual"] = actual
            self.per_device[key]["demand"] = demand

            # Hardware minimum-on intervals are tracked from successful commands.
            # No "locked-on" assumption following restart: such history is unknown.
            locked = bool(old > 0 and now - self.last_started.get(key, -1e12)
                          < int(d.get("min_on_s", 0)))
            min_off_s = int(d.get("min_off_s", 0))
            off_timer_ok = now - self.last_stopped.get(key, -1e12) >= min_off_s
            start_ready = preview or (
                key in self.request_since and
                now - self.request_since[key] >= int(d.get("start_delay_s", 0))
            )
            if old > 0:
                start_ready = True

            steps = ()
            if d["kind"] == "stepped":
                steps = tuple(int(x.strip()) for x in d["steps_w"].split(",") if x.strip())
            result.append(Consumer(
                id=key,
                priority=int(d["priority"]),
                subpriority=int(d["subpriority"]),
                kind=d["kind"],
                minimum=int(d["min_w"]),
                maximum=int(d["max_w"]),
                steps=steps,
                requested=demand,
                allowed_to_start=(off_timer_ok and start_ready),
                locked_on=locked,
                old_target=old,
                actual=actual,
                feedback_settled=(actual is not None and
                                  now - self.last_change.get(key, -1e12) >= settle),
            ))
        return result

    def _round_command(self, d: dict, watts: int) -> tuple[float, int]:
        """Quantize W to an actuator command without exceeding planned W."""
        factor = self._conversion_factor(d)
        value = watts / factor
        entity = d.get("power_output")
        state = self.hass.states.get(entity) if entity else None
        step = float(state.attributes.get("step", 0.01)) if state else 0.01
        if not math.isfinite(step) or step <= 0:
            step = 0.01
        value = math.floor((value + 1e-8) / step) * step
        value = round(value, 5)
        if state:
            minimum = state.attributes.get("min")
            maximum = state.attributes.get("max")
            if maximum is not None and value > float(maximum) + 1e-6:
                raise ValueError(f"Ausgang {entity}: Maximalwert überschritten")
            if watts > 0 and minimum is not None and value < float(minimum) - 1e-6:
                raise ValueError(f"Ausgang {entity}: Min {minimum}, Soll {value}; Einstellungen prüfen")
        effective = int(round(value * factor))
        if watts > 0 and effective < int(d["min_w"]) - 10:
            raise ValueError(f"Ausgang {entity}: Sollleistung nach Rundung unter Minimum")
        return value, effective

    async def _write(self, d: dict, new_w: int) -> int:
        """Write to native HA entities (Modbus/MQTT/OCPP bridge is external)."""
        ident = d["id"]
        old = self.last_targets.get(ident, 0)
        if old == new_w:
            return old
        for entity_id in (d.get("switch_output"), d.get("power_output")):
            if not entity_id:
                continue
            entity = self.hass.states.get(entity_id)
            if entity is None or entity.state in ("unknown", "unavailable"):
                raise ValueError(f"Aktor {entity_id} nicht verfügbar; keine Befehle")
        onoff = d.get("switch_output")
        power = d.get("power_output")
        if d["kind"] == "onoff":
            if not onoff:
                raise ValueError("Ein/Aus-Verbraucher ohne Schaltausgang")
            domain = onoff.split(".", 1)[0]
            await self.hass.services.async_call(
                domain, "turn_on" if new_w > 0 else "turn_off",
                {"entity_id": onoff}, blocking=True,
            )
            effective = int(d["max_w"]) if new_w > 0 else 0
        elif new_w == 0 and onoff:
            domain = onoff.split(".", 1)[0]
            await self.hass.services.async_call(
                domain, "turn_off", {"entity_id": onoff}, blocking=True,
            )
            effective = 0
        else:
            if not power:
                raise ValueError("Leistungssteller ohne Power-Ausgang")
            value, effective = self._round_command(d, new_w)
            domain = power.split(".", 1)[0]
            if new_w > 0 and onoff:
                # Set limit before enabling; never enable unlimited load.
                await self.hass.services.async_call(
                    domain, "set_value", {"entity_id": power, "value": value},
                    blocking=True,
                )
                if old <= 0:
                    on_domain = onoff.split(".", 1)[0]
                    await self.hass.services.async_call(
                        on_domain, "turn_on", {"entity_id": onoff}, blocking=True,
                    )
            else:
                await self.hass.services.async_call(
                    domain, "set_value", {"entity_id": power, "value": value},
                    blocking=True,
                )
        now = time.monotonic()
        self.last_targets[ident] = effective
        self.last_change[ident] = now
        if old == 0 and effective > 0:
            self.last_started[ident] = now
        if old > 0 and effective == 0:
            self.last_stopped[ident] = now
            self.request_since.pop(ident, None)
        return effective

    async def async_cycle(self):
        """Always refresh measurements; write actuator commands only when enabled.

        Monitoring must remain useful while the EMS is paused. Paused cycles
        perform no Home Assistant service calls and do not advance demand
        timers or the active regulation-cycle counter.
        """
        if self._lock.locked():
            return
        async with self._lock:
            self.running = self.enabled
            try:
                self._startup()
                grid = self._read_watts(self.settings.get("grid_entity"))
                batt_entity = self.settings.get("battery_entity")
                battery = self._read_watts(batt_entity) if batt_entity else 0.0
                pv = self._read_watts(self.settings.get("pv_entity"))
                if grid is not None and not self.settings.get("grid_export_positive", True):
                    grid *= -1
                if battery is not None and not self.settings.get("battery_charge_positive", True):
                    battery *= -1
                # Inputs are exposed even when live regulation is switched off.
                self.values.update({"grid": grid, "battery": battery, "pv": pv})
                if grid is None or battery is None:
                    self.values.update({"budget": None, "deficit": None})
                    self.status = "Messfehler" if self.enabled else "Pausiert (Messfehler)"
                    self.error = "Netz- oder Batteriesensor fehlt/ist ungültig; keine Schreibbefehle"
                    return

                now = time.monotonic()
                consumers = self._build_consumers(now, preview=True)
                accounted = sum(
                    (c.actual if c.actual is not None else c.old_target)
                    for c in consumers
                )
                reserve = float(self.settings.get("reserve_w", DEFAULT_RESERVE))
                budget = grid + battery + accounted - reserve
                self.values.update({
                    "budget": round(budget, 1), "deficit": max(0.0, -budget),
                })
                if not self.enabled:
                    # Observation only: never calculate or apply new actuator
                    # commands, and never touch activation/delay bookkeeping.
                    self.status = "Pausiert"
                    self.error = ""
                    return

                preview = distribute(budget, consumers)
                for d in self.devices:
                    key = d["id"]
                    desired = preview.targets[key]
                    current = self.last_targets.get(key, 0)
                    if self._read_demand(d) and current == 0 and desired > 0:
                        self.request_since.setdefault(key, now)
                    elif not self._read_demand(d) or desired == 0:
                        self.request_since.pop(key, None)

                execution = distribute(budget, self._build_consumers(now, preview=False))
                desired = execution.targets
                self.group_records = execution.group_records
                self.values["assigned"] = sum(desired.values())
                self.values["unallocated"] = round(execution.unallocated, 1)
                self.cycle_count += 1

                # Commands only on target change; reductions before increases.
                declines = [d for d in self.devices if desired[d["id"]] <
                            self.last_targets.get(d["id"], 0)]
                raises = [d for d in self.devices if desired[d["id"]] >
                          self.last_targets.get(d["id"], 0)]
                for d in sorted(declines, key=lambda x: (x["priority"], x["subpriority"]), reverse=True):
                    await self._write(d, desired[d["id"]])

                for d in sorted(raises, key=lambda x: (x["priority"], x["subpriority"])):
                    await self._write(d, desired[d["id"]])

                self.status = "Aktiv" if budget >= 0 else "Leistungsmangel"
                self.error = ""
            except Exception as exc:  # Any failed device command halts this cycle.
                self.status = "Fehler"
                self.error = str(exc)
                _LOGGER.exception("PV Energiemanager Regelzyklus fehlgeschlagen")
            finally:
                for d in self.devices:
                    key = d["id"]
                    c = self.per_device[key]
                    c["target"] = self.last_targets.get(key, 0)
                    c["accounted"] = (
                        c["actual"] if c["actual"] is not None else c["target"]
                    )
                self.running = False
                self.notify()
