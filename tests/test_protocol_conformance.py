"""协议层一致性测试：任何改动都必须仍然对得上实测报文与机器行为。

跑法（在 skill 目录内）：
    python3 -m unittest discover -s tests -v
"""

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("xbloom_proto", ROOT / "scripts/xbloom_proto.py")
proto = importlib.util.module_from_spec(SPEC)
sys.modules["xbloom_proto"] = proto
SPEC.loader.exec_module(proto)


def pours(*volumes, temperature=93, flow=3.0, pattern="spiral", pause=8):
    return [proto.Pour(volume=v, temperature=temperature, flow_rate=flow,
                       pattern=proto.PATTERN_WIRE[pattern], pause=pause,
                       vib_before=False, vib_after=(i == 0))
            for i, v in enumerate(volumes)]


def parse_blob(blob: bytes) -> dict:
    """把 blob 拆回结构。注水块 = [体积, 温度, 模式, 振动]，时序块 = [驻留取负, 0, rpm, 流速×10]。

    时序块的第二个字节恒为 0（温度不可能为 0），注水块的第二个字节是温度，据此分段。
    """
    body = blob[1:-2]
    if len(body) % 4:
        raise AssertionError(f"blob 数据段不是 4 的倍数: {len(body)}")
    pours_out, current = [], []
    for offset in range(0, len(body), 4):
        block = body[offset:offset + 4]
        if block[1] == 0:
            pours_out.append({"volumes": current, "pause": -block[0] & 0xFF,
                              "rpm": block[2], "flow": block[3] / 10})
            current = []
        else:
            current.append({"volume": block[0], "temperature": block[1],
                            "pattern": block[2], "vibration": block[3]})
    if current:
        raise AssertionError("blob 末尾残留没有时序块的注水块")
    return {"pours": pours_out, "grinder": blob[-2], "ratio": blob[-1],
            "declared_length": blob[0]}


class CaptureTests(unittest.TestCase):
    """帧层：逐字节对齐实测报文。"""

    def test_reference_frames_match_captures(self):
        result = proto.selfcheck()
        self.assertTrue(all(result.values()), result)

    def test_crc_is_stable(self):
        self.assertEqual(proto.crc16(bytes.fromhex("5801019B110C00000001")), 0x4336)
        self.assertEqual(proto.frame(proto.CMD_STOP).hex().upper(), "5801019B110C000000013643")

    def test_frame_length_field_is_data_plus_twelve(self):
        packet = proto.frame(proto.CMD_SET_CUP, [1, 2])
        length = struct.unpack("<I", packet[5:9])[0]
        self.assertEqual(length, 12 + 8)
        self.assertEqual(len(packet), length)

    def test_hex_frame_carries_raw_payload(self):
        packet = proto.frame_hex(proto.CMD_RECIPE_GRIND, b"\x01\x02\x03")
        self.assertEqual(packet[2], 0x02)
        self.assertEqual(packet[10:13], b"\x01\x02\x03")


class BlobTests(unittest.TestCase):
    """配方 blob：尾部两字节是 [研磨度, ratio×10]，不是 CRC、不是总水量。"""

    def test_tail_is_grinder_and_ratio(self):
        blob = proto.encode_blob(pours(45, 65, 65, 65), grinder_size=50, dose=15, rpm=110)
        self.assertEqual(blob[-2], 50)
        self.assertEqual(blob[-1], 160)          # 1:16 → ratio×10
        self.assertEqual(blob[0], len(blob) - 3)  # 长度前缀

    def test_gate_holds_for_various_doses(self):
        for dose, volumes in ((15, (45, 65, 65, 65)), (12, (50, 70, 72)),
                              (18, (60, 90, 90)), (5, (20, 25, 35))):
            with self.subTest(dose=dose, volumes=volumes):
                parsed = parse_blob(proto.encode_blob(pours(*volumes), grinder_size=50,
                                                      dose=dose, rpm=90))
                total = sum(step["volume"] for pour in parsed["pours"]
                            for step in pour["volumes"])
                self.assertEqual(int(proto._f32(proto._f32(parsed["ratio"] / 10) * dose)), total)

    def test_volumes_stay_close_to_design(self):
        volumes = (45, 65, 65, 65)
        parsed = parse_blob(proto.encode_blob(pours(*volumes), grinder_size=50, dose=15, rpm=90))
        wire = [sum(step["volume"] for step in pour["volumes"]) for pour in parsed["pours"]]
        self.assertEqual(wire, list(volumes))

    def test_volume_over_127_is_chunked(self):
        parsed = parse_blob(proto.encode_blob(pours(150, 90), grinder_size=50, dose=15, rpm=90))
        self.assertEqual([len(p["volumes"]) for p in parsed["pours"]], [2, 1])
        self.assertEqual([s["volume"] for s in parsed["pours"][0]["volumes"]], [127, 23])
        self.assertEqual(sum(s["volume"] for s in parsed["pours"][0]["volumes"]), 150)

    def test_rpm_only_in_first_timing_block(self):
        parsed = parse_blob(proto.encode_blob(pours(60, 60, 60), 50, 15, rpm=110))
        self.assertEqual([p["rpm"] for p in parsed["pours"]], [110, 0, 0])

    def test_pause_is_negated(self):
        parsed = parse_blob(proto.encode_blob(pours(60, 60, 60, pause=14), 50, 15, 90))
        self.assertEqual([p["pause"] for p in parsed["pours"]], [14, 14, 14])

    def test_grinder_off_and_on_use_different_command(self):
        off = proto.build_brew_plan(pours=pours(80, 80, 80), dose=15, grinder_size=0)
        on = proto.build_brew_plan(pours=pours(80, 80, 80), dose=15, grinder_size=50)
        self.assertIn("recipe 8004", off[-2][0])
        self.assertIn("recipe 8001", on[-2][0])


