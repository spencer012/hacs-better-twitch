"""Config flow for Twitch."""

from collections.abc import Mapping
import logging
import re
from typing import Any, cast
from urllib.parse import urlparse

from twitchAPI.helper import first
from twitchAPI.object.api import TwitchUser
from twitchAPI.twitch import Twitch
import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_entry_oauth2_flow, selector
from homeassistant.helpers.config_entry_oauth2_flow import (
    LocalOAuth2Implementation,
    OAuth2Session,
    async_get_config_entry_implementation,
)

from .const import (
    CONF_CHANNELS,
    CONF_PRIORITY_CHANNELS,
    DOMAIN,
    LOGGER,
    OAUTH_SCOPES,
)

CHANNEL_PATTERN = re.compile(r"^[a-z0-9_]{3,25}$")


def _normalize_channel(line: str) -> str:
    """Normalize a channel line to a Twitch login."""
    channel = line.strip().removeprefix("@").strip()
    lower_channel = channel.lower()
    if lower_channel.startswith(("http://", "https://", "twitch.tv/", "www.twitch.tv/")):
        parsed = urlparse(
            channel if "://" in lower_channel else f"https://{channel}"
        )
        host = parsed.netloc.lower().removeprefix("www.")
        if host == "twitch.tv":
            channel = parsed.path.strip("/").split("/", 1)[0]

    channel = channel.strip().lower()
    if not CHANNEL_PATTERN.fullmatch(channel):
        raise ValueError(channel)
    return channel


def _parse_channels(channels: str) -> list[str]:
    """Parse a multiline channel list."""
    parsed_channels: list[str] = []
    seen: set[str] = set()

    for line in channels.splitlines():
        if not line.strip():
            continue
        channel = _normalize_channel(line)
        if channel in seen:
            continue
        parsed_channels.append(channel)
        seen.add(channel)

    return parsed_channels


def _format_channels(channels: list[str]) -> str:
    """Format channels for the multiline text field."""
    return "\n".join(channels)


def _find_unwatched_priority_channels(
    channels: list[str], priority_channels: list[str]
) -> list[str]:
    """Return priority channels that are not in the watched channel list."""
    watched_channels = set(channels)
    return [
        channel for channel in priority_channels if channel not in watched_channels
    ]


