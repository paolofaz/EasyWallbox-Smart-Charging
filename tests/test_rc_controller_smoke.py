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
        C.CONF_EXPECTED_DPM:4.4,
        C.CONF_BASE_KW:4.0,
        C.CONF_BOOST_KW:4.2,
        C.CONF_LEGACY_DISABLED:True,
        C.CONF_VEHICLES:[
            {C.CONF_NAME:"Fiat",C.CONF_CABLE:"binary_sensor.fiat",
             C.CONF_SOC:"sensor.fiat_soc",C.CONF_TARGET_FIXED:80,
             C.CONF_CAPACITY:42,C.CONF_EFFICIENCY:.9,
             C.CONF_DEPARTURE_WEEKDAY:"07:00",C.CONF_DEPARTURE_WEEKEND:"08:00",
             "planning_rate_kw":2.4},
            {C.CONF_NAME:"Kia",C.CONF_CABLE:"binary_sensor.kia",
             C.CONF_SOC:"sensor.kia_soc",C.CONF_TARGET_FIXED:80,
             C.CONF_CAPACITY:77,C.CONF_EFFICIENCY:.9,
             C.CONF_DEPARTURE_WEEKDAY:"07:00",C.CONF_DEPARTURE_WEEKEND:"08:00",
             "planning_rate_kw":2.4},
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
        with self.assertRaises(ValueError):
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

    async def test_charging_never_pauses_even_when_schedule_on(self):
        await self.c.async_change("delay",True)
        await self.c.async_change("real",True)
        await self.settle()
        self.assertFalse(any(x[0]=="switch" for x in self.hass.services.calls))

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
        self.assertLessEqual(len(self.hass.services.calls),1)
        for domain,service,args,_ in self.hass.services.calls:
            self.assertEqual((domain,service),("switch","turn_off"))

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

    async def test_lab_can_run_when_unplugged_without_switching(self):
        self.hass.states["binary_sensor.wallbox_cable"].publish("off")
        self.hass.states["binary_sensor.fiat"].publish("off")
        self.c.refresh()
        await self.c.async_change("lab",True)
        await self.settle()
        self.assertEqual(self.hass.services.calls,[])
        self.assertTrue(self.c.lab_enabled)


if __name__=="__main__":
    unittest.main()
