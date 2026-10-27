"""配方 JSON 校验与预览的测试（不含任何网络或蓝牙行为）。"""

import contextlib
import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("recipe_preview", ROOT / "scripts/recipe_preview.py")
preview_mod = importlib.util.module_from_spec(SPEC)
sys.modules["recipe_preview"] = preview_mod
SPEC.loader.exec_module(preview_mod)


def recipe():
    return json.loads((ROOT / "examples/ethiopia-duwancho.recipe.json").read_text())


class RecipeTests(unittest.TestCase):
    def test_example_keeps_parameters(self):
        payload = recipe()
        self.assertEqual(preview_mod.validate(payload), payload)
        self.assertEqual(preview_mod.preview(payload)["ratio"], 16)
        self.assertEqual([p["pattern"] for p in payload["recipe"]["pours"]], [2, 2, 2, 1])

    def test_out_of_range_values_are_rejected_not_clamped(self):
        cases = [
            ("doseGrams", 19), ("doseGrams", 4), ("doseGrams", "15"), ("doseGrams", True),
            ("doseGrams", float("nan")), ("doseGrams", 15.05), ("cupType", "xpod"),
            ("recipe.grinderSize", 0), ("recipe.grinderSize", 81), ("recipe.grinderSize", 50.1),
            ("recipe.rpm", 95), ("recipe.rpm", "110"), ("recipe.grandWater", 501),
            ("recipe.grandWater", 239), ("recipe.pours", []),
            ("pour.flowRate", 0.5), ("pour.flowRate", 7), ("pour.flowRate", 3.15),
            ("pour.pausing", 60), ("pour.pausing", 300), ("pour.pausing", -1),
            ("pour.temperature", "BP"), ("pour.temperature", "RT"),
            ("pour.temperature", 59), ("pour.temperature", 99),
            ("pour.temperature", 92.5), ("pour.volume", True), ("pour.volume", 0),
            ("pour.pattern", 3), ("pour.pattern", True), ("pour.vibAfter", "false"),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                payload = recipe()
                if field.startswith("recipe."):
                    payload["recipe"][field.split(".")[1]] = value
                elif field.startswith("pour."):
                    payload["recipe"]["pours"][0][field.split(".")[1]] = value
                else:
                    payload[field] = value
                before = copy.deepcopy(payload)
                with self.assertRaises(preview_mod.PreviewError):
                    preview_mod.validate(payload)
                self.assertEqual(repr(payload), repr(before))

    def test_missing_extra_and_stored_confirmation_rejected(self):
        for modify in (
            lambda p: p.pop("doseGrams"),
            lambda p: p.update(confirmSafety=True),
            lambda p: p["recipe"].pop("rpm"),
            lambda p: p["recipe"]["pours"][0].update(extra="unknown"),
        ):
            payload = recipe()
            modify(payload)
            with self.assertRaises(preview_mod.PreviewError):
                preview_mod.validate(payload)

    def test_fingerprint_binds_content_not_key_order(self):
        payload = recipe()
        self.assertEqual(preview_mod.digest(payload),
                         preview_mod.digest(dict(reversed(list(payload.items())))))
        changed = copy.deepcopy(payload)
        changed["recipe"]["grinderSize"] = 52
        self.assertNotEqual(preview_mod.digest(payload), preview_mod.digest(changed))

    def test_duplicate_keys_and_oversize_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "recipe.json"
            for raw in ('{"doseGrams": 15, "doseGrams": 18}', " " * (preview_mod.MAX_BYTES + 1)):
                path.write_text(raw)
                with self.assertRaises(preview_mod.PreviewError):
                    preview_mod.load_recipe(path)

    def test_preview_never_touches_network(self):
        with patch("socket.create_connection", side_effect=AssertionError("网络被调用")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = preview_mod.main(["preview",
                                         str(ROOT / "examples/ethiopia-duwancho.recipe.json")])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["mode"], "offline_preview")


if __name__ == "__main__":
    unittest.main()
