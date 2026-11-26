# EasyWallbox Smart Charging

[![Release](https://img.shields.io/github/v/release/paolofaz/EasyWallbox-Smart-Charging)](https://github.com/paolofaz/EasyWallbox-Smart-Charging/releases/latest)

**Stable Home Assistant release. Requires EasyWallbox ESPHome firmware with cumulative counters for history tracking.**

This integration handles charging scheduling and *slow* EV current limit stabilization through the entities provided by the EasyWallbox ESPHome firmware. It does **not** replace the **wallbox's built-in DPM (Dynamic Power Management)**, which must remain active and continues to handle electrical spikes and safety protections.

## Maintenance update (v1.0.1)

Diagnostic decision logs retain 90 calendar days; the charging history is unaffected. Runtime labels and imports have been cleaned up without changing the charging policy.

## Architecture

- **ESPHome + BLE**: Reads and confirms wallbox registers and states, executes requested commands, accumulates energy and minutes for the physical connection, and determines when the session closes.
- **Home Assistant / EasyWallbox Smart Charging**: Identifies the vehicle, reads SOC and schedules, calculates power margins, makes decisions, and sends commands only after required verification checks. Archives absolute ESPHome totals without summing them a second time.
- **Three Shelly EM sensors** in the reference setup: two legs for household consumption and one dedicated leg for the wallbox. Only household consumption (excluding the EV) is used for policy decisions.
- **The wallbox with active DPM** remains the sole fast current controller. A BLE command, a switch state, or an ACK alone does not prove actual delivered power.

ESPHome Firmware: https://github.com/paolofaz/Easywallbox---Esphome. This is a separate project and does not modify the firmware.

No additional Docker containers, external scripts, solar/PV logic, dynamic tariffs, or AI-based decisions.

## Installation and Updating

Requires **Home Assistant 2026.11.0 or later** (quality gate on **2026.11.1**) and an already working EasyWallbox ESPHome setup. Install via HACS/Marketplace as a custom repository from this repo, or copy `custom_components/easywallbox_smart` into `config/custom_components/` and restart HA.

Open *Settings → Devices & services → Add integration → EasyWallbox Smart Charging* and complete the UI config flow. For existing installations, use **Configure** (Options).

**Installation and upgrade from earlier versions:** First, update ESPHome to the version featuring cumulative counters and the 60 s / 5 min fallback ([reference firmware](https://github.com/paolofaz/Easywallbox---Esphome/blob/main/wallbox.yaml)).

### Required Entities

Select the seven mandatory entities belonging to the **same** ESPHome wallbox: Connection BLE, Car Connected, Charging, Start-Stop, Charge power, Power set, and **Charge Enabled**. A numeric DPM reading is **not** required. Specify the **Contracted power limit** (e.g., 4.4 kW) purely as a mathematical reference, the default EV power, the Shelly sources for household consumption **excluding the EV**, and the separate EV Shelly sensor. The actual hardware DPM can be configured separately in the firmware (e.g., 4.6 kW): this custom integration neither changes nor resets it. Any Start-Stop action triggered by Smart Charging simply pauses charging to 0 A or restores the last positive value managed by ESPHome. Optional sources are available for Charge State, Session Energy, Session Duration, and a physical power relay.

Configure one or more vehicle profiles with cable sensor, SOC, battery capacity, AC charging efficiency, weekday/weekend schedules, and target SOC (from an entity or fixed value). You can optionally select a vehicle data refresh button and enable Stop SOC managed by this integration. Reference setup vehicles: Fiat 500e and Kia EV3.

### Avoiding Conflicting Commands

Before installing, disable any existing automations or scripts that control the wallbox.

## How It Works

- **Automatic**: Reads physical state, vehicle data, and Shelly sensors; calculates the margin until departure time; under verified conditions, can reduce the EV limit using a slow, anti-oscillation policy.
- **Manual**: Automatic management hands control of the session over to the user until physical disconnection.
- **Delayed Start**: Must be configured before plugging in the car, if desired; uses the existing DPM0 pause mechanism. It does not automatically advance the chosen start time.
- **Desired Session Power**: Slider matching the min/max/step exposed by ESPHome. Setting this preference does not equal a written command or measured power.
- **Target SOC**: A fixed target or an HA entity, with Stop SOC active only for enabled vehicles and subject to independent confirmations.
- **HA and BLE Restarts**: Verifies session evidence and the previously confirmed limit without blindly repeating commands. If it cannot safely reconcile a `LIMITED` state or an override, it blocks new commands. Normal unlocking occurs after a confirmed physical disconnection; there is no dedicated UI switch to force-unlock it.

The supervisor does not chase power spikes second-by-second. A `LIMITED` state can return to `NORMAL` after 15 *observed* minutes of nominal headroom, or in case of urgency when actual power headroom is available. The quiet-state condition is currently `contractual power - home - baseline ≥ −0.02 kW`; this is **subject to validation against real-world data** and should not be preemptively altered.

### ETA: End-of-Charge Prediction (Informational Only)

This prediction **does not drive Start-Stop, DPM, or NORMAL/LIMITED states**: the conservative margin for departure time continues to be calculated as before.

Version 1.0.0 adopts a **two-regime prediction model:**

- **Reference Free Power**: Median of at least 20 independent EV readings (at least 10 minutes) within the current session, with household consumption ≤ 0.3 kW and the EV limit actually at `NORMAL`. If this data is unavailable, it temporarily falls back to the lesser of 96% of desired power or contractual power minus 0.2 kW. This fallback is *not* a measurement.
- **Current Power**: Average of EV Shelly measurements over the last 10 minutes, including any observed DPM pauses. This estimate applies only to the next **30 minutes**; the remaining energy is projected using the reference free power. Running an oven right now is not projected across the entire night.
- **Remaining Energy**: Vehicle profile capacity/efficiency minus AC Shelly energy observed since the last SOC update. Within the same session, after at least **5 percentage points of SOC increase** without Shelly data gaps, the kWh/% coefficient can be adjusted with progressive weighting up to ±15%. It is not permanently learned from a single charging session.
- **Stability**: The displayed ETA updates in 10-minute blocks and normally does not shift by more than 15 minutes per update. Explicitly changing the vehicle, target SOC, or desired power starts a new prediction.
- **Transparency**: The Estimated Charge End sensor reports its quality (*provisional/consolidated*), reference free power, recent power, and a *theoretical* completion time at free power. These are calculation references, not guarantees. If SOC is missing, inconsistent, or stale, the prediction remains unavailable.

The model has no knowledge of future usage of ovens, dishwashers, or other appliances: the initial hours in particular can exhibit significant errors. No false "maximum time" or uncalibrated statistical range is shown. More real-world sessions are needed to validate accuracy and evaluate potential persistent learning.

## User Interface

Available entities include status indicators, scheduler/alerts, identified vehicle, stabilizer phase, energy and completion estimates, mode selector, schedules, session power slider, and (where configured) SOC slider. Shelly current/power sensors and BLE states are not duplicated. The Lovelace session history card is automatically registered as a resource; the integration **does not create a dashboard**.

To display the charging history, add a manual card to your Lovelace dashboard using the following YAML:

```yaml
type: custom:easywallbox-session-history-card
```

### Charging History — ESPHome Cumulative Counters

The card displays one row per completed session with columns: **Charge End, Vehicle, Energy, Duration** (hours/minutes). It updates via WebSocket at most every 30 seconds while the page is open, or on demand via Refresh, with no additional BLE polling.

- ESPHome accumulates actual kWh and minutes in the two public sensors `Session Energy` and `Session Duration`, preserving them across pauses.
- Home Assistant saves the last absolute value of each cumulative counter during the active session. It does not reconstruct resets, sum deltas, or run a secondary timer.
- The first verified physical disconnection stores the timestamp and totals, without creating a history row yet. Plugging back in before the counters reset continues the same session.
- The row is archived once both ESPHome cumulative counters reach zero following an observed disconnection. The firmware resets them after at least 60 seconds of confirmed disconnection, or after 5 minutes without telemetry if disconnection was already confirmed. The reset can arrive while BLE is offline; a BLE drop alone does not close the session. An isolated zero reading neither closes nor deletes the snapshot.
- Latest values and any pending disconnection are persisted alongside the history. The timestamp shown in the table reflects the observed disconnection; the reset time is stored separately. Valid completed rows from previous versions are preserved. Rows with less than 0.2 kWh or 2 minutes are not recorded.
- If session continuity cannot be proven (e.g., BLE drop, restart, or anomalous counter regression), the row quality is flagged as `partial_observed`; if the vehicle cannot be identified, it displays "Unidentified".

The log records `archive_configured_at_start`, the archive state at disconnection, and `firmware_session_closed` when both counters reset to zero. Missing the entire closure window (e.g., HA offline from disconnection until a new charging session begins) can make the session unrecoverable: the firmware does not publish a persistent session ID or a history of closed sessions. Missing totals are never fabricated.

A previous-limit warning displays the **last confirmed value**, not a live reading: always verify the actual ESPHome value and Shelly measurements before taking manual action.

## Diagnostic Journal — Optional via Integration Options

Under **Settings → Devices & services → EasyWallbox Smart Charging → Configure → Diagnostic Journal**, you can enable the **"Write decision journal to disk"** flag.

- **Enabled by default** during testing; can be disabled at any time.
- When enabled, writes daily JSONL files to `/config/easywallbox_smart/decision_logs/decisions_YYYY-MM-DD.jsonl`, recording events, decisions, requested commands, confirmations, and reasoning. The diagnostic journal retains the current day and the previous 89 days; older dated journal files are removed when logging next runs. The charging session archive is unaffected.
- When disabled, **no new events are logged**; saving the option reloads the integration. Existing files are not deleted, and any events currently being written may finish flushing during the reload.
- The journal uses a bounded queue, serialized writes, and restrictive local file permissions. It triggers no extra BLE reads or commands. Avoid sharing these logs publicly, as they may contain timestamps, identifiers, and usage data.

# 🍺 Support the Project

If you found this project useful and want to support my work, you can offer me a beer:

[![Buy Me a Beer](https://img.shields.io/badge/Buy%20Me%20a%20Beer-0070ba?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/PaoloFazari)

[License](LICENSE)
