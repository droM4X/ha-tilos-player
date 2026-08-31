"""Config flow to set up the Tilos Radio Player integration."""

from __future__ import annotations

from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_LOOKBACK_DAYS,
    CONF_MEDIA_PLAYER,
    DEFAULT_LOOKBACK_DAYS,
    DOMAIN,
    MAX_LOOKBACK_DAYS,
    MIN_LOOKBACK_DAYS,
)


class TilosConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Tilos Radio Player."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Tilos Rádió", data=user_input
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_MEDIA_PLAYER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
                vol.Optional(
                    CONF_LOOKBACK_DAYS, default=DEFAULT_LOOKBACK_DAYS
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_LOOKBACK_DAYS,
                        max=MAX_LOOKBACK_DAYS,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> TilosOptionsFlow:
        """Create the options flow handler."""
        return TilosOptionsFlow()


class TilosOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Tilos Radio Player."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_player = self.config_entry.data.get(CONF_MEDIA_PLAYER)
        current_days = self.config_entry.data.get(
            CONF_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_MEDIA_PLAYER, default=current_player): (
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="media_player")
                    )
                ),
                vol.Optional(CONF_LOOKBACK_DAYS, default=current_days): (
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_LOOKBACK_DAYS,
                            max=MAX_LOOKBACK_DAYS,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
