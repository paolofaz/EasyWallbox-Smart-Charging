"""beta controller smoke tests with a fake Home Assistant (NO hardware)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import importlib.util
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]/"custom_components/easywallbox_smart"
VERSION=json.loads((ROOT/"manifest.json").read_text())["version"]
if "homeassistant" not in sys.modules:
    ha=types.ModuleType("homeassistant")
    core=types.ModuleType("homeassistant.core")
    core.HomeAssistant=type("HomeAssistant",(),{})
    core.callback=lambda fn: fn
    helpers=types.ModuleType("homeassistant.helpers")
    event=types.ModuleType("homeassistant.helpers.event")
    event.async_track_point_in_utc_time=lambda hass,fn,when: lambda: None
    event.async_track_state_change_event=lambda hass,ids,fn: lambda: None
    storage=types.ModuleType("homeassistant.helpers.storage")
    class Store:
        def __init__(self,hass,version,key):
            self.content={}
        async def async_load(self):
            return {}
        async def async_save(self,data):
            self.content=data
    storage.Store=Store
    sys.modules.update({"homeassistant":ha,"homeassistant.core":core,
                        "homeassistant.helpers":helpers,
                        "homeassistant.helpers.event":event,
                        "homeassistant.helpers.storage":storage})

package=types.ModuleType("easywallbox_test_package")
package.__path__=[str(ROOT)]
sys.modules["easywallbox_test_package"]=package

def load(name):
    path=ROOT/(name+".py")
    spec=importlib.util.spec_from_file_location("easywallbox_test_package."+name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module

const=load("const")
sources=load("sources")
policy=load("power_policy")
controller=load("controller")


class FakeState:
    def __init__(self,value,unit=None):
        self.state=str(value)
        self.attributes={} if unit is None else {"unit_of_measurement":unit}
        self.last_updated=datetime.now(timezone.utc)
        self.last_reported=self.last_updated
        self.last_changed=self.last_updated

    def publish(self,value):
        if self.state != str(value):
            self.last_changed=datetime.now(timezone.utc)
        self.state=str(value)
        self.last_reported=self.last_updated=datetime.now(timezone.utc)


class FakeServices:
    def __init__(self):
        self.calls=[]
    async def async_call(self,domain,service,args,blocking=False):
        self.calls.append((domain,service,dict(args),blocking))


class FakeHass:
    def __init__(self,workdir):
        self.states={}
        self.services=FakeServices()
        self.config=types.SimpleNamespace(
            time_zone="Europe/Rome",path=lambda *p: str(Path(workdir).joinpath(*p)))
    async def async_add_executor_job(self,fn,*args):
        return fn(*args)


class FakeEntry:
    entry_id="mock_rc_test"
    options={}
    def __init__(self,data):
        self.data=data
    def async_create_background_task(self,hass,coro,name):
        return asyncio.create_task(coro,name=name)


def setup(hass,*,cable=True,charging=True,soc="75",home=".1",old_limit=4.0):
    C=const
    config={
        C.CONF_HOUSE_SOURCES:["sensor.floor_a","sensor.floor_b"],
        C.CONF_EV_POWER:"sensor.ev",
        C.CONF_BLE_CONNECTED:"binary_sensor.ble_connection",
        C.CONF_WALLBOX_CONNECTED:"binary_sensor.wallbox_cable",
        C.CONF_WALLBOX_CHARGING:"binary_sensor.wallbox_charging",
        C.CONF_CHARGE_STATE:"sensor.wallbox_charge_state",
        C.CONF_TELEMETRY_FRESH:"binary_sensor.fresh",
        C.CONF_DPM_ACTIVE:"binary_sensor.dpm_active",
        C.CONF_WALLBOX_FAULT:"binary_sensor.fault",
        C.CONF_CHARGE_ENABLED:"binary_sensor.charge_enabled",
        C.CONF_START_STOP:"switch.wallbox_start_stop",
        C.CONF_COMMAND_STATUS:"sensor.command_status",
        C.CONF_REQUESTED_LIMIT:"number.charge_power",
        C.CONF_CONFIRMED_LIMIT:"sensor.power_set",
        C.CONF_DPM_CONFIRMED:"sensor.dpm_set",
        C.CONF_WALLBOX_REFRESH:"button.wallbox_refresh",
        C.CONF_EXPECTED_DPM:4.4,
        C.CONF_BASE_KW:4.0,
        C.CONF_LEGACY_DISABLED:True,
        C.CONF_VEHICLES:[
            {C.CONF_NAME:"Fiat",C.CONF_CABLE:"binary_sensor.fiat",
             C.CONF_SOC:"sensor.fiat_soc",C.CONF_VEHICLE_REFRESH:"button.fiat_update",
             C.CONF_TARGET_FIXED:80,
             C.CONF_CAPACITY:42,C.CONF_EFFICIENCY:.9,
             C.CONF_DEPARTURE_WEEKDAY:"07:00",C.CONF_DEPARTURE_WEEKEND:"08:00",
             },
            {C.CONF_NAME:"Kia",C.CONF_CABLE:"binary_sensor.kia",
             C.CONF_SOC:"sensor.kia_soc",C.CONF_VEHICLE_REFRESH:"button.kia_update",
             C.CONF_TARGET_FIXED:80,
             C.CONF_CAPACITY:77,C.CONF_EFFICIENCY:.9,
             C.CONF_DEPARTURE_WEEKDAY:"07:00",C.CONF_DEPARTURE_WEEKEND:"08:00",
             },
        ],
    }
    values={
        "binary_sensor.ble_connection":("on",None),
        "sensor.floor_a":(home,"kW"),
        "sensor.floor_b":("0.1","kW"),
        "sensor.ev":("3.2" if charging else "0","kW"),
        "binary_sensor.wallbox_cable":("on" if cable else "off",None),
        "binary_sensor.wallbox_charging":("on" if charging else "off",None),
        "sensor.wallbox_charge_state":("Charging" if charging else
                                       "Vehicle ready" if cable else "Cable Unplugged",None),
        "binary_sensor.fresh":("on",None),
        "binary_sensor.dpm_active":("on",None),
        "binary_sensor.fault":("off",None),
        "binary_sensor.charge_enabled":("on",None),
        "switch.wallbox_start_stop":("on",None),
        "sensor.command_status":("Idle",None),
        "number.charge_power":(str(old_limit),"kW"),
        "sensor.power_set":(str(old_limit),"kW"),
        "sensor.dpm_set":("4.4","kW"),
        "button.wallbox_refresh":("unknown",None),
        "button.fiat_update":("unknown",None),
        "button.kia_update":("unknown",None),
        "binary_sensor.fiat":("on" if cable else "off",None),
        "binary_sensor.kia":("off",None),
        "sensor.fiat_soc":(soc,None),
        "sensor.kia_soc":("40",None),
    }
    for eid,(v,unit) in values.items():
        hass.states[eid]=FakeState(v,unit)
    hass.states["number.charge_power"].attributes.update(min=1.4, max=6.0, step=.2)
    # Simulate the existing Charge State entity being reported by the same
    # physical AD update as Car Connected, not a new sensor or BLE command.
    cable_state = hass.states["binary_sensor.wallbox_cable"]
    publish_cable = cable_state.publish
    def report_cable(value):
        publish_cable(value)
        if str(value) in ("off", "False", "false"):
            hass.states["sensor.wallbox_charge_state"].publish("Cable Unplugged")
        elif str(value) in ("on", "True", "true"):
            hass.states["sensor.wallbox_charge_state"].publish("Vehicle ready")
    cable_state.publish = report_cable
    return config


class RCAdapterSmoke(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory()
        self.hass=FakeHass(self.tmp.name)
        cfg=setup(self.hass)
        self.c=controller.ChargingController(self.hass,FakeEntry(cfg), VERSION)
        await self.c.async_load()
        # Exercise each electrical path independently in legacy smoke tests:
        # production automatic-on-boot is verified in a dedicated test.
        self.c.real_enabled = False
        self.c.start()
        # Prior baseline tests exercise the ACTUATION layer, so bypass only
        # their separate simulated 20s cloud-refresh delay. Dedicated tests
        # below verify the delay and refresh logic.
        self.c._refresh_due = None
        self.c._refresh_issued = True
        self.c._refresh_requested_at = None
        self.c._connect_since = datetime.now(timezone.utc)-timedelta(minutes=1)

    async def asyncTearDown(self):
        await self.c.async_close()
        self.tmp.cleanup()

    async def settle(self):
        await asyncio.sleep(.05)

    async def test_legacy_smoke_fixture_starts_unarmed_for_isolated_commands(self):
        self.assertFalse(self.c.real_enabled)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

    async def test_production_boot_activates_automatic_control_without_extra_flag(self):
        cfg=setup(self.hass)
        cfg.pop(const.CONF_LEGACY_DISABLED,None)
        entry=FakeEntry(cfg)
        c=controller.ChargingController(self.hass,entry, VERSION)
        await c.async_load()
        self.assertTrue(c.real_enabled)
        self.assertIsNone(c._blocked)
        # No hardware write until a live connected charging snapshot is
        # deliberately evaluated and conditions are fulfilled.
        await c.async_close()

    async def test_disconnected_never_commands_even_when_auto(self):
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

    async def test_manual_no_commands_ever(self):
        await self.c.async_change("mode","manual")
        with self.assertRaises(ValueError):
            await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

    async def test_charging_only_issues_number_command(self):
        self.hass.states["number.charge_power"].publish("3.6")
        self.hass.states["sensor.power_set"].publish("3.6")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(len(self.hass.services.calls),1)
        domain,service,args,blocking=self.hass.services.calls[0]
        self.assertEqual((domain,service),("number","set_value"))
        self.assertEqual(args["entity_id"],"number.charge_power")
        self.assertTrue(blocking)
        self.assertEqual(args["value"],4.0)

    async def test_user_explicit_delay_arms_only_before_car_plugged(self):
        local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        future=(local+timedelta(hours=1)).time().replace(second=0,microsecond=0)
        await self.c.async_change("time",future)
        await self.c.async_change("real",True)
        with self.assertRaisesRegex(ValueError,"prima di collegare"):
            await self.c.async_change("delay",True)
        self.assertFalse(self.c.delay_enabled)
        self.assertEqual(self.hass.services.calls,[])
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        await self.c.async_change("delay",True)
        self.assertEqual([x[:2] for x in self.hass.services.calls],
                         [("switch","turn_off")])
        self.assertEqual(self.c._pending.kind,"delay_arm")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.c.refresh()
        self.assertIsNone(self.c._pending)
        self.assertEqual(self.c._dpm_lease,4.4)
        self.assertTrue(self.c.delay_enabled)
    async def test_invalid_twenty_three_hour_delay_does_not_change_switch_or_charge(self):
        local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        old=(local-timedelta(hours=1)).time().replace(second=0,microsecond=0)
        await self.c.async_change("time",old)
        await self.c.async_change("real",True)
        with self.assertRaisesRegex(ValueError,"within_12_hours"):
            await self.c.async_change("delay",True)
        await self.settle()
        self.assertFalse(self.c.delay_enabled)
        self.assertFalse(any(c[0]=="switch" for c in self.hass.services.calls))

    async def test_delay_switch_clears_only_after_verified_dpm_release(self):
        await self.c.async_change("real",True)
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        await self.c.async_change("time",(local+timedelta(hours=1)).time().replace(second=0,microsecond=0))
        await self.c.async_change("delay",True)
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.c.refresh()
        self.assertTrue(self.c.delay_enabled)
        self.c._scheduled_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        self.c._saved_delay_lease["start"]=self.c._scheduled_at.isoformat()
        self.c.refresh()
        await self.settle()
        self.assertEqual(self.c._pending.kind,"delay_release")
        self.assertTrue(self.c.delay_enabled)
        self.hass.states["sensor.dpm_set"].publish("4.4")
        self.hass.states["switch.wallbox_start_stop"].publish("on")
        self.c.refresh()
        self.assertFalse(self.c.delay_enabled)
        self.assertIsNone(self.c._pending)
    async def test_unplug_does_not_cancel_explicit_preplug_delay(self):
        await self.c.async_change("real",True)
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        await self.c.async_change("time",(local+timedelta(hours=1)).time().replace(second=0,microsecond=0))
        await self.c.async_change("delay",True)
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.c.refresh()
        self.hass.states["binary_sensor.wallbox_cable"].publish("on")
        self.c.refresh()
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.c.refresh()
        self.assertTrue(self.c.delay_enabled)
        self.assertIsNotNone(self.c._saved_delay_lease)
    async def test_manual_to_auto_does_not_off_if_charging_is_idle(self):
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        await self.c.async_change("mode","manual")
        await self.c.async_change("mode","automatic")
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])
    async def test_delay_rejected_even_when_car_plugged_but_not_charging(self):
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        await self.c.async_change("real",True)
        local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        await self.c.async_change("time",(local+timedelta(hours=2)).time().replace(second=0,microsecond=0))
        with self.assertRaises(ValueError):
            await self.c.async_change("delay",True)
        self.assertFalse(self.c.delay_enabled)
        self.assertEqual(self.hass.services.calls,[])
    async def test_missing_dpm_readback_blocks_real_command(self):
        self.hass.states["sensor.dpm_set"].publish("unavailable")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

    async def test_charge_state_error_blocks_real_command(self):
        await self.c.async_change("real",True)
        self.hass.states["sensor.wallbox_charge_state"].publish("Error")
        self.c.refresh()
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

    async def test_ambiguous_two_cables_block_all(self):
        self.hass.states["binary_sensor.kia"].publish("on")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

    async def test_one_shot_command_without_ble_ack_stays_pending(self):
        self.hass.states["number.charge_power"].publish("3.6")
        self.hass.states["sensor.power_set"].publish("3.6")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.c.refresh()
        await self.settle()
        self.assertEqual(len(self.hass.services.calls),1)
        self.assertIsNotNone(self.c._pending)

    async def test_target_reached_while_still_charging_restores_only_owned_cap(self):
        self.hass.states["number.charge_power"].publish("2.8")
        self.hass.states["sensor.power_set"].publish("2.8")
        self.hass.states["sensor.fiat_soc"].publish("80")
        self.c.refresh()
        self.c._power_state=policy.State(
            session_id=self.c._session_id, phase="LIMITED",
            kind="strong", cap_kw=2.8, baseline_kw=4.0)
        self.c._owned_limit=2.8
        await self.c.async_change("real",True)
        await self.settle()
        calls=self.hass.services.calls
        self.assertEqual(len(calls),1)
        self.assertEqual((calls[0][0],calls[0][1],calls[0][2]["value"]),
                         ("number","set_value",4.0))

    async def test_stopped_at_target_does_not_modify_ev_number(self):
        self.hass.states["number.charge_power"].publish("2.8")
        self.hass.states["sensor.power_set"].publish("2.8")
        self.hass.states["sensor.fiat_soc"].publish("80")
        self.hass.states["sensor.ev"].publish("0")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.c.refresh()
        self.c._power_state=policy.State(
            session_id=self.c._session_id, phase="LIMITED",
            kind="strong", cap_kw=2.8, baseline_kw=4.0)
        self.c._owned_limit=2.8
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])
        self.assertIn("limite da verificare",self.c.status)

    async def test_cancel_verified_preplug_delay_restores_dpm_once(self):
        self.hass.states["sensor.ev"].publish("0")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.c._scheduled_at=datetime.now(timezone.utc)+timedelta(hours=1)
        self.c.delay_enabled=True
        self.c._saved_delay_lease={"kind":"preplug","start":self.c._scheduled_at.isoformat(),"dpm":4.4}
        self.c._dpm_lease=4.4
        self.c._idle_park_trace="test-preplug-lease"
        await self.c.async_change("real",True)
        await self.c.async_change("delay",False)
        await self.settle()
        self.assertEqual([x[:2] for x in self.hass.services.calls],[("switch","turn_on")])
        self.assertEqual(self.c._pending.kind,"delay_release")
        self.hass.states["sensor.dpm_set"].publish("4.4")
        self.hass.states["switch.wallbox_start_stop"].publish("on")
        self.c.refresh()
        self.assertIsNone(self.c._pending)
        self.assertFalse(self.c.delay_enabled)
        self.assertIsNone(self.c._saved_delay_lease)
    async def test_verified_power_status_updates_owned_limit_no_repeat(self):
        self.hass.states["number.charge_power"].publish("3.6")
        self.hass.states["sensor.power_set"].publish("3.6")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(len(self.hass.services.calls),1)
        self.hass.states["number.charge_power"].publish("4.0")
        self.hass.states["sensor.power_set"].publish("4.0")
        self.hass.states["sensor.command_status"].publish("Verified charge power")
        self.c.refresh()
        await self.settle()
        self.assertIsNone(self.c._pending)
        self.assertEqual(self.c._owned_limit,4.0)
        self.assertEqual(len(self.hass.services.calls),1)

    async def test_dpm_zero_with_connected_car_never_auto_restarts(self):
        self.hass.states["sensor.ev"].publish("0")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["sensor.fiat_soc"].publish("70")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(self.hass.services.calls, [])
        self.assertIsNone(self.c._pending)
    async def test_manual_mode_is_displayed_as_manual_not_blocked(self):
        await self.c.async_change("mode","manual")
        self.assertEqual(self.c.status,"Manuale")
        self.assertFalse(self.c.real_enabled)

    async def test_confirmed_unplug_does_not_issue_off_and_retains_normal_dpm(self):
        await self.c.async_change("real",True)
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])
        self.assertIsNone(self.c._pending)
        self.assertIsNone(self.c._connected_unsub)
    async def test_unknown_charge_rate_respects_later_preferred_start(self):
        now=datetime.now(timezone.utc)
        self.c.delay_enabled=True
        self.c.charge_now=False
        self.c.planning_rate_kw=None
        self.c.remaining_kwh=5.0
        self.c.departure=now+timedelta(hours=9)
        self.c._scheduled_at=now+timedelta(hours=3)
        self.c._connect_since=now
        self.assertFalse(self.c._safe_start_due(now+timedelta(minutes=20)))
        self.assertTrue(self.c._safe_start_due(now+timedelta(hours=3)))

    async def test_options_vehicle_profiles_are_used_after_reload(self):
        cfg=setup(self.hass)
        updated=dict(cfg[const.CONF_VEHICLES][0],
                     name="Fiat aggiornata",soc="sensor.updated_soc")
        added={
            const.CONF_NAME:"Terza", const.CONF_CABLE:"binary_sensor.third",
            const.CONF_SOC:"sensor.third_soc",const.CONF_CAPACITY:60,
            const.CONF_EFFICIENCY:.9,const.CONF_TARGET_FIXED:80,
            const.CONF_DEPARTURE_WEEKDAY:"06:00",
            const.CONF_DEPARTURE_WEEKEND:"08:00",
        }
        entry=FakeEntry(cfg)
        entry.options={const.CONF_VEHICLES:
                       [updated,cfg[const.CONF_VEHICLES][1],added]}
        c=controller.ChargingController(self.hass,entry, VERSION)
        await c.async_load()
        self.assertEqual(len(c.cfg[const.CONF_VEHICLES]),3)
        self.assertEqual(c.cfg[const.CONF_VEHICLES][0]["name"],
                         "Fiat aggiornata")
        self.assertTrue(c.real_enabled)
        await c.async_close()

    def enable_soc_stop_on_fiat(self, source_timestamp=True):
        car=self.c.cfg[const.CONF_VEHICLES][0]
        car[const.CONF_STOP_AT_TARGET]=True
        if source_timestamp:
            car[const.CONF_VEHICLE_LAST_UPDATE]="sensor.fiat_update_time"
            self.hass.states["sensor.fiat_update_time"]=FakeState(
                datetime.now(timezone.utc).isoformat())
        return car

    async def test_opt_in_fiat_soc_stop_waits_for_car_refresh_and_ble_ack(self):
        self.enable_soc_stop_on_fiat()
        self.hass.states["sensor.fiat_soc"].publish("80")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertIn(("button","press"),[c[:2] for c in self.hass.services.calls])
        self.assertFalse(any(c[0]=="switch" for c in self.hass.services.calls))

        # A refreshed SOC and source update timestamp are both required.
        self.hass.states["sensor.fiat_update_time"].publish(
            datetime.now(timezone.utc).isoformat())
        self.hass.states["sensor.fiat_soc"].publish("80")
        self.c.refresh()
        await self.settle()
        stops=[c for c in self.hass.services.calls
               if c[0]=="switch" and c[1]=="turn_off"]
        self.assertEqual(len(stops),1)
        self.assertEqual(self.c._pending.kind,"soc_stop")
        self.c.refresh()
        await self.settle()
        self.assertEqual(len([c for c in self.hass.services.calls
                             if c[0]=="switch"]),1)

        # DPM ACK alone is not physical proof of a stopped charge.
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["sensor.command_status"].publish("Verified DPM")
        self.c.refresh()
        await self.settle()
        self.assertIsNotNone(self.c._pending)
        self.assertFalse(self.c._soc_stop_done)

        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0.01")
        self.c.refresh()
        await self.settle()
        self.assertIsNone(self.c._pending)
        self.assertTrue(self.c._soc_stop_done)
        self.assertIsNone(self.c._dpm_lease)
        self.assertEqual(self.c.status,"Carica terminata — limite SOC raggiunto")
        self.c.refresh()
        await self.settle()
        self.assertEqual(len([c for c in self.hass.services.calls
                             if c[0]=="switch"]),1)

    async def test_soc_stop_disabled_does_not_stop(self):
        self.hass.states["sensor.fiat_soc"].publish("80")
        await self.c.async_change("real",True)
        await self.settle()
        self.assertFalse(any(c[0]=="switch" for c in self.hass.services.calls))

    async def test_kia_reaches_its_own_target_without_wallbox_stop(self):
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.kia"].publish("on")
        self.hass.states["sensor.kia_soc"].publish("80")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertFalse(any(c[0]=="switch" for c in self.hass.services.calls))

    async def test_soc_stop_missing_confirmed_car_timestamp_never_stops(self):
        self.enable_soc_stop_on_fiat()
        self.hass.states["sensor.fiat_soc"].publish("80")
        await self.c.async_change("real",True)
        await self.settle()
        # Timestamp intentionally not changed after update button press.
        self.c.refresh()
        await self.settle()
        self.assertFalse(any(c[0]=="switch" for c in self.hass.services.calls))
        self.assertFalse(self.c._soc_stop_done)

    async def test_soc_stop_never_when_soc_below_near_target_threshold(self):
        self.enable_soc_stop_on_fiat()
        self.hass.states["sensor.fiat_soc"].publish("70")
        await self.c.async_change("real",True)
        await self.settle()
        self.assertFalse(any(c[0]=="button" for c in self.hass.services.calls))
        self.assertFalse(any(c[0]=="switch" for c in self.hass.services.calls))

    async def test_managed_soc_slider_updates_only_target_and_its_store(self):
        car=self.enable_soc_stop_on_fiat(source_timestamp=False)
        self.assertEqual(self.c.fixed_target(car),80)
        await self.c.async_set_fixed_target(car[const.CONF_CABLE],90)
        self.assertEqual(self.c.fixed_target(car),90)
        self.assertEqual(self.c._store.content["fixed_target_overrides"][
            car[const.CONF_CABLE]]["value"],90)
        self.assertFalse(any(c[0]=="switch" for c in self.hass.services.calls))
        with self.assertRaises(ValueError):
            await self.c.async_set_fixed_target(car[const.CONF_CABLE],87)

    async def test_explicit_start_never_anticipated_even_when_target_impossible(self):
        now=datetime.now(timezone.utc)
        self.c.delay_enabled=True
        self.c._scheduled_at=now+timedelta(hours=3)
        self.c.remaining_kwh=12.0
        # Decision margin and latest-start now use independently
        # corrected AC energy; this fixture supplies it explicitly.
        self.c._margin_energy_kwh=12.0
        self.c.planning_rate_kw=2.0
        self.c.departure=now+timedelta(hours=4)
        self.assertLess(self.c._latest_start(now),now)
        self.assertFalse(self.c._safe_start_due(now+timedelta(hours=2)))
        self.assertTrue(self.c._safe_start_due(now+timedelta(hours=3)))

    async def test_time_change_while_preplug_delay_on_rejects_too_long(self):
        local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        future=(local+timedelta(hours=1)).time().replace(second=0,microsecond=0)
        old=(local-timedelta(hours=1)).time().replace(second=0,microsecond=0)
        await self.c.async_change("time",future)
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.c.async_change("delay",True)
        original=self.c._scheduled_at
        with self.assertRaises(ValueError):
            await self.c.async_change("time",old)
        self.assertTrue(self.c.delay_enabled)
        self.assertEqual(self.c._scheduled_at,original)
        self.assertIn("rifiutato",self.c.notice.lower())
    async def test_preplug_delay_requires_online_ble_but_no_car(self):
        local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        clock=(local+timedelta(hours=1)).time().replace(second=0,microsecond=0)
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        await self.c.async_change("time",clock)
        await self.c.async_change("real",True)
        await self.c.async_change("delay",True)
        self.assertTrue(self.c.delay_enabled)
        self.assertEqual(self.c._pending.kind,"delay_arm")
        self.assertEqual([x[:2] for x in self.hass.services.calls],[("switch","turn_off")])
    async def test_ble_off_is_normal_no_command_and_stable_off_is_valid(self):
        self.c.cfg[const.CONF_BLE_CONNECTED]="binary_sensor.ble_connection"
        self.hass.states["binary_sensor.ble_connection"]=FakeState("off")
        self.c.refresh()
        self.assertEqual(self.c.status,"Wallbox non disponibile")
        self.assertEqual(self.hass.services.calls,[])
        self.hass.states["binary_sensor.ble_connection"].publish("on")
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.c.refresh()
        # The same uninterrupted connection and its cable report are both old.
        self.c._ble_since -= timedelta(days=8)
        self.hass.states["binary_sensor.wallbox_cable"].last_reported-=timedelta(days=7)
        self.c.refresh()
        self.assertEqual(self.c._wallbox_cable(datetime.now(timezone.utc)),False)
        self.assertEqual(self.c.status,"Scollegata")

    async def test_auto_ready_by_populates_and_resets_on_disconnection(self):
        self.c.refresh()
        self.assertIsNotNone(self.c.departure)
        default=self.c.departure
        local=default.astimezone(ZoneInfo("Europe/Rome"))
        new=(local+timedelta(hours=1)).time().replace(second=0,microsecond=0)
        await self.c.async_change("ready_by",new)
        self.assertIsNotNone(self.c.departure_override)
        self.assertEqual(self.c.departure_override.date(),local.date())
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        self.assertIsNone(self.c.departure_override)

    async def test_real_control_optin_persists_through_boot_but_not_without_consent(self):
        cfg=setup(self.hass)
        entry=FakeEntry(cfg)
        entry.options={const.CONF_AUTOMATIC_CONTROL_ENABLED: True}
        c=controller.ChargingController(self.hass,entry, VERSION)
        await c.async_load()
        self.assertTrue(c.real_enabled)
        self.assertIsNone(c._blocked)
        await c.async_close()

    async def test_verified_preplug_delay_reconciles_after_ha_reboot(self):
        now=datetime.now(timezone.utc)
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.hass.states["binary_sensor.wallbox_cable"].publish("on")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.c.real_enabled=False
        start=now+timedelta(hours=1)
        saved={"delay":True,"scheduled_at":start.isoformat(),
               "delayed_lease":{"kind":"preplug","start":start.isoformat(),"dpm":4.4}}
        other=controller.ChargingController(self.hass,FakeEntry(self.c.cfg), VERSION)
        other._store.async_load=lambda: asyncio.sleep(0,result=saved)
        await other.async_load()
        other.refresh()
        await self.settle()
        self.assertEqual(other._dpm_lease,4.4)
        self.assertEqual(self.hass.services.calls,[])
        await other.async_close()
    async def test_old_rc4_delay_lease_is_not_adopted_or_released(self):
        now=datetime.now(timezone.utc)
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.real_enabled=False
        other=controller.ChargingController(self.hass,FakeEntry(self.c.cfg),VERSION)
        await other.async_load()
        other.delay_enabled=True
        other._scheduled_at=now-timedelta(seconds=1)
        other._saved_delay_lease={"vehicle":"binary_sensor.fiat",
                                  "start":other._scheduled_at.isoformat(),"dpm":4.4}
        other.refresh()
        await self.settle()
        self.assertIsNone(other._dpm_lease)
        self.assertEqual(self.hass.services.calls,[])
        await other.async_close()
    async def test_refresh_after_twenty_seconds_only_selected_car(self):
        await self.c.async_change("real", True)
        self.c._refresh_due = datetime.now(timezone.utc)-timedelta(seconds=1)
        self.c._refresh_issued = False
        self.c.refresh()
        await self.settle()
        calls = [(d,serv,args["entity_id"]) for d,serv,args,_ in
                 self.hass.services.calls]
        self.assertIn(("button","press","button.fiat_update"),calls)
        self.assertNotIn(("button","press","button.wallbox_refresh"),calls)
        self.assertNotIn(("button","press","button.kia_update"),calls)
        self.c.refresh()
        await self.settle()
        self.assertEqual(sum(d=="button" for d,_,_,_ in self.hass.services.calls),1)

    async def test_refresh_both_when_vehicle_not_yet_identified(self):
        await self.c.async_change("real", True)
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.c._refresh_due = datetime.now(timezone.utc)-timedelta(seconds=1)
        self.c._refresh_issued = False
        self.c.refresh()
        await self.settle()
        entities = [args["entity_id"] for d,serv,args,_ in
                    self.hass.services.calls if d=="button"]
        self.assertIn("button.fiat_update",entities)
        self.assertIn("button.kia_update",entities)

    async def test_legacy_rc_park_flag_has_no_preplug_lease_ownership(self):
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        async def old_storage():
            return {"park_owned":True}
        self.c._store.async_load=old_storage
        await self.c.async_load()
        self.c.refresh()
        await self.settle()
        self.assertIsNone(self.c._dpm_lease)
        self.assertFalse(any(x[:2]==("number","set_value") for x in self.hass.services.calls))
        self.assertFalse(any(x[:2]==("switch","turn_on") for x in self.hass.services.calls))
    async def test_connected_car_cannot_start_based_on_cloud_when_dpm_is_parked(self):
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])
        self.assertIsNone(self.c._pending)
    async def test_manual_to_auto_while_charging_never_toggles_start_stop(self):
        await self.c.async_change("mode", "manual")
        await self.c.async_change("mode", "automatic")
        await self.c.async_change("real", True)
        await self.settle()
        self.assertTrue(self.c.charging_verified)
        self.assertFalse(self.c._park_required)
        self.assertFalse(any(x[0] == "switch" for x in self.hass.services.calls))

    async def test_ble_recovery_during_active_charge_never_stops(self):
        await self.c.async_change("real",True)
        self.hass.states["binary_sensor.ble_connection"].publish("off")
        self.c.refresh()
        self.hass.states["binary_sensor.ble_connection"].publish("on")
        self.hass.states["binary_sensor.wallbox_cable"].publish("on")
        self.hass.states["binary_sensor.wallbox_charging"].publish("on")
        self.hass.states["binary_sensor.fault"].publish("off")
        self.hass.states["sensor.dpm_set"].publish("4.4")
        self.hass.states["sensor.power_set"].publish("4.0")
        self.hass.states["sensor.ev"].publish("3.2")
        self.c.refresh()
        await self.settle()
        self.assertFalse(any(x[:2] == ("switch","turn_off") for x in self.hass.services.calls))

    async def test_ble_recovery_unowned_idle_dpm_zero_respects_manual_pause(self):
        await self.c.async_change("real",True)
        self.hass.states["binary_sensor.ble_connection"].publish("off")
        self.c.refresh()
        self.hass.states["binary_sensor.ble_connection"].publish("on")
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["binary_sensor.fault"].publish("off")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        await self.settle()
        self.assertFalse(any(x[:2] == ("switch","turn_on") for x in self.hass.services.calls))
        self.assertIsNone(self.c._pending)
    async def test_ble_recovery_with_unknown_charging_does_not_stop(self):
        await self.c.async_change("real",True)
        self.hass.states["binary_sensor.ble_connection"].publish("off")
        self.c.refresh()
        self.hass.states["binary_sensor.ble_connection"].publish("on")
        self.hass.states["binary_sensor.wallbox_cable"].publish("on")
        self.hass.states["binary_sensor.wallbox_charging"].publish("unavailable")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

    async def test_soc_target_100_never_stops_but_target_below_100_can(self):
        fiat=self.c.cfg[const.CONF_VEHICLES][0]
        fiat[const.CONF_STOP_AT_TARGET]=True
        fiat[const.CONF_TARGET_FIXED]=100
        self.hass.states["sensor.fiat_soc"].publish("100")
        await self.c.async_change("real",True)
        await self.settle()
        self.assertFalse(any(x[:2] == ("switch","turn_off") for x in self.hass.services.calls))

    async def test_past_departure_survives_ha_restart_with_same_connected_car(self):
        deadline=datetime.now(timezone.utc)-timedelta(minutes=10)
        self.c._active_departure=deadline
        self.c._active_departure_vehicle="binary_sensor.fiat"
        await self.c._save()
        saved=dict(self.c._store.content)
        other=controller.ChargingController(self.hass,FakeEntry(self.c.cfg), VERSION)
        other._store.async_load=lambda: asyncio.sleep(0,result=saved)
        await other.async_load()
        other.real_enabled=False
        other.refresh()
        self.assertEqual(other.departure,deadline)
        self.assertEqual(other._active_departure_vehicle,"binary_sensor.fiat")
        await other.async_close()

    async def test_restored_deadline_is_retired_if_ha_begins_unplugged(self):
        past=datetime.now(timezone.utc)-timedelta(minutes=10)
        saved={"active_departure":past.isoformat(),
               "active_departure_vehicle":"binary_sensor.fiat"}
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        other=controller.ChargingController(self.hass, FakeEntry(self.c.cfg), VERSION)
        other._store.async_load=lambda: asyncio.sleep(0,result=saved)
        await other.async_load()
        other.real_enabled=False
        other.refresh()
        await asyncio.sleep(.05)
        self.assertIsNone(other._active_departure)
        self.assertIsNone(other._store.content.get("active_departure"))
        await other.async_close()

    async def test_soc_target_increase_after_confirmed_stop_restarts_to_90(self):
        car=self.enable_soc_stop_on_fiat(source_timestamp=False)
        cable=car[const.CONF_CABLE]
        # Simulate a previous confirmed DPM0 SOC stop at 85%.
        self.c._soc_stop_latch={"vehicle":cable,"target":85,"soc":85}
        self.c._soc_stop_done=True
        self.c._fixed_target_overrides[cable]={"configured":80,"value":85}
        self.hass.states["sensor.fiat_soc"].publish("85")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.c.async_set_fixed_target(cable,90)
        await self.settle()
        self.assertEqual(self.c._pending.kind,"soc_resume")
        self.assertEqual([x[:2] for x in self.hass.services.calls],
                         [("switch","turn_on")])
        self.hass.states["sensor.dpm_set"].publish("4.4")
        self.hass.states["switch.wallbox_start_stop"].publish("on")
        self.c.refresh()
        self.assertIsNone(self.c._pending)
        self.assertIsNone(self.c._soc_stop_latch)
        self.assertEqual(self.c.fixed_target(car),90)

    async def test_soc_target_reduce_or_equal_after_stop_never_restarts(self):
        car=self.enable_soc_stop_on_fiat(source_timestamp=False)
        cable=car[const.CONF_CABLE]
        self.c._soc_stop_latch={"vehicle":cable,"target":85}
        self.c._soc_stop_done=True
        self.c._fixed_target_overrides[cable]={"configured":80,"value":85}
        self.hass.states["sensor.fiat_soc"].publish("85")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.c.async_set_fixed_target(cable,80)
        await self.settle()
        self.assertIsNone(self.c._pending)
        self.assertEqual(self.hass.services.calls,[])
        await self.c.async_set_fixed_target(cable,90)
        self.hass.states["sensor.fiat_soc"].publish("91")
        self.c.refresh()
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

    async def test_fiat_cloud_cable_off_after_soc_stop_still_allows_target_raise(self):
        car=self.enable_soc_stop_on_fiat(source_timestamp=False)
        car[const.CONF_TARGET_FIXED]=85
        self.hass.states["sensor.fiat_soc"].publish("85")
        self.c._soc_stop_refresh_at=datetime.now(timezone.utc)
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(self.c._pending.kind,"soc_stop")
        # Physical wallbox cable stays ON but Fiat cloud now reports OFF.
        marker_before=self.c._continuity_marker(const.CONF_WALLBOX_CONNECTED)
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        self.assertIsNone(self.c._pending)
        self.assertEqual(self.c._soc_stop_latch.get("target"),85)
        self.assertEqual(self.c._soc_stop_latch.get("cable_marker"),marker_before)
        self.assertEqual(self.c._blocked,None)
        await self.c.async_set_fixed_target(car[const.CONF_CABLE],90)
        await self.settle()
        self.assertEqual(self.c._pending.kind,"soc_resume")
        self.assertEqual([x[:2] for x in self.hass.services.calls],
                         [("switch","turn_off"),("switch","turn_on")])

    async def test_stale_soc_after_target_raise_requests_one_cloud_update(self):
        car=self.enable_soc_stop_on_fiat(source_timestamp=False)
        cable=car[const.CONF_CABLE]
        self.c._soc_stop_latch={"vehicle":cable,"target":85}
        self.c._soc_stop_done=True
        self.c._fixed_target_overrides[cable]={"configured":80,"value":85}
        self.hass.states["sensor.fiat_soc"].publish("85")
        self.hass.states["sensor.fiat_soc"].last_reported-=timedelta(minutes=10)
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.c.async_set_fixed_target(cable,90)
        await self.settle()
        self.assertEqual([x[:2] for x in self.hass.services.calls],
                         [("button","press")])
        self.assertIsNone(self.c._pending)
        # Button success is not a new SOC. The provider must report again.
        self.hass.states["sensor.fiat_soc"].publish("85")
        self.c.refresh()
        await self.settle()
        self.assertEqual([x[:2] for x in self.hass.services.calls],
                         [("button","press"),("switch","turn_on")])
        self.assertEqual(self.c._pending.kind,"soc_resume")

    async def test_existing_ha_input_number_target_increase_can_resume(self):
        car=self.enable_soc_stop_on_fiat(source_timestamp=False)
        car[const.CONF_TARGET_ENTITY]="input_number.fiat_target"
        self.hass.states["input_number.fiat_target"]=FakeState("85")
        self.c._soc_stop_latch={"vehicle":car[const.CONF_CABLE],"target":85}
        self.c._soc_stop_done=True
        self.hass.states["sensor.fiat_soc"].publish("85")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        await self.c.async_change("real",True)
        self.hass.states["input_number.fiat_target"].publish("90")
        self.c._on_event(types.SimpleNamespace(data={
            "entity_id":"input_number.fiat_target",
            "old_state":FakeState("85"),
            "new_state":FakeState("90"),
        }))
        await self.settle()
        self.assertEqual([x[:2] for x in self.hass.services.calls],
                         [("switch","turn_on")])
        self.assertEqual(self.c._pending.kind,"soc_resume")

    async def test_lowering_target_during_charging_applies_new_stop_limit(self):
        car=self.enable_soc_stop_on_fiat(source_timestamp=False)
        car[const.CONF_TARGET_FIXED]=90
        self.hass.states["sensor.fiat_soc"].publish("85")
        self.c._soc_stop_refresh_at=datetime.now(timezone.utc)
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertFalse(any(x[:2]==("switch","turn_off") for x in self.hass.services.calls))
        await self.c.async_set_fixed_target(car[const.CONF_CABLE],80)
        await self.settle()
        self.assertEqual([x[:2] for x in self.hass.services.calls],
                         [("switch","turn_off")])
        self.assertEqual(self.c._pending.kind,"soc_stop")

    async def test_soc_stop_latch_survives_reboot_without_automatic_restart(self):
        car=self.enable_soc_stop_on_fiat(source_timestamp=False)
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        storage={"soc_stop_latch":{"vehicle":car[const.CONF_CABLE],"target":85}}
        other=controller.ChargingController(self.hass,FakeEntry(self.c.cfg),VERSION)
        other._store.async_load=lambda: asyncio.sleep(0,result=storage)
        await other.async_load()
        other.refresh()
        await self.settle()
        self.assertTrue(other._soc_stop_done)
        self.assertIsNone(other._pending)
        self.assertEqual(self.hass.services.calls,[])
        await other.async_close()

    async def test_soc_stop_unplug_restores_on_with_confirmed_dpm(self):
        car=self.enable_soc_stop_on_fiat(source_timestamp=False)
        self.c._soc_stop_latch={"vehicle":car[const.CONF_CABLE],"target":85}
        self.c._soc_stop_done=True
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["switch.wallbox_start_stop"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.c.refresh()
        self.assertIsNone(self.c._wallbox_cable(datetime.now(timezone.utc)))
        await self.settle()
        self.assertFalse(any(x[:2]==("switch","turn_on") for x in self.hass.services.calls))
        # Simulate 69 seconds of uninterrupted, fresh state-3 reports.
        self.c._unplug_since = datetime.now(timezone.utc)-timedelta(seconds=70)
        self.hass.states["sensor.wallbox_charge_state"].publish("Cable Unplugged")
        self.c.refresh()
        await self.settle()
        self.assertEqual([x[:2] for x in self.hass.services.calls],
                         [("switch","turn_on")])
        self.assertEqual(self.c._pending.kind,"normalize_on")
        self.hass.states["sensor.dpm_set"].publish("4.4")
        self.hass.states["switch.wallbox_start_stop"].publish("on")
        self.c.refresh()
        self.assertIsNone(self.c._soc_stop_latch)
        self.assertFalse(self.c._soc_stop_done)

    async def test_delay_not_accepted_after_car_is_plugged_even_if_cloud_is_off(self):
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.hass.states["binary_sensor.fiat"].publish("off")
        await self.c.async_change("real",True)
        local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        await self.c.async_change("time",(local+timedelta(hours=1)).time().replace(second=0,microsecond=0))
        with self.assertRaises(ValueError):
            await self.c.async_change("delay",True)
        self.assertEqual(self.hass.services.calls,[])
        self.assertFalse(self.c.delay_enabled)

    async def test_shelly_above_threshold_vetoes_unplug_stop(self):
        await self.c.async_change("real",True)
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0.04")
        self.c.refresh()
        await self.settle()
        self.assertFalse(any(x[:2] == ("switch","turn_off") for x in self.hass.services.calls))

if __name__=="__main__":
    unittest.main()