class PatternTemperatureTests(unittest.TestCase):
    def test_pattern_wire_bytes(self):
        self.assertEqual(proto.PATTERN_WIRE["center"], 0)
        self.assertEqual(proto.PATTERN_WIRE["circular"], 1)
        self.assertEqual(proto.PATTERN_WIRE["spiral"], 2)

    def test_pattern_byte_lands_in_blob(self):
        centers = proto.encode_blob(pours(80, 80, 80, pattern="center"), 50, 15, 90)
        circles = proto.encode_blob(pours(80, 80, 80, pattern="circular"), 50, 15, 90)
        self.assertEqual(centers[3], 0)
        self.assertEqual(circles[3], 1)

    def test_temperature_sentinels(self):
        proto.encode_blob(pours(80, 80, 80, temperature=20), 50, 15, 90)   # RT
        proto.encode_blob(pours(80, 80, 80, temperature=98), 50, 15, 90)   # BP
        for bad in (19, 99, 100):
            with self.subTest(temp=bad), self.assertRaises(proto.ProtoError):
                proto.encode_blob(pours(80, 80, 80, temperature=bad), 50, 15, 90)

    def test_flow_and_pause_bounds(self):
        for bad in (2.9, 3.6, 7.0):
            with self.subTest(flow=bad), self.assertRaises(proto.ProtoError):
                proto.encode_blob(pours(80, 80, 80, flow=bad), 50, 15, 90)
        for bad in (-1, 60, 300):
            with self.subTest(pause=bad), self.assertRaises(proto.ProtoError):
                proto.encode_blob(pours(80, 80, 80, pause=bad), 50, 15, 90)

    def test_pour_count_limits(self):
        with self.assertRaises(proto.ProtoError):
            proto.encode_blob(pours(*[10] * 10), 50, 15, 90)


class SlotTests(unittest.TestCase):
    def test_slot_frame_shape(self):
        """写预设：类型 2、命令 11510、载荷 01|slot|flags|blob。"""
        blob = proto.encode_blob(pours(45, 65, 65, 65), 48, 15, 110)
        for index, name in enumerate("ABC"):
            with self.subTest(slot=name):
                frame = proto.slot_frame(blob, index)
                self.assertEqual(frame[2], 0x02)
                self.assertEqual(struct.unpack("<H", frame[3:5])[0], 11510)
                self.assertEqual(frame[10], 0x01)
                self.assertEqual(frame[11], index)
                self.assertEqual(frame[12], 0x12)          # 称重开
                self.assertEqual(frame[13:-2], blob)   # 末尾 2 字节是 CRC

    def test_slot_frame_rejects_bad_index(self):
        blob = proto.encode_blob(pours(80, 80, 80), 48, 15, 110)
        with self.assertRaises(proto.ProtoError):
            proto.slot_frame(blob, 3)


