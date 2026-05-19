"""Constants for the Twitch integration."""

import logging

from twitchAPI.twitch import AuthScope

from homeassistant.const import Platform

LOGGER = logging.getLogger(__package__)

PLATFORMS = [Platform.SENSOR]

OAUTH2_AUTHORIZE = "https://id.twitch.tv/oauth2/authorize"
OAUTH2_TOKEN = "https://id.twitch.tv/oauth2/token"

DOMAIN = "twitch"
CONF_CHANNELS = "channels"
CONF_PRIORITY_CHANNELS = "priority_channels"

OAUTH_SCOPES = [AuthScope.USER_READ_SUBSCRIPTIONS, AuthScope.USER_READ_FOLLOWS]
