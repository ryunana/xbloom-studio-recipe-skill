"""本机蓝牙能力诊断：三种失败必须给出三套不同的话。

这组测试守的是一条产品规则——"没有蓝牙"、"蓝牙关着"、"没授权"对用户是三件事，
解法完全不同。把它们混成一句"蓝牙不可用"，用户就只能猜。
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import xbloom_brew as brew  # noqa: E402


def fake_run(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["x"], returncode=returncode,
                                       stdout=stdout.encode(), stderr=stderr.encode())


class ProbeTests(unittest.TestCase):
    def test_healthy_when_scan_succeeds(self):
        payload = '{"import_ok": true, "scan": "ok", "devices": 5, "error": ""}'
        with mock.patch.object(brew.subprocess, "run", return_value=fake_run(0, payload)):
            diag = brew.probe_bluetooth()
        self.assertEqual((diag["library"], diag["adapter"], diag["permission"]),
                         ("ok", "ok", "ok"))
        self.assertEqual(diag["devices"], 5)

    def test_missing_library_is_its_own_case(self):
        payload = '{"import_ok": false, "scan": "not_run", "error": "ModuleNotFoundError: bleak"}'
        with mock.patch.object(brew.subprocess, "run", return_value=fake_run(3, payload)):
            diag = brew.probe_bluetooth()
        self.assertEqual(diag["library"], "missing")
        self.assertIn("pip install bleak", brew.bluetooth_help(diag))

    def test_killed_process_means_no_permission(self):
        """macOS 没授权时进程被直接杀掉，没有输出。必须判成权限，不是硬件。"""
        with mock.patch.object(brew.subprocess, "run", return_value=fake_run(-6, "")):
            diag = brew.probe_bluetooth()
        self.assertEqual(diag["permission"], "denied")
        self.assertNotEqual(diag["adapter"], "missing")

    def test_no_adapter_message_wins_over_permission(self):
        payload = ('{"import_ok": true, "scan": "failed", "error": '
                   '"BleakError: No Bluetooth adapters found"}')
        with mock.patch.object(brew.subprocess, "run", return_value=fake_run(0, payload)):
            diag = brew.probe_bluetooth()
        self.assertEqual(diag["adapter"], "missing")

    def test_zero_devices_rechecks_the_switch(self):
        """扫到 0 台且蓝牙是关着的 → 报"关着"，而不是"找不到机器"。"""
        payload = '{"import_ok": true, "scan": "ok", "devices": 0, "error": ""}'
        with mock.patch.object(brew.subprocess, "run", return_value=fake_run(0, payload)), \
             mock.patch.object(brew, "adapter_state", return_value=("off", "蓝牙开关是关着的")):
            diag = brew.probe_bluetooth()
        self.assertEqual(diag["adapter"], "off")

    def test_zero_devices_with_working_adapter_stays_healthy(self):
        """扫到 0 台但蓝牙是好的 → 不能误判成硬件问题。"""
        payload = '{"import_ok": true, "scan": "ok", "devices": 0, "error": ""}'
        with mock.patch.object(brew.subprocess, "run", return_value=fake_run(0, payload)), \
             mock.patch.object(brew, "adapter_state", return_value=("ok", "")):
            diag = brew.probe_bluetooth()
        self.assertEqual(diag["adapter"], "ok")

    def test_denied_in_error_text(self):
        payload = ('{"import_ok": true, "scan": "failed", '
                   '"error": "BleakError: Bluetooth access denied"}')
        with mock.patch.object(brew.subprocess, "run", return_value=fake_run(0, payload)):
            diag = brew.probe_bluetooth()
        self.assertEqual(diag["permission"], "denied")


class HelpTextTests(unittest.TestCase):
    """每套话都必须说清"下一步做什么"，而不是解释哪里坏了。"""

    def _diag(self, **kwargs):
        base = {"library": "ok", "adapter": "ok", "permission": "ok",
                "detail": "", "devices": 0, "platform": "macOS"}
        base.update(kwargs)
        return base

    def test_no_hardware_tells_them_the_recipe_path_still_works(self):
        text = brew.bluetooth_help(self._diag(adapter="missing"))
        self.assertIn("这台电脑没有蓝牙", text)
        self.assertIn("USB 蓝牙适配器", text)
        self.assertIn("不需要蓝牙", text)          # 关键兜底：生成配方不受影响

    def test_bluetooth_off_gives_the_switch_location(self):
        text = brew.bluetooth_help(self._diag(adapter="off", detail="蓝牙开关是关着的"))
        self.assertIn("关着", text)
        self.assertIn("蓝牙图标", text)

    def test_permission_denied_names_the_right_list(self):
        text = brew.bluetooth_help(self._diag(permission="denied"))
        self.assertIn("隐私与安全性 → 蓝牙", text)
        self.assertIn("按「程序」给的", text)
        self.assertIn("退出那个程序再打开", text)

    def test_opened_settings_is_acknowledged(self):
        self.assertIn("已经帮你打开", brew.bluetooth_help(
            self._diag(permission="denied"), settings_opened=True))

    def test_unknown_does_not_assert_a_cause(self):
        text = brew.bluetooth_help(self._diag(adapter="unknown", detail="X"))
        self.assertIn("试不出", text)
        self.assertNotIn("没有蓝牙，所以连不上", text)

    def test_messages_avoid_protocol_jargon(self):
        for diag in (self._diag(adapter="missing"), self._diag(adapter="off"),
                     self._diag(permission="denied"), self._diag(adapter="unknown")):
            text = brew.bluetooth_help(diag)
            for jargon in ("BLE", "MTU", "GATT", "40512", "dBm"):
                self.assertNotIn(jargon, text, f"{jargon} 不该出现在面向用户的话里")


class AdapterStateTests(unittest.TestCase):
    """macOS 的开关状态：关了和没有硬件是两回事。"""

    def test_off_is_detected(self):
        output = "Bluetooth:\n  Bluetooth Controller:\n    State: Off\n"
        with mock.patch.object(brew, "PLATFORM", "darwin"), \
             mock.patch.object(brew.subprocess, "run", return_value=fake_run(0, output)):
            state, note = brew.adapter_state()
        self.assertEqual(state, "off")
        self.assertIn("关", note)

    def test_on_is_ok(self):
        output = "Bluetooth:\n  Bluetooth Controller:\n    State: On\n"
        with mock.patch.object(brew, "PLATFORM", "darwin"), \
             mock.patch.object(brew.subprocess, "run", return_value=fake_run(0, output)):
            self.assertEqual(brew.adapter_state()[0], "ok")

    def test_no_controller_means_missing(self):
        output = "Bluetooth:\n  Not Available\n"
        with mock.patch.object(brew, "PLATFORM", "darwin"), \
             mock.patch.object(brew.subprocess, "run", return_value=fake_run(0, output)):
            self.assertEqual(brew.adapter_state()[0], "missing")

    def test_empty_output_is_unknown_not_missing(self):
        """系统什么都不返回时不能断言"没硬件"，只能说查不到。"""
        with mock.patch.object(brew, "PLATFORM", "darwin"), \
             mock.patch.object(brew.subprocess, "run", return_value=fake_run(0, "")):
            self.assertEqual(brew.adapter_state()[0], "unknown")


class RequireBluetoothTests(unittest.TestCase):
    def test_healthy_returns_true_and_can_announce(self):
        payload = '{"import_ok": true, "scan": "ok", "devices": 2, "error": ""}'
        with mock.patch.object(brew.subprocess, "run", return_value=fake_run(0, payload)):
            self.assertTrue(brew.require_bluetooth(announce=True))

    def test_force_skips_probe(self):
        with mock.patch.object(brew, "probe_bluetooth") as probe:
            self.assertTrue(brew.require_bluetooth(force=True))
            probe.assert_not_called()

    def test_failure_returns_false(self):
        with mock.patch.object(brew.subprocess, "run", return_value=fake_run(-6, "")):
            self.assertFalse(brew.require_bluetooth())


if __name__ == "__main__":
    unittest.main()
