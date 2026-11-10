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
EXAMPLE = ROOT / "examples/ethiopia-duwancho.recipe.json"


class DryRunTests(unittest.TestCase):
    def test_dry_run_prints_plan_without_bluetooth(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = brew.main(["brew", "--recipe", str(EXAMPLE)])
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("干跑结束", text)
        self.assertIn("克豆", text)
        self.assertIn("干跑结束", text)
        self.assertNotIn("5801", text)   # 默认不吐十六进制，普通人看不懂
        self.assertNotIn("bleak", sys.modules)

    def test_plan_matches_example_recipe(self):
        payload = json.loads(EXAMPLE.read_text())
        plan = brew.build(payload)
        labels = [label for label, _ in plan]
        self.assertTrue(labels[0].startswith("handshake"))
        self.assertEqual(labels[-1], "execute 8002")
        self.assertTrue(labels[1].startswith("back_home"))
        self.assertIn("dose", labels[3])
        self.assertEqual(struct.unpack('<H', plan[-1][1][3:5])[0], proto.CMD_EXECUTE)

    def test_current_recipe_is_valid_and_brewable(self):
        """示例配方必须合法且可编码（用户自己的 recipes/current.json 不进仓库，CI 里没有）。"""
        payload = json.loads(EXAMPLE.read_text())
        sys.path.insert(0, str(ROOT / "scripts"))
        import recipe_preview
        recipe_preview.validate(payload)
        plan = brew.build(payload)
        self.assertEqual(len(plan), 7)

    def test_invalid_recipe_exits_nonzero_before_bluetooth(self):
        import tempfile
        bad = json.loads(EXAMPLE.read_text())
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
        return json.loads(EXAMPLE.read_text())

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



def v60_payload():
    payload = json.loads(EXAMPLE.read_text())
    payload["cupType"] = "other"
    payload["brewer"] = {"id": "v60-01"}
    return payload


class BrewerTests(unittest.TestCase):
    """选滤杯：杯型帧跟着滤杯走；非 Omni 允许真冲，但必须多一次确认。#11"""

    def _write(self, payload):
        import tempfile
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "recipe.json"
        path.write_text(json.dumps(payload))
        return path

    def _run(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = brew.main(argv)
        return code, out.getvalue()

    def test_omni_keeps_omni_cup_frame(self):
        plan = dict(brew.build(json.loads(EXAMPLE.read_text())))
        cup = [packet for label, packet in plan.items() if label.startswith("set_cup")]
        self.assertEqual(cup[0], proto.frame(proto.CMD_SET_CUP,
                                             [proto.float_bits(110.0), proto.float_bits(90.0)]))

    def test_v60_sends_other_cup_frame_matching_capture(self):
        plan = brew.build(v60_payload())
        cup = [packet for label, packet in plan if label.startswith("set_cup")]
        self.assertEqual(cup[0].hex().upper(), proto.CAPTURES["set_cup_200_80"])

    def test_dry_run_shows_brewer_and_experimental_flag(self):
        code, text = self._run(["brew", "--recipe", str(self._write(v60_payload()))])
        self.assertEqual(code, 0)
        self.assertIn("滤杯：V60 01", text)
        self.assertIn("实验性", text)
        code, text = self._run(["brew", "--recipe", str(EXAMPLE)])
        self.assertIn("滤杯：Omni（原装）", text)
        self.assertNotIn("实验性", text)

    def test_experimental_start_needs_explicit_ok_before_bluetooth(self):
        code, text = self._run(["brew", "--recipe", str(self._write(v60_payload())), "--start"])
        self.assertEqual(code, 1)
        self.assertIn("--experimental-ok", text)
        self.assertIn("issues/new", text)
        self.assertNotIn("bleak", sys.modules)

    def test_other_brewer_label_and_run_log(self):
        import tempfile
        payload = json.loads(EXAMPLE.read_text())
        payload["cupType"] = "other"
        payload["brewer"] = {"id": "other", "name": "Kalita Wave 155"}

        class FakeSession:
            info = {}
            initial_mode = None
        with tempfile.TemporaryDirectory() as temp:
            os.environ["XBLOOM_RUNS_DIR"] = temp
            self.addCleanup(os.environ.pop, "XBLOOM_RUNS_DIR", None)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                brew.write_run_log(payload, "completed", 4, 160.0, FakeSession())
            record = json.loads(next(Path(temp).glob("*.json")).read_text())
        self.assertEqual(record["brewer"], "其他滤杯：Kalita Wave 155")
        self.assertIn("issues/new", out.getvalue())



def fake_frame(code, status=0xC1, payload=b""):
    """造一条机器通知帧：58 02 07 [code][len][status][payload][crc 占位]。"""
    length = 12 + len(payload)
    return (bytes([0x58, 0x02, 0x07]) + struct.pack("<H", code) + struct.pack("<I", length)
            + bytes([status]) + payload + b"\x00\x00")


class TimelineTests(unittest.TestCase):
    """冲煮通知时间线：WAIT 和"完成"信号都靠它事后对时间。#13 #6"""

    def _timeline(self):
        clock = {"now": 100.0}
        timeline = brew.Timeline(clock=lambda: clock["now"])
        timeline.begin()
        return timeline, clock

    def test_nothing_recorded_before_brew_starts(self):
        timeline = brew.Timeline()
        timeline.add(fake_frame(40510), 40510)
        self.assertEqual(timeline.entries, [])

    def test_unknown_codes_are_all_kept_with_raw_bytes_and_time(self):
        timeline, clock = self._timeline()
        for step, code in enumerate((49991, 49991, 49992, 40555)):
            clock["now"] = 100.0 + 118.0 + step
            frame = fake_frame(code)
            timeline.add(frame, code, "update")
        self.assertEqual([e["code"] for e in timeline.entries], [49991, 49991, 49992, 40555])
        self.assertEqual(timeline.entries[0]["t"], 118.0)
        self.assertEqual(timeline.entries[0]["hex"], fake_frame(49991).hex().upper())
        self.assertEqual(timeline.summary(), {49991: 2, 49992: 1, 40555: 1})

    def test_normal_flow_codes_are_not_flagged_unknown(self):
        timeline, clock = self._timeline()
        for code in (40502, 40510, 40511, 40512, 40513, 8023):
            timeline.add(fake_frame(code), code)
        self.assertEqual(timeline.summary(), {})

    def test_telemetry_is_thinned_to_one_per_second(self):
        timeline, clock = self._timeline()
        for tick in range(100):                      # 10 秒，每 0.1 秒一条
            clock["now"] = 100.0 + tick * 0.1
            timeline.add(fake_frame(20501, payload=struct.pack("<f", 12.5)), 20501)
        self.assertLessEqual(len(timeline.entries), 11)
        self.assertGreaterEqual(len(timeline.entries), 9)
        self.assertEqual(timeline.entries[0]["value"], 12.5)
        self.assertEqual(timeline.summary(), {})     # 遥测不算"没见过"

    def test_telemetry_does_not_hide_other_events(self):
        timeline, clock = self._timeline()
        clock["now"] = 100.0
        timeline.add(fake_frame(20501, payload=struct.pack("<f", 1.0)), 20501)
        clock["now"] = 100.05
        timeline.add(fake_frame(49991), 49991)       # 紧跟在遥测后面，不能被限速吞掉
        self.assertEqual([e["code"] for e in timeline.entries], [20501, 49991])

    def test_hard_cap_counts_dropped(self):
        timeline, clock = self._timeline()
        for index in range(brew.TIMELINE_LIMIT + 5):
            timeline.add(fake_frame(49991), 49991)
        self.assertEqual(len(timeline.entries), brew.TIMELINE_LIMIT)
        self.assertEqual(timeline.dropped, 5)

    def test_session_records_before_parsing(self):
        """哪怕后面的解析把帧当成"不认识"，时间线里也要有。"""
        session = brew.Session()
        session.timeline.begin()
        session.on_notify(None, bytearray(fake_frame(40517)))
        session.on_notify(None, bytearray(b"\x58\x02\x07"))        # 残帧：不能崩
        self.assertEqual([e["code"] for e in session.timeline.entries], [40517])

    def test_run_log_contains_timeline_and_stays_valid_json(self):
        import tempfile

        class FakeSession:
            info = {}
            initial_mode = None
            timeline = brew.Timeline(clock=iter([0.0, 5.0, 118.0, 118.5]).__next__)

        session = FakeSession()
        session.timeline.begin()
        session.timeline.add(fake_frame(40510), 40510)
        session.timeline.add(fake_frame(49991), 49991, "update")
        with tempfile.TemporaryDirectory() as temp:
            os.environ["XBLOOM_RUNS_DIR"] = temp
            self.addCleanup(os.environ.pop, "XBLOOM_RUNS_DIR", None)
            with contextlib.redirect_stdout(io.StringIO()):
                brew.write_run_log(json.loads(EXAMPLE.read_text()), "completed_no_signal",
                                   4, 208.5, session)
            text = next(Path(temp).glob("*.json")).read_text()
        record = json.loads(text)
        self.assertEqual([e["code"] for e in record["timeline"]], [40510, 49991])
        self.assertEqual(record["timeline"][1]["t"], 118.0)
        self.assertEqual(record["timeline_unknown_codes"], {"49991": 1})
        self.assertEqual(text.count('"hex"'), 2)
        self.assertTrue(all("hex" in line for line in text.splitlines() if '"t":' in line),
                        "时间线每条应在同一行")

    def test_run_log_without_timeline_is_unchanged(self):
        """老路径（没有时间线）的记录字段不变。"""
        class FakeSession:
            info = {}
            initial_mode = None
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            os.environ["XBLOOM_RUNS_DIR"] = temp
            self.addCleanup(os.environ.pop, "XBLOOM_RUNS_DIR", None)
            with contextlib.redirect_stdout(io.StringIO()):
                brew.write_run_log(json.loads(EXAMPLE.read_text()), "completed", 4, 1.0, FakeSession())
            record = json.loads(next(Path(temp).glob("*.json")).read_text())
        self.assertNotIn("timeline", record)

    def test_say_flushes_immediately(self):
        """经过 | tee 这类管道时也要实时显示（2026-11-09 冲煮时输出被缓冲，看不到进度）。"""
        class Probe(io.StringIO):
            flushes = 0

            def flush(self):
                Probe.flushes += 1
        probe = Probe()
        with contextlib.redirect_stdout(probe):
            brew.say("hello")
        self.assertGreaterEqual(Probe.flushes, 1)


if __name__ == "__main__":
    unittest.main()


class PersonalRecipeTests(unittest.TestCase):
    """用户配方只留在本机：不能被 git 跟踪，否则升级（git pull）会和用户改动冲突。#7"""

    def test_personal_recipes_are_git_ignored(self):
        import shutil
        import subprocess
        if shutil.which("git") is None or not (ROOT / ".git").exists():
            self.skipTest("不在 git 仓库里（打包场景）")
        for name in ("recipes/current.json", "recipes/my-kenya.json"):
            result = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT)
            self.assertEqual(result.returncode, 0, f"{name} 应被 .gitignore 忽略")
        tracked = subprocess.run(["git", "ls-files", "recipes"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.split()
        self.assertEqual(tracked, ["recipes/README.md"])


class ListenTests(unittest.TestCase):
    """listen 监听模式：被动记录机器通知，测绘"什么情况发什么码"。#15"""

    def _session(self, entries):
        import types
        clock = {"now": 0.0}
        timeline = brew.Timeline(clock=lambda: clock["now"])
        timeline.begin()
        for at, code in entries:
            clock["now"] = at
            timeline.add(fake_frame(code), code, "update")
        return types.SimpleNamespace(info={"serial": "T"}, timeline=timeline)

    def _run_dir(self):
        import tempfile
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        os.environ["XBLOOM_RUNS_DIR"] = temp.name
        self.addCleanup(os.environ.pop, "XBLOOM_RUNS_DIR", None)
        return Path(temp.name)

    def test_listen_log_written_with_timeline_and_unknowns(self):
        folder = self._run_dir()
        session = self._session([(3.0, 49991), (9.0, 8009)])
        with contextlib.redirect_stdout(io.StringIO()):
            brew.write_listen_log(session, 61.2, note="步骤6 睡眠")
        files = list(folder.glob("*-listen.json"))
        self.assertEqual(len(files), 1)
        record = json.loads(files[0].read_text())
        self.assertEqual(record["kind"], "listen")
        self.assertEqual(record["duration_s"], 61.2)
        self.assertEqual(record["note"], "步骤6 睡眠")
        self.assertEqual([e["code"] for e in record["timeline"]], [49991, 8009])
        self.assertEqual(record["timeline_unknown_codes"], {"49991": 1})
        self.assertEqual(record["machine"], {"serial": "T"})

    def test_listen_log_written_even_when_silent(self):
        """机器一条没发也要写文件："沉默"是排查结论，不能和"没记"混淆。"""
        folder = self._run_dir()
        session = self._session([])
        with contextlib.redirect_stdout(io.StringIO()):
            brew.write_listen_log(session, 30.0)
        record = json.loads(next(folder.glob("*-listen.json")).read_text())
        self.assertEqual(record["timeline"], [])
        self.assertEqual(record["timeline_unknown_codes"], {})

    def test_listen_help_lists_seconds_and_note(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as hit:
            brew.main(["listen", "--help"])
        self.assertEqual(hit.exception.code, 0)
        for flag in ("--seconds", "--note", "--verbose"):
            self.assertIn(flag, out.getvalue())


class MappedCodesTests(unittest.TestCase):
    """2026-11-09 真机测绘回来的码，不能再被标"不认识"。#17"""

    MAPPED = (9010, 9011, 40515, 40516, 40517, 40522, 50029, 50036, 65534,
              8100, 8022, 8017, 8102, 8104, 8001, 8004, 8002, 11511,
              40505, 40526, 40506, 40507, 9000, 9002, 9004, 9007, 9008, 8105, 8106)

    def test_mapped_codes_not_flagged_unknown(self):
        clock = {"now": 0.0}
        timeline = brew.Timeline(clock=lambda: clock["now"])
        timeline.begin()
        for i, code in enumerate(self.MAPPED):
            clock["now"] = float(i)
            timeline.add(fake_frame(code), code)
        self.assertEqual(timeline.summary(), {})

    def test_mapped_codes_have_names(self):
        for code in (9010, 9011, 40515, 40516, 40517):
            self.assertIn(code, brew.CODE_NAMES)
