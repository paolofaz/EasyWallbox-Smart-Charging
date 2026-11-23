"""Option: beta diagnostics are enabled by default and explicitly switchable."""
from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import test_controller_smoke as rig
import test_config_flow_ui as flow_fixture

C = rig.const


class TestDiagnosticLogOption(unittest.IsolatedAsyncioTestCase):
    async def test_options_menu_has_log_toggle_and_visible_path_in_translations(self):
        tester = flow_fixture.TestVehicleConfigUI()
        tester.app = flow_fixture.load_flow()
        options = tester.options()
        menu = await options.async_step_init()
        self.assertIn("diagnostics", menu["menu_options"])
        form = await options.async_step_diagnostics()
        self.assertEqual(form["step_id"], "diagnostics")
        validated = form["data_schema"]({C.CONF_DIAGNOSTIC_LOGGING: False})
        self.assertIs(validated[C.CONF_DIAGNOSTIC_LOGGING], False)
        saved = await options.async_step_diagnostics(validated)
        self.assertIs(saved["data"][C.CONF_DIAGNOSTIC_LOGGING], False)
        new_options = tester.options(options=saved["data"])
        form_off = await new_options.async_step_diagnostics()
        self.assertIs(
            form_off["data_schema"]({})[C.CONF_DIAGNOSTIC_LOGGING], False)

    async def test_disabled_flag_writes_no_jsonl_even_with_events(self):
        with TemporaryDirectory() as tmp:
            hass = rig.FakeHass(tmp)
            cfg = rig.setup(hass)
            cfg[C.CONF_DIAGNOSTIC_LOGGING] = False
            c = rig.controller.ChargingController(
                hass, rig.FakeEntry(cfg), rig.VERSION)
            await c.async_load()
            self.assertFalse(c._journal._enabled)
            c._trace_session = "test-connection"
            c._record("decision", "diagnostic_flag_off", action="hold")
            await c._journal.async_flush()
            self.assertFalse(
                list(Path(tmp, "easywallbox_smart", "decision_logs")
                     .glob("*.jsonl")))
            await c.async_close()

    async def test_enabled_flag_produces_private_jsonl(self):
        with TemporaryDirectory() as tmp:
            hass = rig.FakeHass(tmp)
            cfg = rig.setup(hass)
            cfg[C.CONF_DIAGNOSTIC_LOGGING] = True
            c = rig.controller.ChargingController(
                hass, rig.FakeEntry(cfg), rig.VERSION)
            await c.async_load()
            self.assertTrue(c._journal._enabled)
            c._trace_session = "test-connection"
            c._record("decision", "diagnostic_flag_on", action="hold")
            await c._journal.async_flush()
            folder = Path(tmp, "easywallbox_smart", "decision_logs")
            found = list(folder.glob("decisions_*.jsonl"))
            self.assertEqual(len(found), 1)
            self.assertIn("diagnostic_flag_on", found[0].read_text())
            await c.async_close()

    async def test_missing_flag_is_enabled_for_first_beta_trial(self):
        with TemporaryDirectory() as tmp:
            hass = rig.FakeHass(tmp)
            cfg = rig.setup(hass)
            cfg.pop(C.CONF_DIAGNOSTIC_LOGGING, None)
            c = rig.controller.ChargingController(
                hass, rig.FakeEntry(cfg), rig.VERSION)
            await c.async_load()
            self.assertTrue(c._journal._enabled)
            await c.async_close()


if __name__ == "__main__":
    unittest.main()
