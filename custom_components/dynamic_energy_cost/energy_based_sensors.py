import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from functools import cached_property
from typing import Any, Literal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import StateType
from homeassistant.util.dt import now

from .const import DEFAULT_CURRENCY, DOMAIN, ELECTRICITY_PRICE_SENSOR, ENERGY_SENSOR

_LOGGER = logging.getLogger(__name__)

IntervalType = Literal["daily", "monthly", "yearly"]


class BaseEnergyCostSensor(RestoreEntity, SensorEntity):
    """Base sensor for handling energy cost data."""

    def __init__(self, hass: HomeAssistant, energy_sensor_id: str, price_sensor_id: str, interval: IntervalType) -> None:
        super().__init__()
        self.hass = hass
        self._energy_sensor_id = energy_sensor_id
        self._price_sensor_id = price_sensor_id
        self._state = None
        self._interval = interval
        self._last_energy_reading = None
        self._cumulative_energy_kwh = 0
        self._last_reset_time = now()

        # We don't just define _attr_unit_of_measurement here because it could change later and we don't want it to be
        # cached if accessed via `Entity.unit_of_measurement`, which is a `@cached_property`.
        self._unit_of_measurement = DEFAULT_CURRENCY  # Default to DEFAULT_CURRENCY, will update after entity addition

        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:cash"

        self._schedule_next_reset()
        _LOGGER.debug("Sensor initialized with energy sensor ID %s and price sensor ID %s.", energy_sensor_id, price_sensor_id)

        _LOGGER.debug("Initializing EnergyCostSensor with energy_sensor_id: %s and price_sensor_id: %s", energy_sensor_id, price_sensor_id)

        # Generate friendly names based on the energy sensor's ID
        base_part = energy_sensor_id.split(".")[-1]
        _LOGGER.debug("Base part extracted from energy_sensor_id: %s", base_part)

        friendly_name_parts = base_part.replace("_", " ").split()
        _LOGGER.debug("Parts after replacing underscores and splitting: %s", friendly_name_parts)

        # Exclude words that are commonly not part of the main identifier
        friendly_name_parts = [word for word in friendly_name_parts if word.lower() != "energy"]
        _LOGGER.debug("Parts after removing 'energy': %s", friendly_name_parts)

        friendly_name = " ".join(friendly_name_parts).title()
        _LOGGER.debug("Final friendly name generated: %s", friendly_name)

        self._base_name = friendly_name
        self._device_name = friendly_name + " Dynamic Energy Cost"

        self._attr_unique_id = f"{self._price_sensor_id}_{self._energy_sensor_id}_{self._interval}_cost"

        _LOGGER.debug("Sensor base name set to: %s", self._base_name)
        _LOGGER.debug("Sensor device name set to: %s", self._device_name)

    @callback
    def async_reset(self) -> None:
        """Reset the energy cost and cumulative energy kWh."""
        _LOGGER.debug("Resetting cost for %s", self.entity_id)
        self._state = 0
        self._cumulative_energy_kwh = 0
        self.async_write_ha_state()

    @cached_property
    def name(self) -> str | None:
        return f"{self._base_name} {self._interval.capitalize()} Energy Cost"

    @cached_property
    def device_info(self) -> DeviceInfo | None:
        """Return device information to link this sensor with the integration."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._energy_sensor_id)},
            name=self._device_name,
            manufacturer="Custom Integration",
        )

    @property
    def state(self) -> StateType:
        return self._state

    @property
    def unit_of_measurement(self) -> str | None:
        return self._unit_of_measurement

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return the state attributes of the device."""
        attrs = super().extra_state_attributes or {}  # Ensure it's a dict
        attrs["cumulative_energy_kwh"] = self._cumulative_energy_kwh
        attrs["last_energy_reading"] = self._last_energy_reading
        attrs["average_energy_cost"] = self._state / self._cumulative_energy_kwh if self._cumulative_energy_kwh else 0
        return attrs

    async def async_added_to_hass(self) -> None:
        """Load the last known state and subscribe to updates."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
            self._state = float(last_state.state)
            self._last_energy_reading = float(last_state.attributes.get("last_energy_reading"))
            self._cumulative_energy_kwh = float(last_state.attributes.get("cumulative_energy_kwh"))
            self._attr_unit_of_measurement = last_state.attributes.get("unit_of_measurement")
        else:
            self._unit_of_measurement = self._get_currency()
        self.async_write_ha_state()
        async_track_state_change_event(self.hass, self._energy_sensor_id, self._async_update_energy_price_event)
        self._schedule_next_reset()

    def _get_currency(self) -> str:
        """Extract the currency from the unit of measurement of the price sensor."""
        price_entity = self.hass.states.get(self._price_sensor_id)
        if price_entity and price_entity.attributes.get("unit_of_measurement"):
            currency = price_entity.attributes["unit_of_measurement"].split("/")[0].strip()
            _LOGGER.debug("Extracted currency '%s' from unit of measurement '%s'.", currency, price_entity.attributes["unit_of_measurement"])
        else:
            currency = DEFAULT_CURRENCY
            _LOGGER.warning(
                "Unit of measurement not available or invalid for sensor %s, defaulting to '%s'.",
                self._price_sensor_id,
                DEFAULT_CURRENCY,
            )
        return currency

    def _calculate_next_reset_time(self) -> datetime:
        current_time = now()
        if self._interval == "daily":
            next_reset = current_time.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        elif self._interval == "monthly":
            next_month = (current_time.replace(day=1) + timedelta(days=32)).replace(day=1)
            next_reset = next_month.replace(hour=0, minute=0, second=0, microsecond=0)
        elif self._interval == "yearly":
            next_reset = current_time.replace(year=current_time.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return next_reset

    def _schedule_next_reset(self) -> None:
        next_reset = self._calculate_next_reset_time()
        async_track_point_in_time(self.hass, self._reset_meter, next_reset)

    async def _reset_meter(self, next_reset: datetime) -> None:
        self._state = 0  # Reset the cost to zero
        self._cumulative_energy_kwh = 0  # Reset the cumulative energy kWh count to zero
        self.async_write_ha_state()  # Update the state in Home Assistant
        self._schedule_next_reset()  # Reschedule the next reset

        _LOGGER.debug(
            "Meter reset for %s and cumulative energy reset to %s. Next reset scheduled for %s.",
            self.name,
            self._cumulative_energy_kwh,
            next_reset.isoformat(),
        )

    async def _async_update_energy_price_event(self, event: Event[EventStateChangedData]) -> None:
        """Handle sensor state changes based on event data."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            _LOGGER.debug("New state is unknown or unavailable, skipping update.")
            return
        await self.async_update()

    async def async_update(self) -> None:
        """Update the energy costs using the latest sensor states, only adding incremental costs."""
        _LOGGER.debug("Attempting to update energy costs.")
        energy_state = self.hass.states.get(self._energy_sensor_id)
        price_state = self.hass.states.get(self._price_sensor_id)

        if (
            not energy_state
            or energy_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            or not price_state
            or price_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        ):
            _LOGGER.warning("One or more sensors are unavailable. Skipping update.")
            return

        try:
            current_energy = float(energy_state.state)
            price = float(price_state.state)

            if self._last_energy_reading is not None and current_energy >= self._last_energy_reading:
                energy_difference = current_energy - self._last_energy_reading
                cost_increment = energy_difference * price
                self._state = (self._state if self._state is not None else 0) + cost_increment
                self._cumulative_energy_kwh += energy_difference  # Add to the running total of energy
                _LOGGER.info(
                    "Energy cost incremented by %s %s, total cost now %s %s",
                    cost_increment,
                    self._unit_of_measurement,
                    self._state,
                    self._unit_of_measurement,
                )

            elif self._last_energy_reading is not None and current_energy < self._last_energy_reading:
                _LOGGER.debug("Possible meter reset or rollback detected; recalculating from new base.")
                # Optionally reset the cost if you determine it's a complete reset
                # self._state = 0  # Uncomment this if you need to reset the state
            else:
                _LOGGER.debug("No previous energy reading available; initializing with current reading.")

            self._last_energy_reading = current_energy  # Always update the last reading

            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.exception("Failed to update energy costs due to an error: %s", e)


