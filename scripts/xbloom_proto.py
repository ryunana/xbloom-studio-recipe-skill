"""xBloom Studio 协议层参考实现（离线可验证，不含蓝牙传输）。

这个模块只做三件事：构造命令帧、把配方编码成机器要的 blob、解读机器的回复。
它不发蓝牙、不联网，因此可以完全离线逐字节验证——对齐实测报文即为通过。

依据：机器实际通信记录、机器实际反应，以及公开的协议笔记三方交叉核对，
全部整理在 references/device-facts.md。凡是不一致、或只出现在单一来源的结论，
注释里都标了"单源"，不当作确定事实使用。
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass

# --- 命令码（两处独立来源一致） -------------------------------------------------
CMD_HANDSHAKE = 8100        # 0x1FA4 握手 / MTU 协商，连接后必须先发
CMD_BACK_HOME = 8022        # 0x1F56 回主屏
CMD_BYPASS_DOSE = 8102      # 0x1FA6 旁通水量/温度 + 粉量（3 个 int）
CMD_SET_CUP = 8104          # 0x1FA8 杯型重量区间（2 个 float 位）
CMD_RECIPE_GRIND = 8001     # 0x1F41 配方 blob（含研磨）
CMD_RECIPE_NO_GRIND = 8004  # 0x1F44 配方 blob（不含研磨）
CMD_EXECUTE = 8002          # 0x1F42 执行配方
CMD_STOP = 4507             # 0x119B 停止
CMD_PAUSE = 8019            # 0x1F53 暂停（单源，未交叉确认，不可靠）
CMD_GRINDER_START = 3500    # 0x0DAC 手动研磨 [1000, size, rpm]
CMD_GRINDER_STOP = 3505     # 0x0DB1 停止研磨

# 握手载荷恒为 [185, 1]（官方 App 每次冲泡都发这一对，与研磨设置无关）
HANDSHAKE_DATA = (185, 1)

# 配方之外的固定帧：研磨起始帧第一个参数恒为 1000，官方 App 写死，不是时长
GRIND_START_CONST = 1000


# --- CRC16：多项式 0x8408（反转 CCITT），初值 0 --------------------------------
def crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def frame(code: int, ints=()) -> bytes:
    """Type 1 帧：58 01 01 [code LE] [len LE4] 01 [int32 LE × N] [crc LE]。"""
    body = bytearray([0x58, 0x01, 0x01])
    body += struct.pack("<H", code)
    body += struct.pack("<I", 12 + 4 * len(ints))
    body += b"\x01"
    for value in ints:
        body += struct.pack("<i", int(value))
    return bytes(body) + struct.pack("<H", crc16(bytes(body)))


def frame_payload(code: int, payload: bytes) -> bytes:
    """Type 1 帧 + 原始字节数据段——**配方帧必须走这条**。

    实测（2026-10-27 本机 V12.0D.400）：配方帧用 Type 2（58 01 02）机器完全不理，
    连回执都没有；换成 Type 1（58 01 01）+ 原始字节，8001/8004 都立刻回执。
    与官方 App 发出的格式一致（`58 01 01 44 1F ...`）。
    """
    body = bytearray([0x58, 0x01, 0x01])
    body += struct.pack("<H", code)
    body += struct.pack("<I", 12 + len(payload))
    body += b"\x01"
    body += payload
    return bytes(body) + struct.pack("<H", crc16(bytes(body)))


def frame_hex(code: int, payload: bytes) -> bytes:
    """Type 2 帧：数据段是原始字节 hex（模式切换 11511、槽位写入 11510 走这条）。"""
    body = bytearray([0x58, 0x01, 0x02])
    body += struct.pack("<H", code)
    body += struct.pack("<I", 12 + len(payload))
    body += b"\x01"
    body += payload
    return bytes(body) + struct.pack("<H", crc16(bytes(body)))


def float_bits(value: float) -> int:
    """Java Float.floatToIntBits 等价：把 float32 的位模式当无符号整数。"""
    return struct.unpack("<I", struct.pack("<f", float(value)))[0]


# --- 杯型与重量区间 -----------------------------------------------------------
# 官方 App 的 (theMax, theMin) 由云端按杯型下发，不是本地算的。
# Omni dripper (110, 90) 与 Other (200, 80) 已确认；xPod/Tea 只有默认值（单源）。
CUP_WEIGHT_RANGE = {
    1: (200.0, 80.0),   # xPod（默认值，未确认）
    2: (110.0, 90.0),   # Omni dripper（已确认）
    3: (200.0, 80.0),   # Other / Free Solo（已确认）
    4: (200.0, 80.0),   # Tea（默认值，未确认）
}
CUP_LABEL = {1: "xPod", 2: "Omni dripper", 3: "Other", 4: "Tea"}
DEFAULT_CUP = 2


# --- 注水模式：API 整数与线上字节是两套编号，不能互推 -------------------------
# 线上字节经机器语音播报确认：0=中心，1=环绕，2=螺旋。
PATTERN_WIRE = {"center": 0, "centered": 0, "circular": 1, "ring": 1, "spiral": 2}
PATTERN_NAMES = {0: "center", 1: "circular", 2: "spiral"}

# 温度：配方里存的是"线上域"，20 = RT，98 = BP，中间 40-95 是真实摄氏度。
ROOM_TEMP_C = 20
BOILING_POINT_C = 98


class ProtoError(ValueError):
    pass


@dataclass(frozen=True)
class Pour:
    volume: float
    temperature: float
    flow_rate: float
    pattern: int
    pause: int
    vib_before: bool = False
    vib_after: bool = False


def _f32(value: float) -> float:
    """按 float32 精度做一步运算——固件的配方校验用 float32。"""
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def consistent_volumes(volumes, dose: int):
    """让配方通过固件的"体积一致性"闸门，返回 (整数段水量, ratio 字节)。

    固件只有在 trunc((ratio/10) * dose) == Σ(段水量) 时才会提交配方（含研磨档位）。
    不满足时机器会用**上一次的研磨度**冲新配方——这就是所谓 grind-size bug。
    """
    total = sum(volumes)
    if dose <= 0 or total <= 0:
        raise ProtoError("必须提供粉量与总水量，否则无法计算 ratio 字节")
    ideal_ratio = int(round(total / dose * 10))
    chosen, target = None, None
    for candidate in (ideal_ratio, ideal_ratio + 1, ideal_ratio - 1,
                      ideal_ratio + 2, ideal_ratio - 2):
        if not 1 <= candidate <= 0xFF:
            continue
        product = _f32(_f32(_f32(candidate) / _f32(10.0)) * _f32(dose))
        if int(product) == int(product + 0.5):
            chosen, target = candidate, int(product)
            break
    if target is None:
        chosen = max(1, min(0xFF, ideal_ratio))
        target = int(_f32(_f32(_f32(chosen) / _f32(10.0)) * _f32(dose)))
    scaled = [v * target / total for v in volumes]
    ints = [int(v) for v in scaled]
    deficit = target - sum(ints)
    if deficit > 0:
        order = sorted(range(len(scaled)), key=lambda i: scaled[i] - ints[i], reverse=True)
        for i in order[:deficit]:
            ints[i] += 1
    return ints, chosen


def encode_blob(pours, grinder_size: int, dose: int, rpm: int) -> bytes:
    """编码配方 blob：长度前缀 + 每段数据 + [研磨度, ratio×10]。

    每段 = 注水区 (体积, 温度, 模式, 振动位) + 时序区 (驻留取负, 0, 首段 rpm, 流速×10)
    体积 >127 ml 会被拆成 127 的整数块（机器限制）。
    """
    if not 1 <= len(pours) <= 9:
        raise ProtoError("段数必须在 1 到 9 之间（机器上限 9 段）")
    volumes, ratio = consistent_volumes([p.volume for p in pours], dose)
    out = bytearray()
    for index, pour in enumerate(pours):
        if not ROOM_TEMP_C <= int(pour.temperature) <= BOILING_POINT_C:
            raise ProtoError(
                f"第 {index + 1} 段温度 {pour.temperature} 超出 {ROOM_TEMP_C}-{BOILING_POINT_C}"
                f"（{ROOM_TEMP_C}=RT，{BOILING_POINT_C}=BP，中间是真实摄氏度）")
        if not 3.0 - 1e-9 <= pour.flow_rate <= 3.5 + 1e-9:
            raise ProtoError(f"第 {index + 1} 段流速 {pour.flow_rate} 超出 3.0-3.5")
        if not 0 <= pour.pause <= 59:
            raise ProtoError(f"第 {index + 1} 段驻留 {pour.pause}s 超出 0-59")
        vibration = (1 if pour.vib_before else 0) | (2 if pour.vib_after else 0)
        volume = volumes[index]
        while volume > 127:
            out += bytes([127, int(pour.temperature), pour.pattern, vibration])
            volume -= 127
        out += bytes([volume, int(pour.temperature), pour.pattern, vibration])
        out += bytes([(-int(pour.pause)) & 0xFF, 0,
                      (int(rpm) & 0xFF) if index == 0 else 0,
                      int(round(pour.flow_rate * 10)) & 0xFF])
    return bytes([len(out) & 0xFF]) + bytes(out) + bytes([min(int(grinder_size), 80) & 0xFF, ratio & 0xFF])


def build_brew_plan(*, pours, dose: int, grinder_size: int = 0, rpm: int = 90,
                    cup: int = DEFAULT_CUP, bypass_volume: float = 0.0,
                    bypass_temp: float = 0.0):
    """返回 (标签, 帧字节) 序列：官方 App 的连接后冲泡顺序。

    顺序依据实测通信记录：握手 → 回主屏 → 旁通+粉量 → 杯型区间 → 配方 → 执行。
    注意：
    - 不先发握手，机器会在 BLE 层收下帧但完全不响应（不亮屏、无提示音、无回复）。
    - 粉量 8102 必须真的发出去：固件的配方闸门要用它算 ratio，漏了会导致研磨不提交。
    - 8006（进入研磨页）不要放进配方流程，会打乱机器状态。
    """
    plan = [("handshake 握手/MTU 8100", frame(CMD_HANDSHAKE, HANDSHAKE_DATA)),
            ("back_home 回主屏 8022", frame(CMD_BACK_HOME)),
            ("mode 切到 Pro 11511", mode_frame(False))]
    if bypass_volume or bypass_temp:
        plan.append(("bypass+dose 8102", frame(CMD_BYPASS_DOSE,
                                               [float_bits(bypass_volume),
                                                float_bits(bypass_temp), dose])))
    else:
        plan.append(("bypass off + dose 8102", frame(CMD_BYPASS_DOSE, [0, 0, dose])))
    the_max, the_min = CUP_WEIGHT_RANGE.get(cup, CUP_WEIGHT_RANGE[DEFAULT_CUP])
    plan.append((f"set_cup 8104 ({the_max:g}/{the_min:g})",
                 frame(CMD_SET_CUP, [float_bits(the_max), float_bits(the_min)])))
    blob = encode_blob(pours, grinder_size, dose, rpm)
    code = CMD_RECIPE_GRIND if grinder_size else CMD_RECIPE_NO_GRIND
    plan.append((f"recipe {code} ({len(blob)}B)", frame_payload(code, blob)))
    plan.append(("execute 8002", frame(CMD_EXECUTE)))
    return plan


CMD_SAVE_SLOT = 11510      # 写预设槽（A/B/C）
CMD_SLOT_ORDER = 11512     # 三槽写完后的排序收尾帧


def slot_frame(blob: bytes, slot: int, scale: bool = True) -> bytes:
    """把一份配方写进机器的预设槽：0=A，1=B，2=C。这不会冲煮。

    两条硬约束（来自机器实际行为）：
    - 机器**只接受三槽一起写**（A/B/C 连续发）。只写一个会让它卡在保存状态、屏幕显示 RETRY。
    - 机器里的现有预设**读不回来**。所以写 B 必然会覆盖 A 和 C，这一点必须提前告诉用户。
    """
    if slot not in (0, 1, 2):
        raise ProtoError("slot 只能是 0(A) / 1(B) / 2(C)")
    payload = bytes([0x01, slot, 0x12 if scale else 0x02]) + blob
    return frame_hex(CMD_SAVE_SLOT, payload)


def mode_frame(auto: bool) -> bytes:
    """11511 切换 Auto/Pro。Auto 模式下机器不接配置帧与配方帧（实测）。"""
    return frame_hex(11511, bytes.fromhex(MODE_PAYLOAD["auto" if auto else "pro"]))


MODE_PAYLOAD = {"auto": "91327856", "pro": "00000000"}


# --- 回复解读 -----------------------------------------------------------------
# 回复帧：58 02 07 [code LE] [len LE4] [status] [data...] [crc LE]
# status C1 = 周期状态上报，C2 = 对某条命令的 ACK。
# 被拒绝的命令同样会回自己的码，区别在 data 里 3 字节的大端错误码——是一个位域。
REFUSAL_BITS = (
    (0x000040, "no_water", "缺水"),
    (0x000800, "not_on_home_screen", "不在主屏，请先回到待机界面"),
    (0x001000, "not_on_home_screen", "不在主屏（同一原因的另一处）"),
    (0x100000, "not_ready", "未就绪（断电后遗留锁存，需重新上电/校准）"),
    (0x200000, "restore_incomplete", "恢复未完成（同上，另一个锁存）"),
    (0x400000, "recipe_rejected", "配方被拒：检查水量与分段设置"),
)
BUSY_BITS = (0x000100, 0x000200, 0x000400, 0x004000, 0x010000,
             0x020000, 0x040000, 0x080000, 0x800000)


def refusal_reason(code: int):
    """把 24 位错误码按位解释。必须按位读，不能按值比对——固件会把多个条件或起来。"""
    if not code:
        return None
    for bit, token, text in REFUSAL_BITS:
        if code & bit:
            return token, text
    for bit in BUSY_BITS:
        if code & bit:
            return "machine_busy", "机器忙或当前不接受该命令"
    return "unknown", f"未知拒绝码 0x{code:06X}"


def dissect_reply(packet: bytes, error_offset: int | None = None) -> dict:
    """把一条机器回复拆成 {code, status, refusal}。用于闭环判定，而不是靠 HTTP 200。

    回复帧：58 02 07 [code LE][len LE4][status][data...][crc LE]

    实测（2026-10-27，本机 V12.0D.400）：所有 ACK 都是 12 字节、无 payload，状态字节 C1。
    所以"第 12-14 字节是错误码"这条在 ACK 上不成立——照搬会把序列号、秤重等字节误判成拒绝。
    默认 error_offset=None 即不解析拒绝；确需解析时传入实测确认过的偏移。
    """
    if len(packet) < 12 or packet[0] != 0x58:
        raise ProtoError("不是有效回复帧")
    code = struct.unpack("<H", packet[3:5])[0]
    length = struct.unpack("<I", packet[5:9])[0]
    status = packet[9]
    result = {"code": code, "frame_type": packet[2],
              "status": {0xC1: "update", 0xC2: "ack"}.get(status, f"0x{status:02X}"),
              "payload_len": max(0, length - 12)}
    if error_offset is not None and len(packet) >= error_offset + 3:
        err = int.from_bytes(packet[error_offset:error_offset + 3], "big")
        if err:
            reason = refusal_reason(err)
            result["refusal_code"] = f"0x{err:06X}"
            result["refusal"] = reason[0] if reason else None
            result["refusal_text"] = reason[1] if reason else None
    return result


# --- 自检 ---------------------------------------------------------------------
# 这些是实测逐字节记录的真实帧，任何改动都必须仍然对齐。
CAPTURES = {
    "handshake": "580101A41F1400000001B900000001000000BDD1",
    "stop": "5801019B110C000000013643",
    "back_home": "580101561F0C00000001C015",
    "bypass_dose_16g": "580101A61F1800000001000000000000000010000000088C",
    "set_cup_200_80": "580101A81F1400000001000048430000A0422A0F",
}


def selfcheck() -> dict:
    wanted = {
        "handshake": frame(CMD_HANDSHAKE, HANDSHAKE_DATA),
        "stop": frame(CMD_STOP),
        "back_home": frame(CMD_BACK_HOME),
        "bypass_dose_16g": frame(CMD_BYPASS_DOSE, [0, 0, 16]),
        "set_cup_200_80": frame(CMD_SET_CUP, [float_bits(200.0), float_bits(80.0)]),
    }
    return {name: wanted[name].hex().upper() == hexv for name, hexv in CAPTURES.items()}


if __name__ == "__main__":
    import sys
    ok = selfcheck()
    print(json.dumps(ok, indent=2))
    sys.exit(0 if all(ok.values()) else 1)
