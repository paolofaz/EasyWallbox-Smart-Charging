"""Real planning data and post-installation vehicle CRUD (pure, offline)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import sys
import unittest

COMP = Path(__file__).resolve().parents[1] / "custom_components/easywallbox_smart"


def load(name):
    spec = importlib.util.spec_from_file_location("test_" + name, COMP/(name+".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


planner = load("planner_rate")
fleet = load("vehicle_profiles")
NOW = datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc)


def samples(kw, *, count=21, start=-20, step=1):
    return [(NOW+timedelta(minutes=start+i*step), kw) for i in range(count)]


def vehicle(name, cable, target=80):
    return {
        "name":name, "cable":cable, "soc":"sensor."+name.lower(),
        "capacity_kwh":42, "efficiency":.9,
        "departure_weekday":"07:00", "departure_weekend":"08:00",
        "target_fixed":target
    }


class PlannerTests(unittest.TestCase):
    def test_no_history_does_not_invent_a_default_kw(self):
        self.assertIsNone(planner.estimate_ac_kw(
            now=NOW, dpm_kw=4.4, ev_base_kw=4,
            house_samples=[], charging_ev_samples=[]))
        self.assertIsNone(planner.margin_minutes(
            now=NOW, departure=NOW+timedelta(hours=6),
            remaining_kwh=8, rate_kw=None))

    def test_house_power_changes_estimated_rate(self):
        low=planner.estimate_ac_kw(
            now=NOW,dpm_kw=4.4,ev_base_kw=4,house_samples=samples(.1))
        high=planner.estimate_ac_kw(
            now=NOW,dpm_kw=4.4,ev_base_kw=4,house_samples=samples(1.4))
        self.assertEqual(low,4.0)
        self.assertLess(high,low)
        self.assertAlmostEqual(high,2.8)

    def test_boosted_ev_samples_never_raise_hypothetical_regular_rate(self):
        kw=planner.estimate_ac_kw(
            now=NOW,dpm_kw=4.4,ev_base_kw=4.0,
            house_samples=samples(.08),charging_ev_samples=samples(4.2))
        self.assertEqual(kw,4.0)

    def test_real_ev_history_lowers_forecast_not_increases(self):
        kw=planner.estimate_ac_kw(
            now=NOW,dpm_kw=4.4,ev_base_kw=4,
            house_samples=samples(.1),charging_ev_samples=samples(2.1))
        self.assertAlmostEqual(kw,2.1)

    def test_stale_or_gappy_house_does_not_count_as_evidence(self):
        self.assertIsNone(planner.estimate_ac_kw(
            now=NOW,dpm_kw=4.4,ev_base_kw=4,
            house_samples=samples(.1,count=3,start=-15,step=5)))
        self.assertIsNone(planner.estimate_ac_kw(
            now=NOW,dpm_kw=4.4,ev_base_kw=4,
            house_samples=samples(.1,count=10,start=-20)))

    def test_more_consumption_requires_earlier_start(self):
        departure=NOW+timedelta(hours=5)
        early=planner.margin_minutes(
            now=NOW,departure=departure,remaining_kwh=8,rate_kw=2.8)
        late=planner.margin_minutes(
            now=NOW,departure=departure,remaining_kwh=8,rate_kw=4.0)
        self.assertLess(early,late)

    def test_no_zero_dpm_as_numerical_planner_input(self):
        self.assertIsNone(planner.estimate_ac_kw(
            now=NOW,dpm_kw=0,ev_base_kw=4,house_samples=samples(.1)))


class VehicleManagementTests(unittest.TestCase):
    def setUp(self):
        self.fiat=vehicle("Fiat","binary_sensor.fiat")
        self.kia=vehicle("Kia","binary_sensor.kia")

    def test_legacy_manual_rate_is_dropped_not_read(self):
        old=dict(self.fiat,planning_rate_kw=2.4)
        self.assertNotIn("planning_rate_kw",fleet.clean_vehicle(old))
        self.assertNotIn("planning_rate_kw",
            fleet.configured_vehicles({"vehicles":[old]},{} )[0])

    def test_initial_profiles_can_be_edited_after_installation(self):
        revised=dict(self.fiat,soc="sensor.updated_soc",capacity_kwh=44,
                     target_entity="number.target_soc")
        revised.pop("target_fixed")
        result=fleet.upsert_vehicle([self.fiat,self.kia],revised,
                                    original_cable=self.fiat["cable"])
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]["capacity_kwh"],44)
        self.assertEqual(result[0]["target_entity"],"number.target_soc")
        self.assertNotIn("target_fixed",result[0])
        self.assertEqual(result[1],self.kia)

    def test_can_add_a_third_auto_with_unique_cable(self):
        third=vehicle("Third","binary_sensor.third")
        result=fleet.upsert_vehicle([self.fiat,self.kia],third)
        self.assertEqual(len(result),3)

    def test_can_remove_only_when_another_car_remains(self):
        result=fleet.remove_vehicle([self.fiat,self.kia],self.fiat["cable"])
        self.assertEqual(result,[self.kia])
        with self.assertRaisesRegex(ValueError,"cannot_remove_last"):
            fleet.remove_vehicle(result,self.kia["cable"])

    def test_duplicate_name_or_cable_refused(self):
        for new in (vehicle("New",self.kia["cable"]),
                    vehicle("KIA","binary_sensor.other")):
            with self.subTest(new=new):
                with self.assertRaisesRegex(ValueError,"duplicate_vehicle"):
                    fleet.upsert_vehicle([self.fiat,self.kia],new)

    def test_invalid_soc_target_or_battery_refused(self):
        for new in (
            dict(self.fiat,target_entity="number.target"),
            dict(self.fiat,capacity_kwh=0),
            {k:v for k,v in self.fiat.items() if k!="target_fixed"},
        ):
            with self.assertRaisesRegex(ValueError,"invalid_vehicle"):
                fleet.upsert_vehicle([self.kia],new)

    def test_existing_schedule_options_and_full_options(self):
        data={"vehicles":[self.fiat,self.kia]}
        old={"vehicle_schedules":{self.fiat["cable"]:
                                  {"departure_weekday":"06:30"}}}
        self.assertEqual(
            fleet.configured_vehicles(data,old)[0]["departure_weekday"],
            "06:30")
        newer={"vehicles":[self.kia,self.fiat]}
        self.assertEqual(fleet.configured_vehicles(data,newer)[0]["name"],
                         "Kia")


if __name__=="__main__":
    unittest.main()
