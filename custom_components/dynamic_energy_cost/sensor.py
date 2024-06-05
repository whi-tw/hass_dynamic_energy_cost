import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)

from .const import (
    ELECTRICITY_PRICE_SENSOR,
    ENERGY_SENSOR,
    POWER_SENSOR,
    SERVICE_RESET_COST,
)
from .energy_based_sensors import (
    DailyEnergyCostSensor,
    MonthlyEnergyCostSensor,
    YearlyEnergyCostSensor,
)
from .power_based_sensors import RealTimeCostSensor, UtilityMeterSensor

_LOGGER = logging.getLogger(__name__)


async def register_entity_services(_: HomeAssistant) -> None:
    """Register custom services for energy cost sensors."""
    platform = async_get_current_platform()

    platform.async_register_entity_service(
        SERVICE_RESET_COST,
        {},  # No parameters for the service
        "async_reset",
    )


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Setup sensor platform based on user configuration."""
    data = config_entry.data
    electricity_price_sensor = data[ELECTRICITY_PRICE_SENSOR]
    sensors = []

    if data.get(POWER_SENSOR):
        # Setup power-based sensors
        power_sensor = data[POWER_SENSOR]
        real_time_cost_sensor = RealTimeCostSensor(
            hass,
            config_entry,
            electricity_price_sensor,
            power_sensor,
            "Real Time Energy Cost",
        )
        sensors.append(real_time_cost_sensor)
        intervals = ["daily", "monthly", "yearly"]
        utility_sensors = [UtilityMeterSensor(hass, real_time_cost_sensor, interval) for interval in intervals]
        sensors.extend(utility_sensors)

    if data.get(ENERGY_SENSOR):
        # Setup energy-based sensors
        energy_sensor = data[ENERGY_SENSOR]
        sensors.append(DailyEnergyCostSensor(hass, energy_sensor, electricity_price_sensor))
        sensors.append(MonthlyEnergyCostSensor(hass, energy_sensor, electricity_price_sensor))
        sensors.append(YearlyEnergyCostSensor(hass, energy_sensor, electricity_price_sensor))

    if sensors:
        async_add_entities(sensors, True)
    else:
        _LOGGER.error("No sensors configured. Check your configuration.")

    await register_entity_services(hass)
