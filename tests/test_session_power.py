"""prior iterations power slider: only one verified controller, no BLE in number entity."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
import unittest

import test_controller_smoke as rig

C=rig.const
P=rig.policy


class RCTemporaryPowerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory()
        self.hass=rig.FakeHass(self.tmp.name)
        self.cfg=rig.setup(self.hass,cable=True,charging=True,soc="70")
        self.c=rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        await self.c.async_load()
        self.c.real_enabled=False  # Do not write on test setup.
        self.c.refresh()
        self.c._refresh_due=None
        self.c._refresh_issued=True
        self.c._refresh_requested_at=None
        self.c._connect_since=datetime.now(timezone.utc)-timedelta(minutes=1)
        self.assertIsNotNone(self.c._trace_session)
        self.assertIsNotNone(self.c._session_id)

    async def asyncTearDown(self):
        await self.c.async_close()
        self.tmp.cleanup()

    def publish(self, entity, value):
        self.hass.states[entity].publish(value)

    def command_values(self):
        return [x[2]["value"] for x in self.hass.services.calls
                if x[:2]==("number","set_value")]

    async def actuate(self):
        self.c.real_enabled=True
        # Existing source data already has physical proof of Charging.
        await self.c._actuate(self.c._session_id)

    async def test_slider_exactly_copies_esphome_number_limits(self):
        number=self.hass.states[self.cfg[C.CONF_REQUESTED_LIMIT]]
        number.attributes.update(min=1.8,max=5.8,step=.2)
        self.assertEqual(self.c.session_power_range(),(1.8,5.8,.2))
        self.assertTrue(self.c._valid_session_power(4.2))
        self.assertFalse(self.c._valid_session_power(1.6))
        self.assertFalse(self.c._valid_session_power(5.9))
        self.assertFalse(self.c._valid_session_power(4.3))
        number.attributes.pop("max")
        self.assertIsNone(self.c.session_power_range())
        with self.assertRaises(ValueError):
            await self.c.async_set_session_power(4.2)
        self.assertEqual(self.command_values(),[])

    async def test_setting_session_limit_is_only_an_intent_until_charging_verified(self):
        self.publish(self.cfg[C.CONF_WALLBOX_CHARGING],"off")
        self.publish(self.cfg[C.CONF_EV_POWER],"0")
        self.c.refresh()
        await self.c.async_set_session_power(4.2)
        await asyncio.sleep(.02)
        self.assertEqual(self.c.session_power_kw,4.2)
        self.assertEqual(self.command_values(),[])
        await self.actuate()  # physical charging now False
        self.assertEqual(self.command_values(),[])

    async def test_verified_charging_applies_one_user_power_write_and_ack(self):
        await self.c.async_set_session_power(4.2)
        self.assertEqual(self.command_values(),[])
        await self.actuate()
        self.assertEqual(self.command_values(),[4.2])
        self.assertIsNotNone(self.c._pending)
        self.assertIsNone(self.c._owned_limit)  # ownership only after ACK
        self.assertAlmostEqual(self.c._power_state.baseline_kw,4.0)
        self.publish(self.cfg[C.CONF_REQUESTED_LIMIT],4.2)
        self.publish(self.cfg[C.CONF_CONFIRMED_LIMIT],4.2)
        self.c.real_enabled=False  # avoid any incidental further policy action
        self.c.refresh()
        self.assertIsNone(self.c._pending)
        self.assertAlmostEqual(self.c._owned_limit,4.2)
        self.assertEqual(self.c._power_state.phase,"NORMAL")
        self.assertAlmostEqual(self.c._power_state.baseline_kw,4.2)
        self.assertEqual(self.command_values(),[4.2])

    async def test_user_change_overrides_limited_phase_without_start_stop(self):
        # The earlier LIMITED cap belongs to this same software controller.
        self.publish(self.cfg[C.CONF_REQUESTED_LIMIT],2.8)
        self.publish(self.cfg[C.CONF_CONFIRMED_LIMIT],2.8)
        self.c._owned_limit=2.8
        self.c._power_state=P.State(session_id=self.c._session_id,
            phase="LIMITED",cap_kw=2.8,baseline_kw=4.0,kind="strong")
        await self.c.async_set_session_power(3.6)
        await self.actuate()
        self.assertEqual(self.command_values(),[3.6])
        self.assertFalse(any(x[0]=="switch" for x in self.hass.services.calls))
        self.assertEqual(self.c._power_state.phase,"LIMITED")  # not before ACK
        self.publish(self.cfg[C.CONF_REQUESTED_LIMIT],3.6)
        self.publish(self.cfg[C.CONF_CONFIRMED_LIMIT],3.6)
        self.c.real_enabled=False
        self.c.refresh()
        self.assertIsNone(self.c._pending)
        self.assertEqual(self.c._power_state.phase,"NORMAL")
        self.assertAlmostEqual(self.c._power_state.baseline_kw,3.6)

    async def test_unplug_resets_value_without_any_ble_command(self):
        await self.c.async_set_session_power(5.0)
        previous=self.c._trace_session
        self.publish(self.cfg[C.CONF_WALLBOX_CHARGING],"off")
        self.publish(self.cfg[C.CONF_EV_POWER],"0")
        self.publish(self.cfg[C.CONF_WALLBOX_CONNECTED],"off")
        self.publish(self.cfg[C.CONF_VEHICLES][0][C.CONF_CABLE],"off")
        self.c.refresh()
        self.assertIsNone(self.c._trace_session)
        self.assertEqual(self.c.session_power_kw,4.0)  # existing saved config
        self.assertEqual(self.command_values(),[])
        self.publish(self.cfg[C.CONF_WALLBOX_CONNECTED],"on")
        self.publish(self.cfg[C.CONF_VEHICLES][0][C.CONF_CABLE],"on")
        self.c.refresh()
        self.assertNotEqual(self.c._trace_session,previous)
        self.assertEqual(self.c.session_power_kw,4.0)
        self.assertEqual(self.command_values(),[])

    async def test_short_ble_drop_keeps_session_intent_but_never_writes(self):
        await self.c.async_set_session_power(4.8)
        previous=self.c._trace_session
        self.publish(self.cfg[C.CONF_BLE_CONNECTED],"off")
        self.c.refresh()
        self.assertEqual(self.c.session_power_kw,4.8)
        self.publish(self.cfg[C.CONF_BLE_CONNECTED],"on")
        self.c.refresh()
        self.assertEqual(self.c._trace_session,previous)
        self.assertEqual(self.c.session_power_kw,4.8)
        self.assertEqual(self.command_values(),[])

    async def test_slider_unavailable_unplugged_and_invalid_request_rejected(self):
        for value in (0.0, 4.1, 9.0, float("nan"), True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    await self.c.async_set_session_power(value)
        self.assertEqual(self.c.session_power_kw,4.0)
        self.publish(self.cfg[C.CONF_WALLBOX_CHARGING],"off")
        self.publish(self.cfg[C.CONF_EV_POWER],"0")
        self.publish(self.cfg[C.CONF_WALLBOX_CONNECTED],"off")
        self.c.refresh()
        with self.assertRaises(ValueError):
            await self.c.async_set_session_power(4.2)
        self.assertEqual(self.command_values(),[])

    async def test_manual_mode_slider_intent_never_commands_wallbox(self):
        await self.c.async_change("mode","manual")
        await self.c.async_set_session_power(4.2)
        await self.c._actuate(self.c._session_id)
        self.assertEqual(self.c.session_power_kw,4.2)
        self.assertEqual(self.command_values(),[])

    async def test_no_boost_fields_in_current_runtime(self):
        self.assertFalse(hasattr(C,"CONF_BOOST_KW"))
        self.assertFalse(hasattr(P.Observation,"boost_max_kw"))
        self.assertFalse(hasattr(P.State,"boost_margin_since"))
        self.assertEqual(C.DEFAULT_BASE_KW,4.2)


if __name__=="__main__":
    unittest.main()
