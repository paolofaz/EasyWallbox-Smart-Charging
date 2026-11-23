"""Run the beta on an isolated Home Assistant Core with synthetic ESPHome inputs.

Run separately from unittest discovery since the offline suite stubs HA imports.
Requires Home Assistant 2026.11.1. Everything lives in a temporary config dir.
"""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from homeassistant import bootstrap, loader
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
from homeassistant.core_config import async_process_ha_core_config
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er


async def wait_for(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.025)


async def trial(root):
    component = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"
    custom = root / "custom_components"
    custom.mkdir()
    (custom / component.name).symlink_to(component)
    hass = HomeAssistant(str(root))
    loader.async_setup(hass)
    hass.config.skip_pip = True
    hass.config_entries = ConfigEntries(hass, {})
    await hass.config.async_set_time_zone("Europe/Rome")
    await loader.async_get_custom_components(hass)
    assert await bootstrap.async_load_base_functionality(hass)
    # earlier versions depends on HTTP/WebSocket: build the authentic HA auth manager.
    await async_process_ha_core_config(hass, {})
    await hass.config_entries.async_initialize()
    await hass.async_start()
    try:
        await exercise(hass, root)
    finally:
        await hass.async_stop()


async def exercise(hass, root):
    from custom_components.easywallbox_smart.const import WALLBOX_ENTITIES
    reg = er.async_get(hass)
    station = ConfigEntry(domain="esphome", title="Isolated station", data={}, options={},
                          source="user", version=1, minor_version=1, unique_id="fixture",
                          discovery_keys={}, subentries_data=())
    # Register a real HA device without starting an ESPHome connection.
    with patch.object(hass.config_entries, "async_setup", AsyncMock(return_value=True)):
        await hass.config_entries.async_add(station)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=station.entry_id, identifiers={("esphome", "fixture")})
    cfg = dict(house_power_sources=["sensor.trial_house"], ev_power="sensor.trial_ev",
               expected_dpm_kw=4.4, base_kw=4.)
    for key, domain in WALLBOX_ENTITIES.items():
        item = reg.async_get_or_create(domain, "esphome", key, config_entry=station,
                                       device_id=device.id, suggested_object_id="trial_" + key)
        cfg[key] = item.entity_id
    # Optional existing AD Charge State on the SAME ESPHome device.
    state_item = reg.async_get_or_create(
        "sensor", "esphome", "charge_state",
        config_entry=station, device_id=device.id,
        suggested_object_id="trial_charge_state")
    cfg["charge_state"] = state_item.entity_id
    # Native ESPHome counters are optional but selected together for archive.
    for role in ("session_energy", "session_duration"):
        item = reg.async_get_or_create(
            "sensor", "esphome", role, config_entry=station,
            device_id=device.id, suggested_object_id="trial_" + role)
        cfg[role] = item.entity_id
    calls = []
    hass.bus.async_listen(EVENT_CALL_SERVICE, lambda event: calls.append(event.data))
    def publish(entity, value, **attributes):
        hass.states.async_set(entity, str(value), attributes)
    def kw(entity, value, **attributes):
        publish(entity, value, unit_of_measurement="kW", **attributes)

    publish(cfg["ble_connected"], "off")
    # Firmware invalidates AD flags while BLE is disconnected.
    publish(cfg["wallbox_connected"], "unavailable")
    flow = hass.config_entries.flow
    result = await flow.async_init("easywallbox_smart", context={"source": "user"})
    assert result["step_id"] == "user", result
    result = await flow.async_configure(result["flow_id"], cfg)
    assert result["step_id"] == "vehicle", result
    car = dict(name="Test EV", cable="binary_sensor.trial_car", soc="sensor.trial_soc",
               capacity_kwh=50, efficiency=.9, stop_at_target=True, departure_weekday="07:00",
               departure_weekend="08:00", add_another=False)
    result = await flow.async_configure(result["flow_id"], car)
    assert result["step_id"] == "target_method", result
    result = await flow.async_configure(result["flow_id"], {"next_step_id": "target_fixed"})
    result = await flow.async_configure(result["flow_id"], {"target_fixed": 85})
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state == ConfigEntryState.LOADED
    c = hass.data["easywallbox_smart"][entry.entry_id]
    session_power_entity = reg.async_get_entity_id(
        "number", "easywallbox_smart", entry.entry_id + "_session_power")
    assert session_power_entity, "session-power NumberEntity was not registered"
    assert hass.states.get(session_power_entity).state == "unavailable"
    assert c._timer_unsub is None and c._connected_unsub is None
    assert hass.services.has_service("easywallbox_smart", "prune_session_history")
    from custom_components.easywallbox_smart.session_api import ws_sessions
    class WSProbe:
        result = None
        error = None
        def send_result(self, msg_id, result):
            self.result = result
        def send_error(self, msg_id, code, message):
            self.error = (code, message)
    probe = WSProbe()
    ws_sessions(hass, probe, {"id": 42, "type": "easywallbox_smart/sessions",
                             "entry_id": entry.entry_id, "offset": 0, "limit": 20})
    await hass.async_block_till_done()
    assert probe.error is None, probe.error
    assert probe.result["count"] == 0, probe.result
    assert c.session_history.enabled
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.frontend import async_panel_exists
    from custom_components.easywallbox_smart.lovelace_resources import (
        async_register_card_resource, RESOURCE_URL, RESOURCE_PATH)
    lovelace = hass.data[LOVELACE_DATA]
    history_path = "easywallbox-history-" + entry.entry_id[:16]
    assert not async_panel_exists(hass, history_path)
    assert history_path not in lovelace.dashboards
    await lovelace.resources.async_get_info()
    matching = [r for r in lovelace.resources.async_items()
                if r.get("url", "").split("?", 1)[0] == RESOURCE_PATH]
    assert len(matching) == 1 and matching[0]["url"] == RESOURCE_URL, matching
    # A second setup is idempotent; old earlier versions resource URL is upgraded in place.
    await async_register_card_resource(hass)
    matching = [r for r in lovelace.resources.async_items()
                if r.get("url", "").split("?", 1)[0] == RESOURCE_PATH]
    assert len(matching) == 1
    await lovelace.resources.async_update_item(
        matching[0]["id"], {"url": RESOURCE_PATH + "?v=0.0.0-legacy",
                            "res_type": "module"})
    await async_register_card_resource(hass)
    matching = [r for r in lovelace.resources.async_items()
                if r.get("url", "").split("?", 1)[0] == RESOURCE_PATH]
    assert len(matching) == 1 and matching[0]["url"] == RESOURCE_URL
    folder = root / "easywallbox_smart/decision_logs"
    assert not folder.exists()

    sent = []
    @callback
    def station_number(call):
        value=float(call.data["value"])
        sent.append(value)
        kw(cfg["requested_limit"], value, min=1.4, max=6.0, step=.2)
        kw(cfg["confirmed_limit"], value)

    @callback
    def station_stop(call):
        publish(cfg["start_stop_switch"], "off")
        kw(cfg["dpm_confirmed"], 0)
        publish(cfg["wallbox_charging"], "off")
        publish(cfg["charge_state"], "Pause" if hass.states.get(cfg["wallbox_connected"]).state == "on" else "Cable Unplugged")
        kw("sensor.trial_ev", 0)
        # Hardware observation from the 500e: cloud cable becomes OFF
        # under DPM0 even though the wallbox physical cable remains ON.
        if hass.states.get(cfg["wallbox_connected"]).state == "on":
            publish(car["cable"], "off")

    @callback
    def station_start(call):
        publish(cfg["start_stop_switch"], "on")
        kw(cfg["dpm_confirmed"], 4.4)
        if hass.states.get(cfg["wallbox_connected"]).state == "on":
            publish(cfg["wallbox_charging"], "on")
            publish(cfg["charge_state"], "Charging")
            kw("sensor.trial_ev", 3.3)
        else:
            publish(cfg["wallbox_charging"], "off")
            publish(cfg["charge_state"], "Cable Unplugged")
            kw("sensor.trial_ev", 0)

    hass.services.async_register("number", "set_value", station_number)
    hass.services.async_register("switch", "turn_off", station_stop)
    hass.services.async_register("switch", "turn_on", station_start)

    kw("sensor.trial_ev", 0)
    kw("sensor.trial_house", .2)
    publish(car["cable"], "off")
    publish(car["soc"], 65)
    publish(cfg["ble_connected"], "on")
    await hass.async_block_till_done()
    publish(cfg["wallbox_connected"], "off")
    kw(cfg["requested_limit"], 3.6, min=1.4, max=6.0, step=.2)
    kw(cfg["confirmed_limit"], 3.6)
    kw(cfg["dpm_confirmed"], 4.4)
    publish(cfg["charge_state"], "Cable Unplugged")
    publish(cfg["start_stop_switch"], "on")
    publish(cfg["wallbox_charging"], "off")
    await hass.async_block_till_done()
    assert not any(x["domain"]=="switch" for x in calls), calls

    # Ordinary plugging: the wallbox starts the charge BEFORE cloud identity.
    publish(cfg["wallbox_connected"], "on")
    publish(cfg["charge_state"], "Charging")
    publish(cfg["wallbox_charging"], "on")
    kw("sensor.trial_ev", 3.3)
    await hass.async_block_till_done()
    assert not any(x["domain"]=="switch" for x in calls)
    publish(car["cable"], "on")
    await hass.async_block_till_done()
    await wait_for(lambda: hass.states.get(session_power_entity) is not None
                   and hass.states.get(session_power_entity).state != "unavailable", 8)
    power_ui = hass.states.get(session_power_entity)
    assert float(power_ui.state) == 4.0, power_ui
    assert float(power_ui.attributes["min"]) == 1.4
    assert float(power_ui.attributes["max"]) == 6.0
    assert float(power_ui.attributes["step"]) == 0.2
    await wait_for(lambda: c._refresh_issued, 25)
    publish(car["soc"], 66)
    await wait_for(lambda: c.charging_verified is True and
                   c._pending is None and sent == [4.0], 12)
    assert not any(x["domain"]=="switch" for x in calls)

    # Fiat SOC stop is still mandatory when explicitly opted in at 85%.
    publish(car["soc"], 85)
    await wait_for(lambda: c._soc_stop_latch is not None and
                   c._pending is None, 8)
    assert c._soc_stop_latch["target"] == 85
    assert [x["service"] for x in calls if x["domain"]=="switch"]==["turn_off"]

    # 85% -> 90% must restart even though Fiat cloud cable is OFF.
    assert hass.states.get(cfg["wallbox_connected"]).state=="on"
    assert hass.states.get(car["cable"]).state=="off"
    await c.async_set_fixed_target(car["cable"], 90)
    await wait_for(lambda: c._soc_stop_latch is None and
                   c._pending is None and
                   sum(x["domain"]=="switch" and x["service"]=="turn_on"
                       for x in calls)==1, 8)

    # The cloud catches up only AFTER electrical release.
    publish(car["cable"], "on")
    await hass.async_block_till_done()
    # At the new 90% limit, stop again. Unplugging restores ON for next use.
    publish(car["soc"], 90)
    await wait_for(lambda: c._soc_stop_latch is not None and
                   c._soc_stop_latch.get("target")==90 and
                   c._pending is None, 8)
    publish(cfg["wallbox_charging"], "off")
    kw("sensor.trial_ev", 0)
    publish(car["cable"], "off")
    publish(cfg["charge_state"], "Cable Unplugged")
    publish(cfg["wallbox_connected"], "off")
    await hass.async_block_till_done()
    # Advance the verified state-3 hold without a real-world two-minute sleep.
    assert c._unplug_since is not None
    from datetime import datetime, timedelta, timezone
    c._unplug_since = datetime.now(timezone.utc)-timedelta(seconds=111)
    publish(cfg["charge_state"], "Cable Unplugged")  # New AD report
    c.refresh()
    await wait_for(lambda: c.status=="Scollegata" and
                   c._soc_stop_latch is None and c._pending is None and
                   sum(x["domain"]=="switch" and x["service"]=="turn_on"
                       for x in calls)==2, 8)

    # Delay is available ONLY before plugging. Unlike earlier versions, the action is
    # explicit and does not depend on a Fiat/Kia cloud cable report.
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
    clock=(local+timedelta(hours=1)).time().replace(second=0,microsecond=0)
    await c.async_change("time",clock)
    await c.async_change("delay",True)
    await wait_for(lambda: c._pending is None and
                   c.delay_enabled and c._dpm_lease is not None, 8)
    assert c._setting("dpm_confirmed", datetime.now(timezone.utc))==0

    # The 500e cable cloud sensor remains OFF under DPM0. User cancellation
    # must still restore ON without identifying the car in the cloud.
    publish(cfg["wallbox_connected"], "on")
    publish(cfg["charge_state"], "Vehicle ready")
    publish(car["cable"], "off")
    await hass.async_block_till_done()
    await c.async_change("delay",False)
    await wait_for(lambda: c._pending is None and
                   not c.delay_enabled and c._saved_delay_lease is None and
                   sum(x["domain"]=="switch" and x["service"]=="turn_on"
                       for x in calls)==3, 8)

    await c._journal.async_flush()
    rows=[json.loads(line) for file in sorted(folder.glob("*.jsonl"))
          for line in file.read_text().splitlines()]
    assert any(x["event"]=="session_open" for x in rows)
    assert any(x["event"]=="session_close" for x in rows)
    asserted=[(x["domain"],x["service"]) for x in calls
              if x["domain"] in ("number","switch")]
    assert asserted==[
        ("number","set_value"),("switch","turn_off"),("switch","turn_on"),
        ("switch","turn_off"),("switch","turn_on"),
        ("switch","turn_off"),("switch","turn_on")], asserted
    assert [x["kind"] for x in rows if x["event"]=="confirmed"]==[
        "power","soc_stop","soc_resume","soc_stop","normalize_on",
        "delay_arm","delay_release"]

    options = hass.config_entries.options
    result = await options.async_init(entry.entry_id)
    result = await options.async_configure(result["flow_id"], {"next_step_id": "wallbox"})
    assert result["step_id"] == "wallbox"
    result = await options.async_configure(result["flow_id"], cfg)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id)
    print("HA earlier versions field trial passed: natural start, SOC85 stop, target90 resume, unplug ON, preplug OFF/cancel ON, reload")


if __name__ == "__main__":
    with TemporaryDirectory() as temp:
        asyncio.run(trial(Path(temp)))
