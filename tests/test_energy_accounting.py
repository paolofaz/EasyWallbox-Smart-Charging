"""prior iterations: source freshness, cloud SOC anchors and no fabricated EV delivery.

Every scenario uses fake HA State objects, no wallbox or BLE writes.
"""
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
import unittest

import test_controller_smoke as rig

C = rig.const


class RCTwelveEnergyAndMeterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=TemporaryDirectory()
        self.hass=rig.FakeHass(self.tmp.name)
        self.cfg=rig.setup(self.hass,cable=True,charging=True,soc="70",home=".1")
        self.c=rig.controller.ChargingController(self.hass,rig.FakeEntry(self.cfg),rig.VERSION)
        await self.c.async_load()
        self.car=self.c.cfg[C.CONF_VEHICLES][0]
        self.soc=self.hass.states[self.car[C.CONF_SOC]]
        self.ev=self.hass.states[self.cfg[C.CONF_EV_POWER]]
        self.t0=datetime.now(timezone.utc)-timedelta(minutes=11)
        self.c._soc_anchor=None
        self.c._delivery_last=None
        self.c._delivered_ev_kwh=0.0
        self.c._delivery_gap=False
        self.soc.publish("70")
        self.soc.last_reported=self.soc.last_updated=self.t0
        self._ev_report(0,3.6)

    async def asyncTearDown(self):
        await self.c.async_close()
        self.tmp.cleanup()

    def _ev_report(self, minutes, power):
        t=self.t0+timedelta(minutes=minutes)
        self.ev.publish(str(power))
        self.ev.last_reported=self.ev.last_updated=t
        return t

    def test_identical_soc_cloud_publications_never_reset_integral(self):
        first=self.c._energy_after_soc(self.t0,self.car,70,8.0)
        self.assertEqual(first,8.0)
        self.c._record_ev_delivery(self.t0,3.6,True)
        self.c._record_ev_delivery(self._ev_report(1,3.6),3.6,True)
        after=self.c._energy_after_soc(self.t0+timedelta(minutes=1),self.car,70,8.0)
        self.assertAlmostEqual(after,7.94,places=4)
        previous_anchor=self.c._soc_anchor
        # Real HA can increment last_reported while publishing the SAME SOC.
        self.soc.publish("70")
        self.soc.last_reported=self.t0+timedelta(minutes=1)
        self.assertAlmostEqual(
            self.c._energy_after_soc(self.t0+timedelta(minutes=1),
                                     self.car,70,8.0),after)
        self.assertEqual(self.c._soc_anchor,previous_anchor)
        self.c._record_ev_delivery(self._ev_report(2,3.6),3.6,True)
        updated=self.c._energy_after_soc(
            self.t0+timedelta(minutes=2),self.car,70,8.0)
        self.assertAlmostEqual(updated,7.88,places=4)

    def test_six_minute_gap_keeps_conservative_bound_and_sticky_quality(self):
        self.c._record_ev_delivery(self.t0,3.6,True)
        self.c._energy_after_soc(self.t0,self.car,70,8.0)
        self.c._record_ev_delivery(self._ev_report(1,3.6),3.6,True)
        self.c._record_ev_delivery(self._ev_report(6,3.6),3.6,True)
        self.assertTrue(self.c._delivery_gap)
        # Only one observed one-minute interval is counted; none across gap.
        self.assertAlmostEqual(self.c._energy_after_soc(
            self.t0+timedelta(minutes=6),self.car,70,8.0),7.94,places=4)
        self.soc.publish("70")
        self.soc.last_reported=self.t0+timedelta(minutes=6)
        self.assertAlmostEqual(self.c._energy_after_soc(
            self.t0+timedelta(minutes=6),self.car,70,8.0),7.94,places=4)
        self.assertTrue(self.c._delivery_gap)  # report without SOC change
        self.c._record_ev_delivery(self._ev_report(7,3.6),3.6,True)
        self.assertAlmostEqual(self.c._energy_after_soc(
            self.t0+timedelta(minutes=7),self.car,70,8.0),7.88,places=4)
        # Genuine different SOC is the safe re-anchoring event.
        self.soc.publish("71")
        self.soc.last_reported=self.t0+timedelta(minutes=7)
        self.assertAlmostEqual(self.c._energy_after_soc(
            self.t0+timedelta(minutes=7),self.car,71,7.4),7.4,places=4)
        self.assertFalse(self.c._delivery_gap)

    def test_verified_pause_does_not_create_fake_ac_energy(self):
        self.c._record_ev_delivery(self.t0,3.6,True)
        self.c._energy_after_soc(self.t0,self.car,70,8.0)
        self.c._record_ev_delivery(self._ev_report(1,3.6),3.6,True)
        self.c._record_ev_delivery(self._ev_report(1.5,0),0,False)
        self.assertIsNone(self.c._delivery_last)
        self.c._record_ev_delivery(self._ev_report(2,3.6),3.6,True)
        self.c._record_ev_delivery(self._ev_report(3,3.6),3.6,True)
        # Energy integrated only for 0..1 and 2..3; never for pause.
        self.assertAlmostEqual(self.c._delivered_ev_kwh,.12,places=4)
        self.assertFalse(self.c._delivery_gap)

    async def test_shelly_skew_has_explicit_reason_and_seconds_no_commands(self):
        t=datetime.now(timezone.utc)
        self.hass.states["sensor.floor_a"].last_reported=t
        self.hass.states["sensor.floor_b"].last_reported=t-timedelta(seconds=160)
        self.assertEqual(self.c._house(t),(None,None))
        self.assertEqual(self.c._house_quality_reason,
                         "house_sources_not_synchronized")
        self.assertAlmostEqual(self.c._house_skew_seconds,160)
        self.c._snapshot(t)
        self.assertEqual(self.c._facts["house_quality_reason"],
                         "house_sources_not_synchronized")
        self.assertIn("house_sources_not_synchronized",self.c._facts["issues"])
        self.assertEqual(self.hass.services.calls,[])

    def test_gap_margin_exists_but_advisory_eta_is_suppressed(self):
        self.c._active_departure=datetime.now(timezone.utc)+timedelta(hours=5)
        self.c._active_departure_vehicle=self.car[C.CONF_CABLE]
        self.c._record_ev_delivery(self.t0,3.6,True)
        self.c._energy_after_soc(self.t0,self.car,70,8.0)
        self.c._record_ev_delivery(self._ev_report(1,3.6),3.6,True)
        self.c._record_ev_delivery(self._ev_report(5,3.6),3.6,True)
        self.assertTrue(self.c._delivery_gap)
        # Snapshot tests the controller's quality distinction without
        # attempting an actuation or manufacturing a better house history.
        now=datetime.now(timezone.utc)
        self.soc.last_reported=now
        # Restored EV telemetry is fresh; the *earlier* blind interval
        # remains flagged and must not be reconstructed from this report.
        self.ev.last_reported=self.ev.last_updated=now
        self.c._snapshot(now)
        self.assertEqual(self.c._margin_quality,"observed_partial_gap")
        self.assertIsNone(self.c._eta_remaining_ac_kwh)
        self.assertIsNotNone(self.c._margin_energy_kwh)
        self.assertEqual(self.c._facts["margin_quality"],"observed_partial_gap")
        self.assertEqual(self.hass.services.calls,[])


if __name__=="__main__":
    unittest.main()
