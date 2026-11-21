"""RC controller smoke tests with a fake Home Assistant (NO hardware)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone, time
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo
import importlib.util
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]/"custom_components/easywallbox_smart"
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

package=types.ModuleType("rc_test_package")
package.__path__=[str(ROOT)]
sys.modules["rc_test_package"]=package

def load(name):
    path=ROOT/(name+".py")
    spec=importlib.util.spec_from_file_location("rc_test_package."+name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module

const=load("const")
sources=load("sources")
policy=load("rc_policy")
controller=load("rc_controller")


class FakeState:
    def __init__(self,value,unit=None):
        self.state=str(value)
        self.attributes={} if unit is None else {"unit_of_measurement":unit}
        self.last_updated=datetime.now(timezone.utc)
        self.last_reported=self.last_updated

    def publish(self,value):
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
        C.CONF_WALLBOX_CONNECTED:"binary_sensor.wallbox_cable",
        C.CONF_WALLBOX_CHARGING:"binary_sensor.wallbox_charging",
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
        C.CONF_BOOST_KW:4.2,
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
        "sensor.floor_a":(home,"kW"),
        "sensor.floor_b":("0.1","kW"),
        "sensor.ev":("3.2" if charging else "0","kW"),
        "binary_sensor.wallbox_cable":("on" if cable else "off",None),
        "binary_sensor.wallbox_charging":("on" if charging else "off",None),
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
    return config


class RCAdapterSmoke(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory()
        self.hass=FakeHass(self.tmp.name)
        cfg=setup(self.hass)
        self.c=controller.RCController(self.hass,FakeEntry(cfg))
        await self.c.async_load()
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

    async def test_real_control_never_armed_after_boot(self):
        self.assertFalse(self.c.real_enabled)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

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

    async def test_user_explicit_delay_pauses_charging_once_with_confirmed_ack(self):
        local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        future=(local+timedelta(hours=1)).time().replace(second=0,microsecond=0)
        await self.c.async_change("time",future)
        await self.c.async_change("real",True)
        await self.c.async_change("delay",True)
        await self.settle()
        switches=[c for c in self.hass.services.calls if c[0]=="switch"]
        self.assertEqual(len(switches),1)
        self.assertEqual(switches[0][:2],("switch","turn_off"))
        self.assertEqual(self.c._pending.kind,"delay_pause")
        self.c.refresh()
        await self.settle()
        self.assertEqual(len([c for c in self.hass.services.calls
                              if c[0]=="switch"]),1)
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["sensor.command_status"].publish("Verified DPM")
        self.hass.states["binary_sensor.charge_enabled"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0.01")
        self.c.refresh()
        await self.settle()
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

    async def test_delay_switch_turns_off_after_verified_start_not_at_clock_alone(self):
        now=datetime.now(timezone.utc)
        self.c.delay_enabled=True
        self.c._scheduled_at=now-timedelta(seconds=1)
        self.hass.states["sensor.ev"].publish("0.01")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.c.refresh()
        self.assertTrue(self.c.delay_enabled)
        self.hass.states["sensor.ev"].publish("3.4")
        self.hass.states["binary_sensor.wallbox_charging"].publish("on")
        self.c.refresh()
        self.assertFalse(self.c.delay_enabled)
        self.assertIsNone(self.c._scheduled_at)

    async def test_unplug_clears_delayed_switch_only_after_real_connection(self):
        local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        future=(local+timedelta(hours=1)).time().replace(second=0,microsecond=0)
        await self.c.async_change("time",future)
        await self.c.async_change("delay",True)
        self.assertTrue(self.c.delay_enabled)
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        self.assertFalse(self.c.delay_enabled)

    async def test_connected_not_charging_without_delay_does_nothing(self):
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

    async def test_delayed_stop_only_when_cable_connected_and_verified_stopped(self):
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0")
        self.c.refresh()
        local=datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Rome"))
        clock=(local+timedelta(hours=2)).time().replace(second=0,microsecond=0)
        await self.c.async_change("time",clock)
        await self.c.async_change("delay",True)
        await self.c.async_change("real",True)
        await self.settle()
        # Under the new approved lifecycle, an already connected idle car
        # cannot be paused opportunistically: only unplug parks the DPM.
        self.assertEqual(self.hass.services.calls,[])

    async def test_missing_dpm_readback_blocks_real_command(self):
        self.hass.states["sensor.dpm_set"].publish("unavailable")
        self.c.refresh()
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

    async def test_fault_blocks_real_command(self):
        self.hass.states["binary_sensor.fault"].publish("on")
        self.c.refresh()
        await self.c.async_change("real",True)
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

    async def test_cancel_owned_delayed_pause_proposes_resume_once(self):
        self.hass.states["sensor.ev"].publish("0")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["binary_sensor.charge_enabled"].publish("off")
        self.c.refresh()
        self.c._dpm_lease=4.4
        await self.c.async_change("real",True)
        await self.settle()
        self.assertEqual(len(self.hass.services.calls),1)
        self.assertEqual(self.hass.services.calls[0][:2],
                         ("switch","turn_on"))
        self.c.refresh()
        await self.settle()
        self.assertEqual(len(self.hass.services.calls),1)

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

    async def test_external_dpm_zero_requires_reconciliation_without_start(self):
        self.hass.states["sensor.ev"].publish("0")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["binary_sensor.charge_enabled"].publish("off")
        self.c.refresh()
        self.assertEqual(self.c.reason, "dpm_zero_without_proven_rc_lease")
        self.assertFalse(self.c.real_enabled)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])

    async def test_manual_mode_is_displayed_as_manual_not_blocked(self):
        await self.c.async_change("mode","manual")
        self.assertEqual(self.c.status,"Manuale")
        self.assertFalse(self.c.real_enabled)

    async def test_confirmed_unplug_parks_once_after_30w_30seconds(self):
        await self.c.async_change("real", True)
        await self.settle()
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0.01")
        self.c.refresh()
        self.c._disconnect_since -= timedelta(seconds=31)
        self.c._ev_idle_since -= timedelta(seconds=31)
        self.c.refresh()
        await self.settle()
        switches=[x for x in self.hass.services.calls if x[0]=="switch"]
        self.assertEqual(len(switches),1)
        self.assertEqual(switches[0][:2],("switch","turn_off"))
        self.assertIsNotNone(self.c._pending)
        self.assertEqual(self.c._pending.kind,"park")
        self.c.refresh()
        await self.settle()
        self.assertEqual(len([x for x in self.hass.services.calls if x[0]=="switch"]),1)

    async def test_unplug_above_thirty_watts_never_parks(self):
        await self.c.async_change("real", True)
        await self.settle()
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["sensor.ev"].publish("0.04")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.c.refresh()
        self.c._disconnect_since -= timedelta(seconds=31)
        self.c.refresh()
        await self.settle()
        self.assertFalse(any(x[0]=="switch" for x in self.hass.services.calls))

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
        c=controller.RCController(self.hass,entry)
        await c.async_load()
        self.assertEqual(len(c.cfg[const.CONF_VEHICLES]),3)
        self.assertEqual(c.cfg[const.CONF_VEHICLES][0]["name"],
                         "Fiat aggiornata")
        self.assertFalse(c.real_enabled)
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
        self.hass.states["binary_sensor.charge_enabled"].publish("off")
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
        self.assertTrue(self.c._park_owned)
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

    async def test_refresh_after_twenty_seconds_only_selected_car(self):
        await self.c.async_change("real", True)
        self.c._refresh_due = datetime.now(timezone.utc)-timedelta(seconds=1)
        self.c._refresh_issued = False
        self.c.refresh()
        await self.settle()
        calls = [(d,serv,args["entity_id"]) for d,serv,args,_ in
                 self.hass.services.calls]
        self.assertIn(("button","press","button.fiat_update"),calls)
        self.assertIn(("button","press","button.wallbox_refresh"),calls)
        self.assertNotIn(("button","press","button.kia_update"),calls)
        self.c.refresh()
        await self.settle()
        self.assertEqual(sum(d=="button" for d,_,_,_ in self.hass.services.calls),2)

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

    async def test_park_prepare_resume_requires_verified_staged_responses(self):
        # Arm once, then disconnect and park after the measured quiet period.
        self.hass.states["number.charge_power"].publish("3.6")
        self.hass.states["sensor.power_set"].publish("3.6")
        await self.c.async_change("real",True)
        await self.settle()
        # Any pending initial number operation is outside this new session.
        self.c._pending=None
        self.hass.services.calls.clear()
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.hass.states["binary_sensor.wallbox_charging"].publish("off")
        self.hass.states["sensor.ev"].publish("0.01")
        self.c.refresh()
        self.c._disconnect_since-=timedelta(seconds=31)
        self.c._ev_idle_since-=timedelta(seconds=31)
        self.c.refresh()
        await self.settle()
        self.assertEqual(self.hass.services.calls[0][:2],("switch","turn_off"))
        self.hass.states["sensor.dpm_set"].publish("0")
        self.hass.states["binary_sensor.charge_enabled"].publish("off")
        self.hass.states["sensor.command_status"].publish("Verified DPM")
        self.c.refresh()
        await self.settle()
        self.assertTrue(self.c._park_owned)
        self.assertIsNone(self.c._pending)

        # Next car: one refresh request, then actual new SOC evidence.
        self.hass.states["binary_sensor.wallbox_cable"].publish("on")
        self.hass.states["binary_sensor.fiat"].publish("on")
        self.c.refresh()
        self.c._refresh_due=datetime.now(timezone.utc)-timedelta(seconds=1)
        self.c.refresh()
        await self.settle()
        self.assertTrue(self.c._refresh_issued)
        self.hass.states["sensor.fiat_soc"].publish("75")
        self.c.refresh()
        await self.settle()
        prepares=[x for x in self.hass.services.calls if x[0]=="number"]
        self.assertGreaterEqual(len(prepares),1)
        self.assertEqual(prepares[-1][2]["value"],4.0)
        self.assertEqual(self.c._pending.kind,"prepare")

        # BLE confirms charge-power register before ANY Start-Stop ON.
        self.assertFalse(any(x[0]=="switch" and x[1]=="turn_on"
                             for x in self.hass.services.calls))
        self.hass.states["number.charge_power"].publish("4.0")
        self.hass.states["sensor.power_set"].publish("4.0")
        self.hass.states["sensor.command_status"].publish("Verified charge power")
        self.c.refresh()
        await self.settle()
        self.assertEqual(self.c._pending.kind,"resume")
        self.assertEqual(self.hass.services.calls[-1][:2],("switch","turn_on"))

        self.hass.states["sensor.dpm_set"].publish("4.4")
        self.hass.states["binary_sensor.charge_enabled"].publish("on")
        self.hass.states["sensor.command_status"].publish("Verified DPM")
        self.c.refresh()
        await self.settle()
        self.assertFalse(self.c._park_owned)
        self.assertIsNone(self.c._pending)
        self.assertEqual(sum(d=="switch" and svc=="turn_on"
                             for d,svc,_,_ in self.hass.services.calls),1)



if __name__=="__main__":
    unittest.main()
