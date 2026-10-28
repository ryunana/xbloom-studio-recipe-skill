#!/usr/bin/env python3
"""从复核过的配方到真机出杯：连接 xBloom Studio，装载并（可选）启动冲煮。

四步，按顺序：
  1. 校验配方 JSON（scripts/recipe_preview.py）
  2. 打印要发送的每一帧与内容指纹（人看得见再发）
  3. 连接：订阅状态 → 握手（会重试一次）→ 读机器信息 → 回主屏 → 粉量 → 杯型 → 配方 [→ 执行]
  4. 听机器回话：ACK、拒绝码、分段序号、完成事件（40512）

用法：
  python3 scripts/xbloom_brew.py scan
  python3 scripts/xbloom_brew.py info
  python3 scripts/xbloom_brew.py brew --recipe recipes/current.json           # 干跑
  python3 scripts/xbloom_brew.py brew --recipe recipes/current.json --load    # 装载，不出水
  python3 scripts/xbloom_brew.py brew --recipe recipes/current.json --start   # 真冲
  python3 scripts/xbloom_brew.py grind --size 50                              # 空仓验证链路

安全边界：
  - 不带 --load / --start 时只打印帧，不连蓝牙。
  - --load 只把配方装载进机器，不发送执行帧；--start 才会真的出水。
  - 任何写入失败或超时都不自动重传：先看机器，再决定。

蓝牙细节来自机器实测与公开协议笔记交叉核对：
  - 写特征值 FFE1、通知特征值 FFE2，挂在标准 Bluetooth Base UUID 下（不是自定义服务 UUID）
  - 写必须是 Write Without Response
  - 握手帧 8100 [185,1] 发一次可能被机器忽略（GATT 重发现后首帧常被吞），必须重试
  - 机器靠广播里的自定义服务 UUID 标识自己，名字可能为空 → 两种都要认
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import recipe_preview  # noqa: E402
import xbloom_proto as proto  # noqa: E402

# 自定义服务（用于在广播里认出机器；名字可能是空的）
SERVICE_UUID = "0000e0ff-3c17-d293-8e48-14fe2e4da212"
# 真正的读写特征值挂在标准 Base UUID 下，这是三家实现一致的做法
CHAR_COMMAND = "0000ffe1-0000-1000-8000-00805f9b34fb"   # 写
CHAR_STATUS = "0000ffe2-0000-1000-8000-00805f9b34fb"    # 通知
NAME_HINT = "BLOOM"
FRAME_GAP = 0.4          # 帧间最小间隔，机器需要喘息
SETTLE_AFTER_SESSION = 2.0

EVENT_INFO = 40521       # 机器信息（序列号 / 固件 / 单位 / 模式）
EVENT_DONE = 40512       # RD_ENJOY：机器自己说冲完了
EVENT_STOPPED = {40511, 40519}
EVENT_NO_WATER = 40522
EVENT_FAULT = {8203: "磨盘位置异常", 8204: "投粉或水量异常"}
EVENT_POUR = 40510
EVENT_SLEEPING = 8009    # RD_MachineSleeping
EVENT_AWAKE = 8011       # RD_MachineNotSleeping


class Assembler:
    """机器可能把一帧拆成两条通知发，这里按长度字段拼回完整帧。

    帧头：58 02 07 [code LE2] [长度 LE4] … 长度含 12 字节头 + 2 字节 CRC。
    """

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes):
        self.buf.extend(data)
        frames = []
        while True:
            if len(self.buf) < 12:
                break
            if self.buf[0] != 0x58:
                del self.buf[0]
                continue
            declared = struct.unpack("<I", bytes(self.buf[5:9]))[0]
            if declared < 12 or declared > 4096:
                del self.buf[0]
                continue
            if len(self.buf) < declared:
                break
            frames.append(bytes(self.buf[:declared]))
            del self.buf[:declared]
        return frames


def looks_like_machine(name: str, service_uuids) -> bool:
    if NAME_HINT in (name or "").upper():
        return True
    return any(SERVICE_UUID in (u or "").lower() for u in (service_uuids or []))


def decode_machine_info(packet: bytes):
    """解 40521：序列号、固件版本、水箱/自来水、研磨度、模式。"""
    if len(packet) < 12 or struct.unpack("<H", packet[3:5])[0] != EVENT_INFO:
        return None
    declared = struct.unpack("<I", packet[5:9])[0]
    complete = len(packet) >= declared
    payload = packet[10:declared - 2] if complete else packet[10:]

    def ascii_of(start, end):
        chunk = payload[start:end]
        return "".join(chr(b) for b in chunk if 0x20 <= b < 0x7F).strip("\x00")

    info = {"serial": ascii_of(0, 13), "firmware": ascii_of(19, 29)}
    if len(payload) >= 34:
        info["water_ok"] = bool(payload[33])
    if len(payload) >= 37:
        info["water_source"] = "自来水" if payload[36] else "水箱"
    if len(payload) >= 38:
        info["grind_reported"] = max(payload[37] - 30, 1)
    if len(payload) >= 55:
        info["mode"] = "Auto" if payload[51:55].hex() == "91327856" else "Pro"
    return info



# --------------------------------------------------------------------------- #
# 面向普通用户的话术：不出现命令码、协议名、dBm
# --------------------------------------------------------------------------- #
EVENT_FAULT_PLAIN = {8203: "磨盘的定位不对", 8204: "粉量或水量不对"}
CUP_WEIGHT_FACTOR = 0.9634      # 93℃ 水密度：240 毫升 ≈ 231 克


def say(text=""):
    print(text)


def human_failure(exc: Exception) -> str:
    text = str(exc)
    if "没水" in text or "缺水" in text or "no_water" in text:
        return "机器说没水了。检查下水箱或水管，弄好之后跟我说一声，我重新开始。"
    if "没有扫到机器" in text:
        return ("找不到咖啡机。三件事：机器开着、屏幕亮着；手机上的官方 App 关掉"
                "（它连着时机器就不对外广播）；机器离电脑别太远。")
    if "握手" in text or "没有回显" in text:
        return "机器没回应。多半是手机 App 还连着，或者机器正在做别的事。把 App 关掉，等十来秒再叫我。"
    if "没有回执" in text:
        return "机器不接受这份配方。停在配方界面时它就不接新配方——按一下机器上的返回，再试一次。"
    if "必须" in text or "超出" in text or "pours" in text:
        return f"这份配方有一项参数不对：{text}"
    return f"出错了：{text}。先看一眼机器屏幕，把上面显示的告诉我。"


def write_run_log(payload, outcome, pours_seen, duration, session, note=None):
    """每次冲煮留一条记录。没有口感也能用：机器侧的数据本身就是证据。"""
    try:
        folder = Path(os.environ.get("XBLOOM_RUNS_DIR")
                      or (Path(__file__).resolve().parent.parent / "runs"))
        if not folder.is_dir():
            folder.mkdir(parents=True)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "outcome": outcome,
            "pours_observed": pours_seen,
            "pours_planned": len(payload["recipe"]["pours"]),
            "duration_s": round(duration, 1),
            "recipe": payload,
            "fingerprint": recipe_preview.digest(payload),
            "expected_cup_g": round(payload["recipe"]["grandWater"] * CUP_WEIGHT_FACTOR),
            "machine": session.info or {},
            "mode_before": session.initial_mode,
            "taste_note": note,
        }
        name = time.strftime("%Y%m%d-%H%M%S") + f"-{outcome}.json"
        (folder / name).write_text(json.dumps(record, ensure_ascii=False, indent=2))
        say(f"\n这次冲煮已记录：runs/{name}")
        if not note:
            say("（口感是选填的。你说一句，我就把这条记录补上，下次调整有据可依。）")
    except Exception as exc:  # noqa: BLE001
        say(f"（记录没写成功，不影响咖啡：{exc}）")


def to_pours(payload: dict):
    return [proto.Pour(volume=p["volume"], temperature=p["temperature"],
                       flow_rate=p["flowRate"], pattern=p["pattern"],
                       pause=p["pausing"], vib_before=p["vibBefore"],
                       vib_after=p["vibAfter"])
            for p in payload["recipe"]["pours"]]


def build(payload: dict):
    return proto.build_brew_plan(
        pours=to_pours(payload),
        dose=int(round(payload["doseGrams"])),
        grinder_size=int(payload["recipe"]["grinderSize"]),
        rpm=int(payload["recipe"]["rpm"]),
        cup=proto.DEFAULT_CUP,
    )


def show_plan(plan, payload, verbose=False):
    pours = payload["recipe"]["pours"]
    water = payload["recipe"]["grandWater"]
    say(f"{payload['doseGrams']:g} 克豆 / {water} 毫升水 / 研磨 {payload['recipe']['grinderSize']} / "
        f"{len(pours)} 段")
    say("  预计杯里约 %d 克（热水比冷水轻，这是正常的）" % round(water * CUP_WEIGHT_FACTOR))
    if verbose:
        say(f"  配方指纹 {recipe_preview.digest(payload)}")
        for label, packet in plan:
            say(f"  {label:<26} {len(packet):>3}B  {packet.hex().upper()}")
    say()


# --------------------------------------------------------------------------- #
# 蓝牙
# --------------------------------------------------------------------------- #
class Session:
    def __init__(self):
        self.events: asyncio.Queue = asyncio.Queue()
        self.info = None
        self.sleeping = None      # None = 未知，True/False 由 8009/8011 更新
        self._assembler = Assembler()

    def on_notify(self, _char, data: bytearray):
        for packet in self._assembler.feed(bytes(data)):
            self._handle(packet)

    def _handle(self, packet: bytes):
        info = decode_machine_info(packet)
        if info is not None:
            self.info = info
            self.events.put_nowait({"code": EVENT_INFO, "machine_info": info})
            return
        try:
            event = proto.dissect_reply(packet)
        except proto.ProtoError:
            self.events.put_nowait({"code": None, "raw": packet.hex().upper()})
            return
        code = event.get("code")
        if code == EVENT_SLEEPING:
            self.sleeping = True
        elif code == EVENT_AWAKE:
            self.sleeping = False
        self.events.put_nowait(event)

    async def wait_for(self, codes, timeout, allow_refusal=False):
        codes = {codes} if isinstance(codes, int) else set(codes)
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            try:
                event = await asyncio.wait_for(self.events.get(), timeout=left)
            except asyncio.TimeoutError:
                return None
            if event.get("refusal") and not allow_refusal:
                raise RuntimeError(f"机器拒绝了 {event['code']}：{event['refusal_text']}"
                                   f"（{event['refusal_code']}）")
            if event.get("code") in codes:
                return event


async def find_device(timeout=12.0, address=None, name=None):
    from bleak import BleakScanner
    if address:
        return address
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    found = []
    for device, adv in devices.values():
        label = adv.local_name or getattr(device, "name", None) or ""
        if looks_like_machine(label, adv.service_uuids) or (name and name.lower() in label.lower()):
            found.append((label or "(无名)", device))
    if not found:
        return None
    label, device = found[0]
    print(f"找到机器：{label}  {device.address}")
    return device


async def require_linked(args):
    """连上并完成握手。返回 (client, session)；失败抛异常。"""
    from bleak import BleakClient
    target = await find_device(getattr(args, "scan_timeout", 12.0), args.address, args.name)
    if target is None:
        raise RuntimeError(
            "没有扫到机器。请确认：机器已开机且屏幕亮着（睡眠时不广播）；手机 App 未占用连接；"
            "机器离电脑足够近。也可以先用 scan 子命令看列表里有没有名字带 BLOOM 的设备。")

    client = BleakClient(target, timeout=25)
    await client.connect()
    session = Session()
    session.initial_mode = None
    await client.start_notify(CHAR_STATUS, session.on_notify)

    acked = False
    for attempt in (1, 2):
        await client.write_gatt_char(CHAR_COMMAND,
                                     proto.frame(proto.CMD_HANDSHAKE, proto.HANDSHAKE_DATA),
                                     response=False)
        event = await session.wait_for({EVENT_INFO, proto.CMD_HANDSHAKE}, timeout=5)
        if event is not None:
            acked = True
            break
        if attempt == 2:
            await client.disconnect()
            raise RuntimeError("握手没有回应。通常是手机 App 还占着连接，或者机器还没醒。")
        print("握手没回应，重试一次（首帧常被机器吞掉）…")

    if acked and session.info is None:
        # 握手 ACK 通常先到，机器信息（40521）紧跟其后，单独等一下
        await session.wait_for(EVENT_INFO, timeout=5)

    if session.info:
        i = session.info
        session.initial_mode = i.get("mode")
        if getattr(args, "verbose", False):
            print(f"[机器] {i.get('serial')} 固件 {i.get('firmware')} 模式 {i.get('mode')} "
                  f"研磨 {i.get('grind_reported')}")
    else:
        print("握手成功，但没等到机器信息帧（不影响后续命令）。")
    return client, session


async def restore_mode(client, session, mode):
    """把机器切回冲煮前的模式。实测：必须先回主屏 + 退出配方界面，11511 才生效。"""
    if not mode or mode == "Pro":
        return
    try:
        await client.write_gatt_char(CHAR_COMMAND, proto.frame(proto.CMD_BACK_HOME), response=False)
        await asyncio.sleep(1.2)
        await client.write_gatt_char(CHAR_COMMAND, proto.frame(8017), response=False)
        await asyncio.sleep(0.8)
        await client.write_gatt_char(CHAR_COMMAND, proto.mode_frame(auto=(mode == "Auto")),
                                     response=False)
        await asyncio.sleep(2.0)
        await client.write_gatt_char(CHAR_COMMAND,
                                     proto.frame(proto.CMD_HANDSHAKE, proto.HANDSHAKE_DATA),
                                     response=False)
        fresh = await session.wait_for(EVENT_INFO, timeout=5)
        now = session.info.get("mode", "?") if session.info else "?"
        print(f"已把机器切回{mode}（机器现在报告：{now}）" if fresh
              else f"已请求切回{mode}，没读到确认，看一眼机器屏幕")
    except Exception as exc:  # noqa: BLE001
        print(f"切回 {mode} 模式失败：{exc}（机器可能停在 Pro 模式）")


async def run_brew(args):
    payload = recipe_preview.load_recipe(args.recipe)
    plan = build(payload)
    show_plan(plan, payload, verbose=getattr(args, 'verbose', False))

    if not (args.load or args.start):
        print("干跑结束：没有连接蓝牙。要装载加 --load，要真的出水加 --start。")
        return 0

    if not require_bluetooth(args.force):
        return 2

    client, session = await require_linked(args)
    started = time.monotonic()
    pours_plan = payload["recipe"]["pours"]
    outcome, pours_seen = "unknown", 0
    try:
        async def send_confirmed(label, packet, attempts=3, required=True):
            code = struct.unpack("<H", packet[3:5])[0]
            for attempt in range(1, attempts + 1):
                await client.write_gatt_char(CHAR_COMMAND, packet, response=False)
                event = await session.wait_for(code, timeout=3, allow_refusal=True)
                if event is not None:
                    if event.get("refusal") and args.verbose:
                        say(f"  机器拒绝：{event['refusal_text']}")
                    await asyncio.sleep(FRAME_GAP)
                    return True
                if code == proto.CMD_EXECUTE:
                    raise RuntimeError("启动指令没有回应。不要重发——先看机器，它可能已经开始。")
                if args.verbose:
                    say(f"  {label} 没有回显（第 {attempt} 次）")
            if required:
                raise RuntimeError(f"{label} 三次都没有回执，停止发送")
            return False

        if args.verbose:
            say("  正在准备机器…")
        await client.write_gatt_char(CHAR_COMMAND, plan[1][1], response=False)
        await asyncio.sleep(1.0)
        await send_confirmed(plan[2][0], plan[2][1], attempts=2, required=False)
        await asyncio.sleep(SETTLE_AFTER_SESSION)

        for label, packet in plan[3:]:
            if label.startswith("execute"):
                if not args.start:
                    say("配方已经装进机器了，还没放水。想冲的时候跟我说「开始」。")
                    return 0
                say("开始冲煮，手离开机器。")
                await asyncio.sleep(3)
            if args.verbose:
                say(f"  {label}")
            attempts = 1 if label.startswith("execute") else 3
            await send_confirmed(label, packet, attempts=attempts)

        say("")
        while time.monotonic() - started < args.timeout:
            try:
                event = await asyncio.wait_for(session.events.get(), timeout=5)
            except asyncio.TimeoutError:
                continue
            code = event.get("code")
            if code == EVENT_POUR:
                pours_seen += 1
                seg = pours_plan[min(pours_seen - 1, len(pours_plan) - 1)]
                say(f"  第 {pours_seen}/{len(pours_plan)} 段：{seg['volume']} 毫升，{seg['temperature']} 度")
            elif code == EVENT_NO_WATER:
                say("  机器说没水了。接好水再叫我。")
                outcome = "no_water"
                write_run_log(payload, outcome, pours_seen, time.monotonic() - started, session, args.note)
                return 1
            elif code in EVENT_FAULT:
                say(f"  机器报了个问题：{EVENT_FAULT_PLAIN[code]}。先别继续，看一眼机器。")
                outcome = "fault"
                write_run_log(payload, outcome, pours_seen, time.monotonic() - started, session, args.note)
                return 1
            elif code in EVENT_STOPPED:
                # 机器先报"停止"，约两秒后才报"完成"，不能据此判失败。
                # 但"完成"这条本身也会丢——信号弱时整条通知就没了（2026-10-28 实测到一次）。
                # 真正可靠的判据是"每一段都收到过注水事件"，那是机器主动报的。
                done = await session.wait_for(EVENT_DONE, timeout=8)
                if done is not None:
                    outcome = "completed"
                    break
                if pours_seen >= len(pours_plan):
                    say("  四段都注完了。最后那条完成信号没收到，但水已经出完，这杯是成的。")
                    outcome = "completed_no_signal"
                    break
                say("  咖啡机提前停了。看一眼杯里还有多少水，告诉我。")
                outcome = "stopped"
                write_run_log(payload, outcome, pours_seen, time.monotonic() - started, session, args.note)
                return 1
            elif code == EVENT_DONE:
                outcome = "completed"
                break

        if outcome == "completed":
            duration = time.monotonic() - started
            water = payload["recipe"]["grandWater"]
            say("")
            say(f"冲好了。用时 {int(duration // 60)} 分 {int(duration % 60)} 秒，{pours_seen} 段都注完了。")
            say(f"杯里大约 {round(water * CUP_WEIGHT_FACTOR)} 克——热水比冷水轻，不是 {water} 克，正常。")
            say("先别急着喝，烫。凉一点之后花香会更清楚。")
            say("")
            say("喝着偏酸、偏苦、还是太淡？说一句就行，下一杯我只改一个地方。")
            write_run_log(payload, outcome, pours_seen, duration, session, args.note)
            return 0

        say("")
        say("等太久，没等到机器说完成。看一眼机器屏幕和杯里有多少水，把看到的告诉我。")
        outcome = "timeout"
        write_run_log(payload, outcome, pours_seen, time.monotonic() - started, session, args.note)
        return 1
    finally:
        if args.start and session.initial_mode:
            await restore_mode(client, session, session.initial_mode)
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def run_info(args):
    if not require_bluetooth(args.force):
        return 2
    client, _session = await require_linked(args)
    await asyncio.sleep(1.0)
    await client.disconnect()
    return 0


async def run_grind(args):
    if not require_bluetooth(args.force):
        return 2
    client, session = await require_linked(args)
    try:
        async def send(packet):
            await client.write_gatt_char(CHAR_COMMAND, packet, response=False)
            await asyncio.sleep(FRAME_GAP)

        await send(proto.frame(proto.CMD_BACK_HOME))
        await asyncio.sleep(SETTLE_AFTER_SESSION)
        print(f"开始研磨：{args.size} 档 / {args.rpm} RPM / {args.seconds:.0f}s（空仓测试，不加水）")
        await send(proto.frame(8006, [args.size, args.rpm]))
        await send(proto.frame(proto.CMD_GRINDER_START,
                               [proto.GRIND_START_CONST, args.size, args.rpm]))
        await asyncio.sleep(args.seconds)
        await send(proto.frame(proto.CMD_GRINDER_STOP))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                event = await asyncio.wait_for(session.events.get(), timeout=1)
            except asyncio.TimeoutError:
                continue
            print(f"  机器：{event.get('code')} {event.get('name', '') or ''}".rstrip())
        print(f"已发停止。看两件事：磨盘是否转过；屏幕研磨度是否显示 {args.size}。")
        return 0
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def run_mode(args):
    """切换 Auto / Pro。Auto 模式不接配置帧与配方帧，真冲必须先切 Pro。"""
    if not require_bluetooth(args.force):
        return 2
    client, session = await require_linked(args)
    try:
        target = "Auto" if args.auto else "Pro"
        # 机器停在子页面时不接模式切换：先回主屏，再退出配方界面（实测缺 8017 切不动）
        await client.write_gatt_char(CHAR_COMMAND, proto.frame(proto.CMD_BACK_HOME),
                                     response=False)
        await asyncio.sleep(1.2)
        await client.write_gatt_char(CHAR_COMMAND, proto.frame(8017), response=False)
        await asyncio.sleep(0.8)
        await client.write_gatt_char(CHAR_COMMAND, proto.mode_frame(auto=args.auto),
                                     response=False)
        await asyncio.sleep(2.0)
        # 机器信息只在握手时上报一次，再握一次手才能读到最新状态
        await client.write_gatt_char(CHAR_COMMAND,
                                     proto.frame(proto.CMD_HANDSHAKE, proto.HANDSHAKE_DATA),
                                     response=False)
        fresh = await session.wait_for(EVENT_INFO, timeout=5)
        if fresh and session.info:
            print(f"已请求切到 {target}；机器现在报告：{session.info.get('mode', '?')}")
        else:
            print(f"已请求切到 {target}，但没读到最新状态；看一眼机器屏幕确认")
        return 0
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


CHECKLIST = """冲之前请确认这几件事（一分钟）：
  1. 滤纸已经放进滤杯，用热水冲一下更好（去纸味）
  2. 称好 {dose} 克咖啡豆，倒进豆仓
  3. 杯子放在滤杯正下方，摆正——别歪到一边，也别紧贴机身
  4. 水箱有水 / 水管通水
  5. 手机上的官方 App 已经关掉（它连着时机器不接电脑）
  放好之后跟我说一声，我就开始。"""


async def run_check(args):
    """体检 + 准备清单：全部用日常话讲，不出现命令码。"""
    if not require_bluetooth(args.force, announce=True):
        return 2
    payload = None
    if getattr(args, "recipe", None):
        try:
            payload = recipe_preview.load_recipe(args.recipe)
        except Exception as exc:  # noqa: BLE001
            say(f"配方读不出来：{exc}")
            return 1
    client, session = await require_linked(args)
    try:
        info = session.info or {}
        mode = info.get("mode", "不确定")
        say("")
        mode_plain = {"Auto": "自动模式（A/B/C 三个预设）", "Pro": "专业模式"}.get(mode, "待确认")
        say(f"机器连上了：{info.get('serial', '这台')}，现在在{mode_plain}。")
        if info.get("water_source") == "自来水":
            say("　水路：接的外接水管。")
        else:
            say(f"　水位：{'够用' if info.get('water_ok', True) else '偏低，记得加水'}。")
        say(f"　机器里当前研磨档位：{info.get('grind_reported', '读不到')}。")
        if info.get("mode") == "Auto":
            say("　（现在是自动模式（A/B/C 三个预设）。冲的时候我会临时切到专业模式，冲完切回来。）")
        say("")
        if payload:
            say(CHECKLIST.format(dose=f"{payload['doseGrams']:g}"))
        else:
            say("准备好了就跟我说一声。")
        return 0
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def run_save_slots(args):
    """把配方写进机器的 A/B/C 预设。写预设不是冲咖啡。"""
    payload = recipe_preview.load_recipe(args.recipe)
    blob = proto.encode_blob(to_pours(payload), int(payload["recipe"]["grinderSize"]),
                             int(round(payload["doseGrams"])), int(payload["recipe"]["rpm"]))
    frames = [(name, proto.slot_frame(blob, index, scale=not args.scale_off))
              for index, name in enumerate("ABC")]

    say("这一步是把配方存进机器的三个预设（A / B / C），不是冲咖啡。")
    say("有件事得先说清楚：机器要求三个预设一起写，而且读不回原来存的是什么。")
    say("所以写进去之后，A、B、C 三个都会变成同一份配方——你原来的预设会被覆盖。")

    if not args.yes:
        say("")
        say("现在只是预览，没有写进机器。确认要覆盖就加 --yes 再来一次。")
        for name, packet in frames:
            say(f"  预设 {name}：{len(packet)} 字节")
        return 0

    if not require_bluetooth(args.force):
        return 2
    client, session = await require_linked(args)
    try:
        async def send(packet, gap=0.6):
            await client.write_gatt_char(CHAR_COMMAND, packet, response=False)
            await asyncio.sleep(gap)

        say("")
        say("正在写入，别碰机器…")
        await send(proto.frame(proto.CMD_BACK_HOME), 1.0)
        await send(proto.frame(8017), 0.8)
        await send(proto.mode_frame(auto=False), 1.5)
        for name, packet in frames:
            await send(packet)
        await send(proto.frame(proto.CMD_SLOT_ORDER), 2.0)
        await restore_mode(client, session, "Auto")
        say("写好了。机器上转到 A / B / C 就能看到这三个预设。")
        return 0
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def run_scan(args):
    from bleak import BleakScanner
    if not require_bluetooth(args.force):
        return 2
    devices = await BleakScanner.discover(timeout=args.scan_timeout, return_adv=True)
    hits, others = [], []
    for device, adv in devices.values():
        label = adv.local_name or getattr(device, "name", None) or ""
        if looks_like_machine(label, adv.service_uuids):
            hits.append((label or "(无名，但广播了 xBloom 服务)", device.address, adv.rssi))
        else:
            others.append((label or "(无名)", device.address, adv.rssi))
    print(f"共扫到 {len(devices)} 个设备，其中疑似咖啡机 {len(hits)} 个：")
    for label, address, rssi in hits:
        print(f"  {label:<40} {address}  rssi={rssi}")
    if args.all:
        print("\n其余设备（信号强的排前面，机器不广播名字时可以从这里找）：")
        for label, address, rssi in sorted(others, key=lambda row: -(row[2] or -999)):
            print(f"  {label:<40} {address}  rssi={rssi}")
    if not hits:
        print("\n没找到。机器的屏幕亮着才会广播；按一下中间旋钮唤醒后再试。")
        return 2
    return 0


# --------------------------------------------------------------------------- #
# 本机蓝牙能力诊断：有没有硬件 → 开着没 → 有没有权限
#
# 这三件事的解法完全不同：没硬件要买适配器，没打开是点一个开关，没权限是去系统里授权。
# 混成一句"蓝牙不可用"，用户就只能猜。所以这里分三次判断，各给各的话。
# --------------------------------------------------------------------------- #

PLATFORM = sys.platform

PROBE_SRC = r'''
import asyncio, json, sys
out = {"import_ok": False, "scan": "not_run", "devices": 0, "error": "", "error_type": ""}
try:
    import bleak
except Exception as exc:
    out["error"] = "%s: %s" % (type(exc).__name__, exc)
    print(json.dumps(out))
    sys.exit(3)
out["import_ok"] = True
try:
    out["devices"] = len(asyncio.run(bleak.BleakScanner.discover(timeout=2.0)))
    out["scan"] = "ok"
except Exception as exc:
    out["scan"] = "failed"
    out["error"] = "%s: %s" % (type(exc).__name__, exc)
    out["error_type"] = type(exc).__name__
print(json.dumps(out))
'''


def platform_label() -> str:
    if PLATFORM == "darwin":
        return "macOS"
    if PLATFORM.startswith("win"):
        return "Windows"
    if PLATFORM.startswith("linux"):
        return "Linux"
    return PLATFORM


def _linux_rfkill_blocked() -> bool:
    """Linux 上蓝牙可能被 rfkill 关掉，这时设备节点还在但用不了。"""
    base = "/sys/class/rfkill"
    try:
        names = os.listdir(base)
    except OSError:
        return False
    for name in names:
        root = os.path.join(base, name)
        try:
            with open(os.path.join(root, "type"), encoding="utf-8") as fh:
                if fh.read().strip() != "bluetooth":
                    continue
            for flag in ("soft", "hard"):
                with open(os.path.join(root, flag), encoding="utf-8") as fh:
                    if fh.read().strip() == "1":
                        return True
        except OSError:
            continue
    return False


def adapter_state() -> tuple[str, str]:
    """有没有蓝牙适配器、开着没。返回 (ok|off|missing|unknown, 说明)。

    只查这台机器，不扫设备；查不出来就如实说 unknown，不猜。
    """
    if PLATFORM == "darwin":
        try:
            done = subprocess.run(["/usr/sbin/system_profiler", "SPBluetoothDataType"],
                                  capture_output=True, timeout=20)
        except Exception as exc:  # noqa: BLE001
            return "unknown", f"查不了系统蓝牙信息：{exc}"
        text = done.stdout.decode(errors="replace")
        if not text.strip():
            return "unknown", "系统没有返回蓝牙信息（可能被隐私设置挡住了）"
        low = text.lower()
        if "bluetooth controller" not in low and "控制器" not in text:
            return "missing", "系统信息里没有蓝牙控制器"
        if "state: on" in low or "状态：打开" in text or "状态: 打开" in text:
            return "ok", ""
        if "state: off" in low or "状态：关闭" in text or "状态: 关闭" in text:
            return "off", "蓝牙开关是关着的"
        return "ok", ""
    if PLATFORM.startswith("linux"):
        base = "/sys/class/bluetooth"
        if not os.path.isdir(base):
            return "missing", "系统里没有 /sys/class/bluetooth（没装 BlueZ，或没有适配器）"
        try:
            nodes = [n for n in os.listdir(base) if n.startswith("hci")]
        except OSError as exc:
            return "unknown", f"读不到蓝牙设备节点：{exc}"
        if not nodes:
            return "missing", "系统里没有蓝牙适配器"
        if _linux_rfkill_blocked():
            return "off", "蓝牙被 rfkill 关掉了"
        return "ok", ""
    # Windows 没有稳定可靠的命令行查法，交给 bleak 的报错文本判断
    return "unknown", ""


def probe_bluetooth() -> dict:
    """三件事各给一个结论：库、硬件、权限。"""
    diag = {"library": "ok", "adapter": "unknown", "permission": "unknown",
            "detail": "", "devices": 0, "platform": platform_label()}
    try:
        done = subprocess.run([sys.executable, "-c", PROBE_SRC],
                              capture_output=True, timeout=40)
    except Exception as exc:  # noqa: BLE001
        diag["detail"] = f"探测没启动起来：{exc}"
        return diag

    # 被信号杀掉：macOS 上就是"没给权限"的典型表现
    if done.returncode < 0 or done.returncode in (134, 137, 139):
        diag["permission"] = "denied"
        diag["detail"] = "系统在扫描时直接终止了进程（没有蓝牙权限的典型表现）"
        return diag

    payload: dict = {}
    for line in reversed(done.stdout.decode(errors="replace").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
                break
            except ValueError:
                continue

    if done.returncode == 3 or payload.get("import_ok") is False:
        diag["library"] = "missing"
        diag["detail"] = payload.get("error") or "这个 Python 没有蓝牙库"
        return diag

    if payload.get("scan") == "ok":
        diag["permission"] = "ok"
        diag["adapter"] = "ok"
        diag["devices"] = payload.get("devices", 0)
        # 一台设备都扫不到时，再确认一次是不是蓝牙根本没开。
        # 有些系统在权限被静默拒绝时不报错、只返回空列表，这里能兜住。
        if diag["devices"] == 0:
            state, note = adapter_state()
            if state in ("off", "missing"):
                diag["adapter"] = state
                diag["detail"] = note or "扫不到任何蓝牙设备"
        return diag

    text = " ".join([payload.get("error") or "", done.stderr.decode(errors="replace")])
    low = text.lower()
    if any(key in low for key in ("no bluetooth", "adapter", "not available", "no radio")):
        diag["adapter"] = "missing"
    elif any(key in low for key in ("unauthor", "denied", "permission", "not permitted")):
        diag["permission"] = "denied"
    diag["detail"] = payload.get("error") or text.strip()[:200] or "系统没给原因"
    return diag


def open_privacy_settings() -> bool:
    """把用户送到该开的那个设置页；送不到就当没做，不报错。"""
    try:
        if PLATFORM == "darwin":
            done = subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Bluetooth"],
                capture_output=True, timeout=10)
            return done.returncode == 0
        if PLATFORM.startswith("win"):
            done = subprocess.run(["cmd", "/c", "start", "", "ms-settings:privacy-bluetooth"],
                                  capture_output=True, timeout=10)
            return done.returncode == 0
    except Exception:  # noqa: BLE001
        pass
    return False


def bluetooth_help(diag: dict, settings_opened: bool = False) -> str:
    """把诊断翻译成"下一步做什么"。不出现 bleak、TCC、MTU 这类词。"""
    if diag["library"] == "missing":
        return (f"还差一个蓝牙库才能连机器。装它只要一行：\n"
                f"  {sys.executable} -m pip install bleak\n"
                "  如果提示 externally-managed 或权限不够，就建个虚拟环境：\n"
                "    python3 -m venv .venv && .venv/bin/pip install bleak\n"
                "\n只想先看要发什么的话，不加 --load / --start 就能跑，不需要这个库。")

    if diag["adapter"] == "missing":
        return ("这台电脑没有蓝牙，所以连不上咖啡机。\n"
                "  台式机很常见：主板没带蓝牙，也没插适配器。\n"
                "\n两条路，任选：\n"
                "  1. 插一个 USB 蓝牙适配器（要支持低功耗蓝牙，也就是 4.0 以上；几十块，插上就能用）\n"
                "  2. 不连机器也能用：让我把配方生成好，你在手机官方 App 里手动填。\n"
                "     配方能力不需要蓝牙，这一步本来就是零依赖的。")

    if diag["adapter"] == "off":
        where = {"macOS": "菜单栏右上角的蓝牙图标 → 打开蓝牙；或「系统设置 → 蓝牙」",
                 "Windows": "设置 → 蓝牙和其他设备 → 打开蓝牙",
                 "Linux": "sudo rfkill unblock bluetooth"}.get(diag["platform"], "系统设置里打开蓝牙")
        # detail 有时只是把"关着"说第二遍，那就别重复；有额外原因（rfkill 之类）才显示
        extra = (diag.get("detail") or "").strip()
        reason = f"\n  原因：{extra}" if extra and extra != "蓝牙开关是关着的" else ""
        return (f"这台电脑的蓝牙是关着的。{reason}\n"
                f"  {where}\n"
                "打开之后回来再跑一次。")

    if diag["permission"] == "denied":
        opened = ("我已经帮你打开了那个设置页。" if settings_opened
                  else "打开：设置 → 隐私与安全性 → 蓝牙（macOS）／设置 → 隐私和安全性 → 蓝牙（Windows）")
        return ("系统不让这个程序用蓝牙。\n"
                "  原因：蓝牙权限是按「程序」给的，不是按「用户」。而且系统通常只允许应用在\n"
                "        第一次使用时申请一次；被拒绝过之后不会再弹窗，只能手动打开。\n"
                f"\n怎么办：\n"
                f"  1. {opened}\n"
                "  2. 在列表里找到你现在用的那个程序（终端 / iTerm / WorkBuddy / VS Code…），把开关打开\n"
                "  3. 完全退出那个程序再打开（权限只在启动时读一次），然后重跑这条命令\n"
                "\n注意：在终端里能跑、在某个应用里跑不了，是因为两个程序是不同的东西，要分别授权。\n"
                "      第一次运行时系统会弹一次授权框，那是正常的，点允许。\n"
                "\n修好之前，配方照样能生成，只是没法替你冲这一杯。")

    platform_hint = {
        "macOS": "系统设置 → 蓝牙，看开关是否打开；再看 隐私与安全性 → 蓝牙",
        "Windows": "设置 → 蓝牙和其他设备；再看 设置 → 隐私和安全性 → 蓝牙",
        "Linux": "systemctl status bluetooth；再看当前用户是否在 bluetooth 组",
    }.get(diag["platform"], "系统设置里检查蓝牙")
    return (f"试不出这台电脑的蓝牙状态（{diag['detail'] or '系统没给原因'}）。\n"
            f"  自查：{platform_hint}\n"
            "  如果蓝牙确实正常，可能是这台机器上还有别的程序连着咖啡机，先退出手机 App 和\n"
            "  任何后台的蓝牙工具，再跑一次。")


def require_bluetooth(force: bool = False, announce: bool = False) -> bool:
    """连机器之前先确认这台电脑能用蓝牙。诊断结果直接给用户看。"""
    if force:
        return True
    diag = probe_bluetooth()
    healthy = (diag["library"] == "ok" and diag["adapter"] == "ok"
               and diag["permission"] == "ok")
    if healthy:
        if announce:
            print(f"蓝牙：可用（{diag['platform']}，本机蓝牙正常）")
        return True

    # 权限被拒时，顺手把设置页打开——用户不用自己去找
    settings_opened = False
    if diag["permission"] == "denied":
        settings_opened = open_privacy_settings()

    print(bluetooth_help(diag, settings_opened), file=sys.stderr)
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("--address", default=None, help="直接指定设备地址，跳过扫描")
        p.add_argument("--name", default=None, help="按名字片段指定设备")
        p.add_argument("--scan-timeout", type=float, default=12.0)
        p.add_argument("--force", action="store_true", help="跳过蓝牙权限探测")

    save = sub.add_parser("save-slots", help="把配方存进机器的 A/B/C 预设（会覆盖原有预设）")
    save.add_argument("--recipe", required=True)
    save.add_argument("--scale-off", action="store_true", help="预设里关掉称重")
    save.add_argument("--yes", action="store_true", help="真的写入（不加只预览）")
    add_common(save)
    save.set_defaults(func=run_save_slots)

    check = sub.add_parser("check", help="冲之前的体检与准备清单（人话）")
    check.add_argument("--recipe", default=None)
    add_common(check)
    check.set_defaults(func=run_check)

    scan = sub.add_parser("scan", help="列出疑似咖啡机的设备")
    scan_all_help = "连无关设备也列出来（机器不广播名字时用来人工找）"
    add_common(scan)
    scan.add_argument("--all", action="store_true", help=scan_all_help)
    scan.set_defaults(func=run_scan)

    mode = sub.add_parser("mode", help="切换 Auto / Pro 模式")
    group = mode.add_mutually_exclusive_group(required=True)
    group.add_argument("--auto", action="store_true", help="切到 Auto（面板 A/B/C 预设）")
    group.add_argument("--pro", action="store_true", help="切到 Pro（可接临时配方）")
    add_common(mode)
    mode.set_defaults(func=run_mode)

    info = sub.add_parser("info", help="连上并读机器信息（不出水、不磨豆）")
    add_common(info)
    info.set_defaults(func=run_info)

    brew = sub.add_parser("brew", help="装载 / 启动一份复核过的配方")
    brew.add_argument("--recipe", required=True)
    brew.add_argument("--load", action="store_true", help="只装载，不启动")
    brew.add_argument("--start", action="store_true", help="装载并启动（会真的出水）")
    brew.add_argument("--timeout", type=float, default=300.0, help="等待完成事件的秒数")
    brew.add_argument("--note", default=None, help="这一杯的口感备注（选填），会写进出杯记录")
    brew.add_argument("--verbose", action="store_true", help="显示协议细节（给技术排查用）")
    add_common(brew)
    brew.set_defaults(func=run_brew)

    grind = sub.add_parser("grind", help="空仓研磨测试（验证链路，不耗豆不耗水）")
    grind.add_argument("--size", type=int, default=50)
    grind.add_argument("--rpm", type=int, default=100)
    grind.add_argument("--seconds", type=float, default=3.0)
    add_common(grind)
    grind.set_defaults(func=run_grind)

    args = parser.parse_args(argv)
    try:
        return asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("\n已中断。若正在冲煮，先看机器，不要重发。", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print("")
        print(human_failure(exc))
        if "--verbose" in (argv or sys.argv):
            print(f"（技术细节：{exc}）", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
