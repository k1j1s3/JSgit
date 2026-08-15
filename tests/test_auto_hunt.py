import importlib.util
import sys
import unittest
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw


MODULE_PATH = Path(__file__).parents[1] / "tools" / "ldplayer_auto_hunt.py"
SPEC = importlib.util.spec_from_file_location("ldplayer_auto_hunt", MODULE_PATH)
BOT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BOT
SPEC.loader.exec_module(BOT)


class AutoHuntDetectionTest(unittest.TestCase):
    def test_hp_measurement(self):
        image = Image.new("RGB", (100, 10), "black")
        ImageDraw.Draw(image).rectangle((0, 0, 59, 9), fill=(220, 20, 20))
        self.assertAlmostEqual(BOT.measure_hp(image, [0, 0, 100, 10]), 0.60, places=2)

    def test_requires_hp_drop_and_player_color(self):
        cfg = {
            "detection": {
                "hp_drop_window_seconds": 2.5,
                "minimum_hp_drop_ratio": 0.08,
                "minimum_cyan_pixels": 35,
                "minimum_hostile_magenta_pixels": 500,
                "safe_zone_cyan_pixels": 150,
            }
        }
        history = deque(
            [
                BOT.FrameState(1.0, 1.0, 60, 600, 0),
                BOT.FrameState(2.0, 0.90, 60, 600, 0),
            ]
        )
        self.assertTrue(BOT.detect_threat(history, cfg)[0])
        history[-1] = BOT.FrameState(2.0, 0.90, 5, 600, 0)
        self.assertFalse(BOT.detect_threat(history, cfg)[0])

    def test_safe_zone_suppresses_trigger(self):
        cfg = {
            "detection": {
                "hp_drop_window_seconds": 2.5,
                "minimum_hp_drop_ratio": 0.08,
                "minimum_cyan_pixels": 35,
                "minimum_hostile_magenta_pixels": 500,
                "safe_zone_cyan_pixels": 150,
            }
        }
        history = deque(
            [
                BOT.FrameState(1.0, 1.0, 60, 600, 0),
                BOT.FrameState(2.0, 0.80, 60, 600, 200),
            ]
        )
        self.assertFalse(BOT.detect_threat(history, cfg)[0])


if __name__ == "__main__":
    unittest.main()
