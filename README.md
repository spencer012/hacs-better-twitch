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

## Application Credentials

This integration uses Twitch OAuth through Home Assistant application credentials. Create Twitch developer credentials and add them in Home Assistant under **Settings > Devices & services > Application Credentials** if prompted.

## Notes

This custom integration uses the `twitch` domain, so Home Assistant loads it instead of the built-in Twitch integration when installed under `custom_components/twitch`. Remove it from HACS/custom components and restart Home Assistant to return to the built-in integration.