class RefusalTests(unittest.TestCase):
    def test_bits_decode_individually(self):
        cases = {0x000040: "no_water", 0x100000: "not_ready", 0x200000: "restore_incomplete",
                 0x400000: "recipe_rejected", 0x800000: "machine_busy"}
        for code, token in cases.items():
            with self.subTest(code=hex(code)):
                self.assertEqual(proto.refusal_reason(code)[0], token)

    def test_multi_bit_reads_as_first_known_condition(self):
        self.assertEqual(proto.refusal_reason(0x400040)[0], "no_water")

    def test_zero_is_not_a_refusal(self):
        self.assertIsNone(proto.refusal_reason(0))

    def test_dissect_ack_with_refusal(self):
        payload = bytes([0x58, 0x02, 0x07]) + struct.pack("<H", proto.CMD_RECIPE_GRIND) \
            + struct.pack("<I", 15) + bytes([0xC2]) + b"\x00\x00" + (0x400000).to_bytes(3, "big")
        packet = payload + struct.pack("<H", proto.crc16(payload))
        result = proto.dissect_reply(packet, error_offset=12)
        self.assertEqual(result["status"], "ack")
        self.assertEqual(result["refusal"], "recipe_rejected")

    def test_real_ack_12_bytes_has_no_refusal(self):
        """实测帧：8100 的 ACK 只有 12 字节、无 payload。不能凭空读出拒绝码。"""
        packet = bytes.fromhex("580207A41F0C000000C190B8")
        result = proto.dissect_reply(packet)
        self.assertEqual(result["code"], proto.CMD_HANDSHAKE)
        self.assertNotIn("refusal", result)

    def test_machine_info_is_not_mistaken_for_refusal(self):
        """实测 40521 帧的第 12-14 字节是序列号 ASCII，不是错误码。"""
        packet = bytes.fromhex(
            "580207499E43000000C14A313541303143343748303435FFFFFFFFFFFF"
            "5631322E30442E3430300037C64700000101500FDC0101413602000040B75A")
        self.assertNotIn("refusal", proto.dissect_reply(packet))

    def test_dissect_clean_ack(self):
        payload = bytes([0x58, 0x02, 0x07]) + struct.pack("<H", proto.CMD_EXECUTE) \
            + struct.pack("<I", 12) + bytes([0xC2])
        packet = payload + struct.pack("<H", proto.crc16(payload))
        self.assertNotIn("refusal", proto.dissect_reply(packet))


class PlanTests(unittest.TestCase):
    def test_plan_order_and_dose(self):
        plan = proto.build_brew_plan(pours=pours(45, 65, 65, 65), dose=15, grinder_size=50)
        labels = [label for label, _ in plan]
        self.assertTrue(labels[0].startswith("handshake"), labels)
        self.assertTrue(labels[1].startswith("back_home"), labels)
        self.assertTrue(labels[2].startswith("mode"), labels)
        self.assertIn("dose", labels[3])
        self.assertTrue(labels[4].startswith("set_cup"))
        self.assertTrue(labels[5].startswith("recipe 8001"))
        self.assertEqual(labels[6], "execute 8002")

        dose_frame = plan[3][1]
        dose_value = struct.unpack("<i", dose_frame[18:22])[0]
        self.assertEqual(dose_value, 15)

    def test_recipe_uses_type1_frame(self):
        """实测：配方帧用 Type 2 机器完全不回执，必须 Type 1。"""
        plan = proto.build_brew_plan(pours=pours(80, 80, 80), dose=15, grinder_size=50)
        recipe = [p for label, p in plan if label.startswith("recipe")][0]
        self.assertEqual(recipe[2], 0x01)

    def test_mode_frame_matches_capture(self):
        self.assertEqual(proto.mode_frame(auto=False).hex().upper(),
                         "580102F72C1000000001000000002A90")
        self.assertEqual(proto.mode_frame(auto=True).hex().upper(),
                         "580102F72C100000000191327856FF58")

    def test_plan_never_sends_8006(self):
        plan = proto.build_brew_plan(pours=pours(80, 80, 80), dose=15, grinder_size=50)
        for _, packet in plan:
            code = struct.unpack("<H", packet[3:5])[0]
            self.assertNotEqual(code, 8006)

    def test_cup_ranges(self):
        self.assertEqual(proto.CUP_WEIGHT_RANGE[2], (110.0, 90.0))   # Omni
        self.assertEqual(proto.CUP_WEIGHT_RANGE[3], (200.0, 80.0))   # Other


if __name__ == "__main__":
    unittest.main()