# Define sensor classes for each interval
class DailyEnergyCostSensor(BaseEnergyCostSensor):
    def __init__(self, hass: HomeAssistant, energy_sensor_id: str, price_sensor_id: str) -> None:
        super().__init__(hass, energy_sensor_id, price_sensor_id, "daily")


class MonthlyEnergyCostSensor(BaseEnergyCostSensor):
    def __init__(self, hass: HomeAssistant, energy_sensor_id: str, price_sensor_id: str) -> None:
        super().__init__(hass, energy_sensor_id, price_sensor_id, "monthly")


class YearlyEnergyCostSensor(BaseEnergyCostSensor):
    def __init__(self, hass: HomeAssistant, energy_sensor_id: str, price_sensor_id: str) -> None:
        super().__init__(hass, energy_sensor_id, price_sensor_id, "yearly")


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    energy_sensor_id = config_entry.data.get(ENERGY_SENSOR)
    price_sensor_id = config_entry.data.get(ELECTRICITY_PRICE_SENSOR)
    sensors = [
        DailyEnergyCostSensor(hass, energy_sensor_id, price_sensor_id),
        MonthlyEnergyCostSensor(hass, energy_sensor_id, price_sensor_id),
        YearlyEnergyCostSensor(hass, energy_sensor_id, price_sensor_id),
    ]
    async_add_entities(sensors, True)