def _parse_channel_options(
    user_input: dict[str, Any], errors: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Parse channel options and assign validation errors to the right field."""
    try:
        channels = _parse_channels(user_input[CONF_CHANNELS])
    except ValueError as err:
        errors[CONF_CHANNELS] = "invalid_channel"
        raise

    try:
        priority_channels = _parse_channels(user_input.get(CONF_PRIORITY_CHANNELS, ""))
    except ValueError as err:
        errors[CONF_PRIORITY_CHANNELS] = "invalid_channel"
        raise

    return channels, priority_channels


async def _async_get_twitch_client(
    hass: HomeAssistant,
    entry_or_flow: ConfigEntry | OAuth2FlowHandler,
    data: dict[str, Any],
) -> Twitch:
    """Create an authenticated Twitch client for validation."""
    implementation = cast(
        LocalOAuth2Implementation,
        entry_or_flow.flow_impl
        if isinstance(entry_or_flow, OAuth2FlowHandler)
        else await async_get_config_entry_implementation(hass, entry_or_flow),
    )
    client = Twitch(
        app_id=implementation.client_id,
        authenticate_app=False,
    )
    client.auto_refresh_auth = False
    await client.set_user_authentication(
        data[CONF_TOKEN][CONF_ACCESS_TOKEN], scope=OAUTH_SCOPES
    )
    return client


async def _async_validate_channels(
    client: Twitch, channels: list[str]
) -> tuple[list[TwitchUser], list[str]]:
    """Validate configured channel logins and return resolved users."""
    if not channels:
        return [], []

    users = [user async for user in client.get_users(logins=channels)]
    found = {user.login.lower() for user in users}
    missing = [channel for channel in channels if channel not in found]
    return users, missing


def _channels_schema(default: str = "", priority_default: str = "") -> vol.Schema:
    """Return the channel editor schema."""
    return vol.Schema(
        {
            vol.Required(CONF_CHANNELS, default=default): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
            vol.Optional(
                CONF_PRIORITY_CHANNELS, default=priority_default
            ): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
        }
    )


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Config flow to handle Twitch OAuth2 authentication."""

    DOMAIN = DOMAIN

    def __init__(self) -> None:
        """Initialize flow."""
        super().__init__()
        self._oauth_data: dict[str, Any] = {}
        self._title: str = ""

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlowHandler:
        """Create the options flow."""
        return OptionsFlowHandler()

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Extra data that needs to be appended to the authorize url."""
        return {"scope": " ".join([scope.value for scope in OAUTH_SCOPES])}

    async def async_oauth_create_entry(
        self,
        data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Handle the OAuth callback."""
        client = await _async_get_twitch_client(self.hass, self, data)
        user = await first(client.get_users())
        assert user

        user_id = user.id

        await self.async_set_unique_id(user_id)
        if self.source != SOURCE_REAUTH:
            self._abort_if_unique_id_configured()
            self._oauth_data = data
            self._title = user.display_name
            return await self.async_step_channels()

        reauth_entry = self._get_reauth_entry()
        self._abort_if_unique_id_mismatch(
            reason="wrong_account",
            description_placeholders={
                "title": reauth_entry.title,
                "username": str(reauth_entry.unique_id),
            },
        )

        return self.async_update_reload_and_abort(
            reauth_entry,
            data=data,
            options=reauth_entry.options,
        )

    async def async_step_channels(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure tracked Twitch channels."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}

        if user_input is not None:
            try:
                channels, priority_channels = _parse_channel_options(
                    user_input, errors
                )
            except ValueError as err:
                description_placeholders["channel"] = str(err)
            else:
                unwatched_priority_channels = _find_unwatched_priority_channels(
                    channels, priority_channels
                )
                if unwatched_priority_channels:
                    errors[CONF_PRIORITY_CHANNELS] = "unwatched_priority_channels"
                    description_placeholders["channels"] = ", ".join(
                        unwatched_priority_channels
                    )
                else:
                    client = await _async_get_twitch_client(
                        self.hass, self, self._oauth_data
                    )
                    _, missing = await _async_validate_channels(client, channels)
                    if missing:
                        errors[CONF_CHANNELS] = "unknown_channels"
                        description_placeholders["channels"] = ", ".join(missing)
                    else:
                        return self.async_create_entry(
                            title=self._title,
                            data=self._oauth_data,
                            options={
                                CONF_CHANNELS: channels,
                                CONF_PRIORITY_CHANNELS: priority_channels,
                            },
                        )

        return self.async_show_form(
            step_id="channels",
            data_schema=_channels_schema(),
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Perform reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauth dialog."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()


class OptionsFlowHandler(OptionsFlowWithReload):
    """Twitch options flow handler."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage tracked channels."""
        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}

        if user_input is not None:
            try:
                channels, priority_channels = _parse_channel_options(
                    user_input, errors
                )
            except ValueError as err:
                description_placeholders["channel"] = str(err)
            else:
                unwatched_priority_channels = _find_unwatched_priority_channels(
                    channels, priority_channels
                )
                if unwatched_priority_channels:
                    errors[CONF_PRIORITY_CHANNELS] = "unwatched_priority_channels"
                    description_placeholders["channels"] = ", ".join(
                        unwatched_priority_channels
                    )
                else:
                    session = OAuth2Session(
                        self.hass,
                        self.config_entry,
                        cast(
                            LocalOAuth2Implementation,
                            await async_get_config_entry_implementation(
                                self.hass, self.config_entry
                            ),
                        ),
                    )
                    await session.async_ensure_token_valid()
                    client = await _async_get_twitch_client(
                        self.hass, self.config_entry, {CONF_TOKEN: session.token}
                    )
                    _, missing = await _async_validate_channels(client, channels)
                    if missing:
                        errors[CONF_CHANNELS] = "unknown_channels"
                        description_placeholders["channels"] = ", ".join(missing)
                    else:
                        return self.async_create_entry(
                            title=self.config_entry.title,
                            data={
                                CONF_CHANNELS: channels,
                                CONF_PRIORITY_CHANNELS: priority_channels,
                            },
                        )

        current_channels = cast(
            list[str], self.config_entry.options.get(CONF_CHANNELS, [])
        )
        current_priority_channels = cast(
            list[str], self.config_entry.options.get(CONF_PRIORITY_CHANNELS, [])
        )
        return self.async_show_form(
            step_id="init",
            data_schema=_channels_schema(
                _format_channels(current_channels),
                _format_channels(current_priority_channels),
            ),
            errors=errors,
            description_placeholders=description_placeholders,
        )
