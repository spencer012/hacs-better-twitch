# Better Twitch

Better Twitch is a Home Assistant custom integration that replaces the built-in Twitch integration with faster online/offline detection and a simpler way to manage channels.

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=spencer012&repository=hacs-better-twitch&category=integration)

## Features

- Faster stream online/offline updates.
- Channel management through a large multi-line text box.
- One Twitch channel login or URL per line.
- Home Assistant config flow and options flow support.

## Installation with HACS

Use the quick install link above, or add the repository manually:

1. In Home Assistant, open HACS.
2. Go to **Integrations**.
3. Open the three-dot menu and choose **Custom repositories**.
4. Add `https://github.com/spencer012/hacs-better-twitch`.
5. Select **Integration** as the category.
6. Install **Better Twitch**.
7. Restart Home Assistant.

After restart, add the Twitch integration from **Settings > Devices & services**. If you already use Twitch, open the integration options to edit channels in the multi-line channel box.

## Migration from Built-in Twitch

Better Twitch uses the same `twitch` domain as the built-in integration, so it can be installed as a drop-in replacement.

If you already have Twitch sensors, they should continue to work after installing this integration and restarting Home Assistant. To remove old channel sensors, open the Twitch integration options and remove those channels from the channel list. The old sensor entities can only be deleted after their channels are no longer configured.

If you previously disabled old Twitch entities, re-enable them first. After they are enabled, Home Assistant should show the entity delete button. If the delete button still is not available, restart Home Assistant again and check the entity after startup.

Watching too many channels at one time can trigger websocket errors during setup or updates. If that happens, reduce the channel list and restart Home assistant.

## Application Credentials

This integration uses Twitch OAuth through Home Assistant application credentials. Create Twitch developer credentials and add them in Home Assistant under **Settings > Devices & services > Application Credentials** if prompted.

## Log Warnings

This integration uses a websocket connection for faster online/offline detection. Home Assistant may log `asyncio` warnings about request handler or Twitch config entry tasks taking a fraction of a second, especially during startup:

```text
WARNING (MainThread) [asyncio] Executing <Task pending name='Task-145' coro=<RequestHandler._handle_request() ...> took 0.117 seconds
WARNING (MainThread) [asyncio] Executing <Task pending name='config entry setup ... twitch ...> took 0.104 seconds
```

These warnings are expected from the websocket implementation. If they are noisy, add filters like this to your Home Assistant `configuration.yaml`:

```yaml
logger:
  filters:
    asyncio:
      - "Executing <Task .*RequestHandler\\._handle_request\\(\\).* took .* seconds"
      - "Executing <Task .*config entry setup .* twitch .* took .* seconds"
```

## Notes

This custom integration uses the `twitch` domain, so Home Assistant loads it instead of the built-in Twitch integration when installed under `custom_components/twitch`. Remove it from HACS/custom components and restart Home Assistant to return to the built-in integration.
