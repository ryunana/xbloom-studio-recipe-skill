"""出杯 CLI 的干跑测试：不连蓝牙、不需要 bleak，只验证编排与帧序列。"""

import contextlib
import importlib.util
import io
import os
import json
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


proto = load("xbloom_proto", ROOT / "scripts/xbloom_proto.py")
brew = load("xbloom_brew", ROOT / "scripts/xbloom_brew.py")


class DryRunTests(unittest.TestCase):
    def test_dry_run_prints_plan_without_bluetooth(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = brew.main(["brew", "--recipe", str(ROOT / "recipes/current.json")])
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("干跑结束", text)
        self.assertIn("克豆", text)
        self.assertIn("干跑结束", text)
        self.assertNotIn("5801", text)   # 默认不吐十六进制，普通人看不懂
        self.assertNotIn("bleak", sys.modules)

    def test_plan_matches_example_recipe(self):
        payload = json.loads((ROOT / "recipes/current.json").read_text())
        plan = brew.build(payload)
        labels = [label for label, _ in plan]
        self.assertTrue(labels[0].startswith("handshake"))
        self.assertEqual(labels[-1], "execute 8002")
        self.assertTrue(labels[1].startswith("back_home"))
        self.assertIn("dose", labels[3])
        self.assertEqual(struct.unpack('<H', plan[-1][1][3:5])[0], proto.CMD_EXECUTE)

    def test_current_recipe_is_valid_and_brewable(self):
        """recipes/current.json 是"当前要冲的那份"，内容会随豆子变；只要求它合法且可编码。"""
        payload = json.loads((ROOT / "recipes/current.json").read_text())
        sys.path.insert(0, str(ROOT / "scripts"))
        import recipe_preview
        recipe_preview.validate(payload)
        plan = brew.build(payload)
        self.assertEqual(len(plan), 7)

    def test_invalid_recipe_exits_nonzero_before_bluetooth(self):
        import tempfile
        bad = json.loads((ROOT / "recipes/current.json").read_text())
        bad["recipe"]["pours"][0]["flowRate"] = 7.0
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            path.write_text(json.dumps(bad))
            err = io.StringIO()
            out = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                code = brew.main(["brew", "--recipe", str(path), "--start"])
        self.assertEqual(code, 1)
        self.assertIn("flowRate", out.getvalue())
        self.assertNotIn("bleak", sys.modules)


class RunLogTests(unittest.TestCase):
    """出杯记录：没有口感也要能留下机器侧证据。"""

    def _payload(self):
        return json.loads((ROOT / "recipes/current.json").read_text())

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["XBLOOM_RUNS_DIR"] = self._tmp.name
        self.addCleanup(os.environ.pop, "XBLOOM_RUNS_DIR", None)

    def test_log_written_without_taste_note(self):
        class FakeSession:
            info = {"serial": "TESTSERIAL", "firmware": "V0", "mode": "Pro"}
            initial_mode = "Auto"
        brew.write_run_log(self._payload(), "completed", 4, 171.2, FakeSession())
        folder = Path(self._tmp.name)
        files = sorted(folder.glob("*.json"))
        self.assertTrue(files, "没有写出记录")
        record = json.loads(files[-1].read_text())
        for key in ("outcome", "pours_observed", "duration_s", "fingerprint",
                    "expected_cup_g", "machine", "mode_before"):
            self.assertIn(key, record)
        self.assertEqual(record["outcome"], "completed")
        self.assertEqual(record["pours_observed"], 4)
        self.assertEqual(record["mode_before"], "Auto")
        self.assertIsNone(record["taste_note"])
        self.assertEqual(record["expected_cup_g"], 231)

    def test_human_failure_messages_avoid_jargon(self):
        for exc, must in ((Exception("没有扫到机器"), "找不到咖啡机"),
                          (Exception("缺水"), "没水"),
                          (Exception("握手没有回应"), "没回应")):
            self.assertIn(must, brew.human_failure(exc))
        self.assertNotIn("40522", brew.human_failure(Exception("缺水")))


class SuccessCriterionTests(unittest.TestCase):
    """什么算"冲好了"。

    2026-10-29 踩过一次：加了"四段齐全但收尾信号丢失"这个状态，却没把它算进成功，
    结果杯子满了、屏幕写"等太久"。这组测试守的就是这条线。
    """

    def test_both_success_states_count(self):
        self.assertTrue(brew.brew_succeeded("completed"))
        self.assertTrue(brew.brew_succeeded("completed_no_signal"))

    def test_failures_do_not_count(self):
        for outcome in ("stopped", "timeout", "fault", "no_water", "unknown"):
            self.assertFalse(brew.brew_succeeded(outcome), outcome)

    def test_success_branch_uses_the_helper(self):
        """防止有人把判定改回写死的 outcome == "completed"。"""
        source = (ROOT / "scripts/xbloom_brew.py").read_text()
        self.assertIn("brew_succeeded(outcome)", source)
        self.assertNotIn('outcome == "completed":', source)


if __name__ == "__main__":
    unittest.main()
