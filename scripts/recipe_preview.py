#!/usr/bin/env python3
"""配方 JSON 离线校验与预览（纯标准库，不联网、不碰蓝牙）。

只做一件事：确认一份蓝牙配方 JSON 严格符合 Studio 的可执行范围，并算出一个
内容指纹。指纹用于"人看过的配方"和"待发送的配方"是同一份。

真正的帧编码在 scripts/xbloom_proto.py；本文件不发送任何命令。
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

MAX_BYTES = 65536


class PreviewError(ValueError):
    pass


def exact_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise PreviewError(f"{label} 必须且只能包含: {', '.join(keys)}")


def number(value, lo, hi, label, integer=False, tenth=False):
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not lo <= value <= hi
            or (integer and type(value) is not int)
            or (tenth and not math.isclose(value * 10, round(value * 10), abs_tol=1e-8))):
        raise PreviewError(f"{label} 必须是 {lo}..{hi} 之间的{'整数' if integer else '数值'}"
                           + ("，且为 0.1 的整数倍" if tenth else ""))


def validate(payload):
    """Studio 约束与协议编码约束的交集。不做任何静默夹取或四舍五入。"""
    exact_keys(payload, ("cupType", "doseGrams", "recipe"), "payload")
    if payload["cupType"] != "xdripper":
        raise PreviewError("当前 profile 只支持 xdripper / Omni Dripper")
    number(payload["doseGrams"], 5, 18, "doseGrams", tenth=True)
    recipe = payload["recipe"]
    exact_keys(recipe, ("grinderSize", "rpm", "grandWater", "pours"), "recipe")
    number(recipe["grinderSize"], 1, 80, "grinderSize", integer=True)
    if type(recipe["rpm"]) is not int or recipe["rpm"] not in (60, 70, 80, 90, 100, 110, 120):
        raise PreviewError("rpm 只能是 60/70/80/90/100/110/120")
    number(recipe["grandWater"], 40, 500, "grandWater", integer=True)
    pours = recipe["pours"]
    if not isinstance(pours, list) or not 3 <= len(pours) <= 5:
        raise PreviewError("pours 必须包含 3..5 段")
    for index, pour in enumerate(pours):
        label = f"pours[{index}]"
        exact_keys(pour, ("volume", "temperature", "flowRate", "pattern", "pausing",
                          "vibBefore", "vibAfter"), label)
        number(pour["volume"], 1, 300, f"{label}.volume", integer=True)
        number(pour["temperature"], 60, 98, f"{label}.temperature", integer=True)
        number(pour["flowRate"], 3.0, 3.5, f"{label}.flowRate", tenth=True)
        number(pour["pattern"], 0, 2, f"{label}.pattern", integer=True)
        number(pour["pausing"], 0, 59, f"{label}.pausing", integer=True)
        if type(pour["vibBefore"]) is not bool or type(pour["vibAfter"]) is not bool:
            raise PreviewError(f"{label} 的振动字段必须是布尔值")
    if sum(pour["volume"] for pour in pours) != recipe["grandWater"]:
        raise PreviewError("各段水量之和必须等于 grandWater")
    return payload


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PreviewError(f"JSON 出现重复键: {key}")
        result[key] = value
    return result


def load_recipe(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise PreviewError("配方文件超过 64 KiB")
    return validate(json.loads(raw, object_pairs_hook=unique_object))


def digest(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def preview(payload):
    return {
        "mode": "offline_preview",
        "recipe_sha256": digest(payload),
        "ratio": round(payload["recipe"]["grandWater"] / payload["doseGrams"], 3),
        "payload": payload,
        "pattern_mapping": {"0": "center", "1": "circular", "2": "spiral"},
        "note": "doseGrams 是准备说明，不是蓝牙剂量指令。未接触任何硬件。",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    preview_parser = commands.add_parser("preview")
    preview_parser.add_argument("file")
    args = parser.parse_args(argv)
    try:
        result = preview(load_recipe(args.file))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (PreviewError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
