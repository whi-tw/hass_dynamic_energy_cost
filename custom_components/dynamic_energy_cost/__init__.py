import logging

from awesomeversion.awesomeversion import AwesomeVersion
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION  # noqa
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    ELECTRICITY_PRICE_SENSOR,
    ENERGY_SENSOR,
    MIN_HA_VERSION,
    POWER_SENSOR,
)

__all__ = ["ELECTRICITY_PRICE_SENSOR", "ENERGY_SENSOR", "POWER_SENSOR"]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, _: ConfigType) -> bool:
    """Set up the Dynamic Energy Cost component."""
    if AwesomeVersion(HA_VERSION) < AwesomeVersion(MIN_HA_VERSION):  # pragma: no cover
        msg = (
            "This integration requires at least HomeAssistant version "
            f" {MIN_HA_VERSION}, you are running version {HA_VERSION}."
            " Please upgrade HomeAssistant to continue use this integration."
        )
        _notify_message(hass, "inv_ha_version", "PowerCalc", msg)
        _LOGGER.critical(msg)
        return False

    _LOGGER.debug("Global setup of Dynamic Energy Cost component initiated.")
    hass.data[DOMAIN] = {}
    _LOGGER.debug("Dynamic Energy Cost component data storage initialized.")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dynamic Energy Cost from a config entry."""
    _LOGGER.info(
        "Starting setup of Dynamic Energy Cost component, entry.data: %s",
        entry.data,
    )

    try:
        _LOGGER.debug(
            "Attempting to forward Dynamic Energy Cost entry setup to the sensor platform.",
        )
        setup_result = await hass.config_entries.async_forward_entry_setup(
            entry,
            "sensor",
        )
        _LOGGER.debug("Forwarding to sensor setup was successful: %s", setup_result)
    except Exception as e:
        _LOGGER.error("Failed to set up sensor platform, error: %s", str(e))
        return False

    _LOGGER.info("Dynamic Energy Cost setup completed successfully.")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Dynamic Energy Cost config entry."""
    _LOGGER.debug("Attempting to unload the Dynamic Energy Cost component.")
    try:
        unload_ok = await hass.config_entries.async_forward_entry_unload(
            entry,
            "sensor",
        )
        _LOGGER.debug("Unloading was successful: %s", unload_ok)
        return unload_ok
    except Exception as e:
        _LOGGER.error("Failed to unload sensor platform, error: %s", str(e))
        return False


def _notify_message(
    hass: HomeAssistant,
    notification_id: str,
    title: str,
    message: str,
) -> None:  # pragma: no cover
    """Notify user with persistent notification."""
    hass.async_create_task(
        hass.services.async_call(
            domain="persistent_notification",
            service="create",
            service_data={
                "title": title,
                "message": message,
                "notification_id": f"{DOMAIN}.{notification_id}",
            },
        ),
    )
