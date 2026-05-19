"""Define a class to manage fetching Twitch data."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.helper import first
from twitchAPI.object.api import FollowedChannel, Stream, TwitchUser, UserSubscription
from twitchAPI.twitch import Twitch
from twitchAPI.type import (
    EventSubSubscriptionConflict,
    EventSubSubscriptionError,
    EventSubSubscriptionTimeout,
    TwitchAPIException,
    TwitchBackendException,
    TwitchResourceNotFound,
    UnauthorizedException,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CHANNELS,
    CONF_PRIORITY_CHANNELS,
    DOMAIN,
    LOGGER,
    OAUTH_SCOPES,
)

type TwitchConfigEntry = ConfigEntry[TwitchCoordinator]

EVENTSUB_EXCEPTIONS = (
    EventSubSubscriptionConflict,
    EventSubSubscriptionError,
    EventSubSubscriptionTimeout,
    TwitchBackendException,
    UnauthorizedException,
)
EVENTSUB_MAX_TOTAL_COST = 10
EVENTSUB_STREAM_SUBSCRIPTIONS_PER_CHANNEL = 2
EVENTSUB_MAX_STREAM_CHANNELS = (
    EVENTSUB_MAX_TOTAL_COST // EVENTSUB_STREAM_SUBSCRIPTIONS_PER_CHANNEL
)


def chunk_list[T](items: list[T], chunk_size: int) -> list[list[T]]:
    """Split a list into chunks of chunk_size."""
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


@dataclass
class TwitchUpdate:
    """Class for holding Twitch data."""

    name: str
    followers: int
    is_streaming: bool
    game: str | None
    title: str | None
    started_at: datetime | None
    stream_picture: str | None
    picture: str
    subscribed: bool | None
    subscription_gifted: bool | None
    subscription_tier: int | None
    follows: bool
    following_since: datetime | None
    viewers: int | None


class TwitchCoordinator(DataUpdateCoordinator[dict[str, TwitchUpdate]]):
    """Class to manage fetching Twitch data."""

    config_entry: TwitchConfigEntry
    current_user: TwitchUser
    users: dict[str, TwitchUser]

    def __init__(
        self,
        hass: HomeAssistant,
        twitch: Twitch,
        session: OAuth2Session,
        entry: TwitchConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self.twitch = twitch
        self.session = session
        self.eventsub: EventSubWebsocket | None = None
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=1),
            config_entry=entry,
        )

    async def _async_setup(self) -> None:
        """Resolve configured channel logins."""
        channels = self.config_entry.options.get(CONF_CHANNELS, [])
        self.users = {}

        for chunk in chunk_list(channels, 100):
            async for channel in self.twitch.get_users(logins=chunk):
                self.users[channel.id] = channel

        if not (user := await first(self.twitch.get_users())):
            raise UpdateFailed("Logged in user not found")
        self.current_user = user
        self.users[self.current_user.id] = self.current_user

    async def _async_set_user_authentication(self) -> None:
        """Refresh and apply the current user authentication."""
        await self.session.async_ensure_token_valid()
        await self.twitch.set_user_authentication(
            self.session.token["access_token"],
            OAUTH_SCOPES,
            self.session.token["refresh_token"],
            False,
        )

    async def _async_update_data(self) -> dict[str, TwitchUpdate]:
        """Update all configured channel data."""
        await self._async_set_user_authentication()

        streams: dict[str, Stream] = {}
        user_ids = list(self.users)
        for chunk in chunk_list(user_ids, 100):
            async for stream in self.twitch.get_streams(
                first=len(chunk), user_id=chunk
            ):
                streams[stream.user_id] = stream

        updates = await asyncio.gather(
            *(
                self._async_build_channel_update(channel, streams.get(channel_id))
                for channel_id, channel in self.users.items()
            )
        )
        return dict(zip(self.users, updates, strict=True))

    async def async_refresh_channel(self, channel_id: str) -> None:
        """Refresh a single channel after a stream event."""
        channel = self.users.get(channel_id)
        if channel is None:
            return

        await self._async_set_user_authentication()
        stream = await first(
            self.twitch.get_streams(first=1, user_id=[channel_id])
        )
        data = dict(self.data or {})
        data[channel_id] = await self._async_build_channel_update(channel, stream)
        self.async_set_updated_data(data)

    async def _async_build_channel_update(
        self, channel: TwitchUser, stream: Stream | None
    ) -> TwitchUpdate:
        """Build one channel update."""
        followers, follow, sub = await asyncio.gather(
            self.twitch.get_channel_followers(channel.id),
            self._async_get_follow(channel.id),
            self._async_get_subscription(channel),
        )

        return TwitchUpdate(
            channel.display_name,
            followers.total,
            bool(stream),
            stream.game_name if stream else None,
            stream.title if stream else None,
            stream.started_at if stream else None,
            stream.thumbnail_url.format(width="", height="") if stream else None,
            channel.profile_image_url,
            bool(sub),
            sub.is_gift if sub else None,
            {"1000": 1, "2000": 2, "3000": 3}.get(sub.tier) if sub else None,
            bool(follow),
            follow.followed_at if follow else None,
            stream.viewer_count if stream else None,
        )

    async def _async_get_follow(self, channel_id: str) -> FollowedChannel | None:
        """Return the current user's follow relationship for one channel."""
        return await first(
            await self.twitch.get_followed_channels(
                user_id=self.current_user.id,
                broadcaster_id=channel_id,
                first=1,
            )
        )

    async def _async_get_subscription(
        self, channel: TwitchUser
    ) -> UserSubscription | None:
        """Return the current user's subscription for one channel."""
        try:
            return await self.twitch.check_user_subscription(
                user_id=self.current_user.id, broadcaster_id=channel.id
            )
        except TwitchResourceNotFound:
            LOGGER.debug("User is not subscribed to %s", channel.display_name)
        except TwitchAPIException as exc:
            LOGGER.error("Error response on check_user_subscription: %s", exc)
        return None

    async def async_start_eventsub(self) -> None:
        """Start EventSub websocket subscriptions for stream status changes."""
        if self.eventsub is not None:
            return

        eventsub = EventSubWebsocket(self.twitch)
        try:
            await self.hass.async_add_executor_job(eventsub.start)
            subscribed_channels = 0
            skipped_channels: list[str] = []
            for channel_id, channel in self._ordered_eventsub_users():
                if subscribed_channels >= EVENTSUB_MAX_STREAM_CHANNELS:
                    skipped_channels.append(channel.display_name)
                    continue

                online_topic_id = await eventsub.listen_stream_online(
                    channel_id, self._async_stream_event_callback(channel_id, True)
                )
                try:
                    await eventsub.listen_stream_offline(
                        channel_id,
                        self._async_stream_event_callback(channel_id, False),
                    )
                except EVENTSUB_EXCEPTIONS:
                    await eventsub.unsubscribe_topic(online_topic_id)
                    raise
                subscribed_channels += 1
        except EVENTSUB_EXCEPTIONS as exc:
            LOGGER.warning("Could not start Twitch EventSub websocket: %s", exc)
            await self._async_stop_eventsub(eventsub)
            return

        if skipped_channels:
            LOGGER.warning(
                "Skipped Twitch EventSub websocket subscriptions for %s because "
                "Twitch limits websocket subscription cost; these channels will "
                "update on the regular polling interval",
                ", ".join(skipped_channels),
            )

        self.eventsub = eventsub

    def _ordered_eventsub_users(self) -> list[tuple[str, TwitchUser]]:
        """Return users with configured priority channels first."""
        priority_channels = self.config_entry.options.get(CONF_PRIORITY_CHANNELS, [])
        channel_ids_by_login = {
            channel.login.lower(): channel_id
            for channel_id, channel in self.users.items()
        }
        priority_channel_ids = [
            channel_ids_by_login[channel]
            for channel in priority_channels
            if channel in channel_ids_by_login
        ]

        ordered_channel_ids = priority_channel_ids + [
            channel_id
            for channel_id in self.users
            if channel_id not in priority_channel_ids
        ]
        return [
            (channel_id, self.users[channel_id]) for channel_id in ordered_channel_ids
        ]

    def _async_stream_event_callback(
        self, channel_id: str, is_streaming: bool
    ) -> Callable[[Any], Awaitable[None]]:
        """Return an EventSub callback for one channel."""

        async def _async_handle_stream_event(_: Any) -> None:
            self.hass.add_job(
                self.async_handle_stream_event(channel_id, is_streaming)
            )

        return _async_handle_stream_event

    async def async_handle_stream_event(
        self, channel_id: str, is_streaming: bool
    ) -> None:
        """Apply an EventSub stream state immediately and refresh metadata later."""
        current_data = self.data or {}
        current = current_data.get(channel_id)
        if current is None:
            return

        updated = replace(
            current,
            is_streaming=is_streaming,
            game=current.game if is_streaming else None,
            title=current.title if is_streaming else None,
            started_at=current.started_at if is_streaming else None,
            stream_picture=(
                current.stream_picture or current.picture if is_streaming else None
            ),
            viewers=current.viewers if is_streaming else None,
        )
        self.async_set_updated_data({**current_data, channel_id: updated})

        if is_streaming:
            await asyncio.sleep(15)
        await self.async_refresh_channel(channel_id)

    async def async_shutdown(self) -> None:
        """Stop background resources."""
        if self.eventsub is None:
            return

        eventsub = self.eventsub
        self.eventsub = None
        await self._async_stop_eventsub(eventsub)

    async def _async_stop_eventsub(self, eventsub: EventSubWebsocket) -> None:
        """Stop EventSub if it is currently running."""
        with suppress(RuntimeError):
            await eventsub.stop()
