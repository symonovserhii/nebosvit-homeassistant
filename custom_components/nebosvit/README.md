# Nebosvit — Home Assistant integration

Air raid alerts and hourly outage schedules for Ukraine, read from the
Nebosvit server (`/v1/snapshot`, `/v1/power`). It does not call alerts.in.ua
or ukrainealarm.com directly, so no third-party token is needed in Home Assistant.

## Install
Copy `custom_components/nebosvit` into your HA `config/custom_components/`
(or add this repository to HACS as a custom repository), restart HA, then
*Settings → Devices & services → Add integration → Nebosvit*.

Pick the server (default `https://alarm-api.symonov.com`), an optional app
key, an oblast, then the whole oblast, a raion or a hromada. Optionally pick an
outage zone and queue.

## Entities (per watched place)
| Entity | Values |
|---|---|
| `binary_sensor.<place>_alert_active` | on while any alert concerns the place (its own, a parent's or one inside it) |
| `sensor.<place>_alert_level` | `clear` / `yellow` / `red` |
| `sensor.<place>_threat_type` | `none`, `air`, `artillery`, `urban_fights`, `chemical`, `nuclear`, `unknown` (attributes: all types, threats) |
| `sensor.<place>_alert_since` | timestamp of the earliest matching alert |
| `sensor.<place>_power_schedule` | `on` / `off` / `maybe_off` / `unknown`, **according to the published schedule, not a live measurement** |
| `sensor.<place>_next_power_change` | timestamp |

If the server has no alert source the alert entities become unavailable
rather than showing "all clear".

Polling: alerts every 30 s (ETag, the server answers 304 when nothing changed),
schedules every 5 min.
