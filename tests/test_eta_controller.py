"""Controller ETA regressions: measured energy, smoothing and isolation."""
import unittest
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import test_controller_smoke as rig
from easywallbox_test_package.planner_rate import ChargeETA

C = rig.const


class EtaControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.hass = rig.FakeHass(self.temp.name)
        self.cfg = rig.setup(self.hass)
        self.ctrl = rig.controller.ChargingController(
            self.hass, rig.FakeEntry(self.cfg), rig.VERSION)
        self.car = self.cfg[C.CONF_VEHICLES][0]
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def test_bounded_soc_learning_and_missing_shelly_intervals(self):
        c = self.ctrl
        c._delivered_ev_kwh = 0.0
        prior_per_pct = self.car[C.CONF_CAPACITY]/self.car[C.CONF_EFFICIENCY]/100
        first = c._eta_energy(self.car, 50, 80, True)
        self.assertAlmostEqual(first, 30*prior_per_pct)
        c._delivered_ev_kwh = 5.2
        adjusted = c._eta_energy(self.car, 60, 80, True)
        self.assertIsNotNone(c._eta_ac_per_soc)
        self.assertGreater(adjusted, 20*prior_per_pct)
        self.assertLessEqual(adjusted, 20*prior_per_pct*1.15+.00001)

        # Different car must not inherit Fiat's AC coefficient.
        kia = self.cfg[C.CONF_VEHICLES][1]
        c._eta_energy(kia, 45, 80, True)
        self.assertIsNone(c._eta_ac_per_soc)
        self.assertEqual(c._eta_soc_ref[0], kia[C.CONF_CABLE])

        # A missing interval cannot train a coefficient from incomplete AC.
        c._eta_soc_ref = (kia[C.CONF_CABLE], 45, 0)
        c._delivered_ev_kwh = 25
        c._delivery_gap = True
        c._eta_energy(kia, 55, 80, True)
        self.assertIsNone(c._eta_ac_per_soc)

    def test_uncapped_only_is_accepted_as_free_power_evidence(self):
        c = self.ctrl
        c._eta_observe(self.now, True, True, "Charging", 3.8, .15, 4.0)
        self.assertEqual(len(c._eta_free_history), 1)
        ev = self.hass.states[self.cfg[C.CONF_EV_POWER]]
        ev.last_reported = self.now+timedelta(seconds=46)
        c._eta_observe(self.now+timedelta(seconds=46), True, True,
                       "Charging", 2.0, .15, 1.8)
        self.assertEqual(len(c._eta_free_history), 1)  # LIMITED is not free
        ev.last_reported = self.now+timedelta(seconds=92)
        c._eta_observe(self.now+timedelta(seconds=92), True, True,
                       "Charging", 3.7, 1.2, 4.0)
        self.assertEqual(len(c._eta_free_history), 1)  # DPM loaded is not free

    def test_ten_minute_forecast_bucket_and_max_fifteen_minute_shift(self):
        c = self.ctrl
        eta = ChargeETA(
            seconds=3*3600, earliest_seconds=2*3600,
            free_kw=3.8, now_kw=2.3, average_kw=3.0, quality="provvisoria")
        first = self.now.replace(minute=0, second=0, microsecond=0)
        c._eta_publish(first, eta, self.car, 80)
        a = c._eta_last_finish
        c._eta_publish(first+timedelta(minutes=3), ChargeETA(
            seconds=6*3600, earliest_seconds=2*3600,
            free_kw=3.8, now_kw=0.0, average_kw=1.3, quality="provvisoria"),
            self.car, 80)
        self.assertEqual(c._eta_last_finish, a)
        c._eta_publish(first+timedelta(minutes=10), ChargeETA(
            seconds=6*3600, earliest_seconds=2*3600,
            free_kw=3.8, now_kw=0.0, average_kw=1.3, quality="provvisoria"),
            self.car, 80)
        self.assertEqual(c._eta_last_finish-a, timedelta(minutes=15))
        self.assertEqual(self.hass.services.calls, [])

    def test_different_target_resets_unsupported_stability_fence(self):
        c = self.ctrl
        eta = ChargeETA(3600, 3500, 3.8, 3.1, 3.0, "provvisoria")
        c._eta_publish(self.now, eta, self.car, 80)
        old = c._eta_last_finish
        c._eta_publish(self.now+timedelta(seconds=10), eta, self.car, 90)
        self.assertGreater(c._eta_last_finish, old)


if __name__ == "__main__":
    unittest.main()
