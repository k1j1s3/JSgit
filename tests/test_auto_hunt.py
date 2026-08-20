import importlib.util
import json
import sys
import unittest
from collections import deque
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw


MODULE_PATH = Path(__file__).parents[1] / "tools" / "ldplayer_auto_hunt.py"
SPEC = importlib.util.spec_from_file_location("ldplayer_auto_hunt", MODULE_PATH)
BOT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BOT
SPEC.loader.exec_module(BOT)


class AutoHuntDetectionTest(unittest.TestCase):
    def test_test_emulator_inherits_calibrated_actions_but_keeps_own_flags(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        test_device = BOT.resolve_device_config(config, config["devices"][1])
        self.assertEqual("emulator-5556", test_device["device"])
        self.assertTrue(test_device["actions_enabled"])
        self.assertFalse(test_device["world_boss"]["enabled"])
        self.assertEqual(config["devices"][0]["town_actions"], test_device["town_actions"])
        self.assertEqual(config["devices"][0]["hunting_routes"], test_device["hunting_routes"])
        self.assertEqual(1, len(test_device["hunting_routes"]))
        self.assertEqual(
            "03-dragon-valley-dungeon-central-entrance",
            test_device["hunting_routes"][0]["name"],
        )

    def test_hunting_routes_open_map_from_minimap_without_opening_skill_menu(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        routes = config["devices"][0]["hunting_routes"]
        for route in routes:
            first = route["actions"][0]
            self.assertEqual("tap", first["type"])
            self.assertEqual([1155, 205], first["point"])
            self.assertIn("directly", first["label"])

    def test_recovery_runs_town_actions_before_hunting_route(self):
        cfg = {
            "return_actions": [{"type": "tap", "point": [1, 1]}],
            "town_actions": [{"type": "tap", "point": [2, 2]}],
            "hunting_routes": [
                {"name": "route", "actions": [{"type": "tap", "point": [3, 3]}]}
            ],
        }
        logger = Mock()
        with patch.object(BOT, "execute_actions") as execute:
            route = BOT.recover_and_resume("adb", "device", cfg, logger)

        self.assertEqual(route["name"], "route")
        self.assertEqual(
            [call.args[2] for call in execute.call_args_list],
            [cfg["return_actions"], cfg["town_actions"], cfg["hunting_routes"][0]["actions"]],
        )

    def test_quest_recovery_never_runs_normal_hunting_route(self):
        cfg = {
            "return_actions": [{"type": "tap", "point": [1, 1]}],
            "town_actions": [{"type": "tap", "point": [2, 2]}],
            "hunting_routes": [{"name": "wrong", "actions": [{"type": "tap", "point": [3, 3]}]}],
        }
        with patch.object(BOT, "execute_actions") as execute:
            BOT.recover_quest_to_town("adb", "device", cfg, Mock())
        self.assertEqual([cfg["return_actions"], cfg["town_actions"]], [call.args[2] for call in execute.call_args_list])

    def test_quest_mode_requires_explicit_enabled_marker(self):
        marker = BOT.ROOT / "data" / "auto-hunt" / "test-quest-mode.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        try:
            marker.write_text('{"mode":"daily-quests"}', encoding="utf-8")
            self.assertFalse(BOT.quest_mode_enabled({"quest_mode_marker": str(marker.relative_to(BOT.ROOT))}))
            marker.write_text('{"enabled":true,"mode":"daily-quests"}', encoding="utf-8")
            self.assertTrue(BOT.quest_mode_enabled({"quest_mode_marker": str(marker.relative_to(BOT.ROOT))}))
        finally:
            marker.unlink(missing_ok=True)

    def test_auto_active_requires_orange_ring(self):
        inactive = Image.new("RGB", (80, 90), (40, 40, 40))
        active = inactive.copy()
        ImageDraw.Draw(active).rectangle((0, 0, 29, 29), fill=(220, 110, 20))

        self.assertFalse(BOT.is_auto_active(inactive, [0, 0, 80, 90], 500))
        self.assertTrue(BOT.is_auto_active(active, [0, 0, 80, 90], 500))

    def test_close_overlay_detection_requires_red_close_button(self):
        field = Image.new("RGB", (70, 70), (40, 40, 40))
        menu = field.copy()
        ImageDraw.Draw(menu).rectangle((10, 10, 30, 30), fill=(180, 35, 35))
        self.assertFalse(BOT.is_close_overlay_open(field, [0, 0, 70, 70]))
        self.assertTrue(BOT.is_close_overlay_open(menu, [0, 0, 70, 70]))

    def test_reference_verification_distinguishes_shop_from_warehouse(self):
        shop = Image.open(BOT.ROOT / "data/auto-hunt/town-general-merchant.png").convert("RGB")
        shop_after = Image.open(BOT.ROOT / "data/auto-hunt/town-auto-purchase-confirmed.png").convert("RGB")
        warehouse = Image.open(BOT.ROOT / "data/auto-hunt/warehouse-interaction.png").convert("RGB")
        regions = [[1000, 10, 1200, 75], [0, 80, 390, 550], [900, 610, 1245, 690]]
        self.assertGreater(BOT.reference_similarity(shop_after, shop, regions), 0.99)
        self.assertLess(BOT.reference_similarity(warehouse, shop, regions), 0.97)

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
                "minimum_pvp_red_pixels": 500,
                "safe_zone_cyan_pixels": 150,
                "legacy_pvp_detection_enabled": True,
            }
        }
        history = deque(
            [
                BOT.FrameState(1.0, 1.0, 60, 600, 600, 0),
                BOT.FrameState(2.0, 0.90, 60, 600, 600, 0),
            ]
        )
        self.assertTrue(BOT.detect_threat(history, cfg)[0])
        history[-1] = BOT.FrameState(2.0, 0.90, 5, 600, 600, 0)
        self.assertFalse(BOT.detect_threat(history, cfg)[0])

    def test_safe_zone_suppresses_trigger(self):
        cfg = {
            "detection": {
                "hp_drop_window_seconds": 2.5,
                "minimum_hp_drop_ratio": 0.08,
                "minimum_cyan_pixels": 35,
                "minimum_hostile_magenta_pixels": 500,
                "minimum_pvp_red_pixels": 500,
                "safe_zone_cyan_pixels": 150,
                "legacy_pvp_detection_enabled": True,
            }
        }
        history = deque(
            [
                BOT.FrameState(1.0, 1.0, 60, 600, 0, 0),
                BOT.FrameState(2.0, 0.80, 60, 600, 0, 200),
            ]
        )
        self.assertFalse(BOT.detect_threat(history, cfg)[0])

    def test_pvp_indicator_triggers_despite_small_hp_drop(self):
        cfg = {
            "detection": {
                "hp_drop_window_seconds": 2.5,
                "minimum_hp_drop_ratio": 0.025,
                "minimum_cyan_pixels": 900,
                "minimum_hostile_magenta_pixels": 500,
                "minimum_pvp_red_pixels": 500,
                "safe_zone_cyan_pixels": 150,
                "legacy_pvp_detection_enabled": True,
            }
        }
        history = deque(
            [
                BOT.FrameState(1.0, 1.0, 1000, 600, 0, 0),
                BOT.FrameState(2.0, 0.995, 1000, 600, 800, 0),
            ]
        )
        self.assertTrue(BOT.detect_threat(history, cfg)[0])

    def test_loading_frame_with_zero_hp_does_not_trigger(self):
        cfg = {
            "detection": {
                "hp_drop_window_seconds": 2.5,
                "minimum_hp_drop_ratio": 0.025,
                "minimum_cyan_pixels": 900,
                "minimum_hostile_magenta_pixels": 2500,
                "minimum_pvp_red_pixels": 500,
                "safe_zone_cyan_pixels": 150,
            }
        }
        history = deque(
            [
                BOT.FrameState(1.0, 1.0, 0, 0, 0, 0),
                BOT.FrameState(2.0, 0.0, 0, 0, 0, 0),
            ]
        )
        self.assertFalse(BOT.detect_threat(history, cfg)[0])

    def test_low_hp_from_monsters_triggers_without_player_colors(self):
        cfg = {
            "detection": {
                "hp_drop_window_seconds": 2.5,
                "minimum_hp_drop_ratio": 0.025,
                "minimum_cyan_pixels": 900,
                "minimum_hostile_magenta_pixels": 2500,
                "minimum_pvp_red_pixels": 500,
                "safe_zone_cyan_pixels": 150,
                "emergency_hp_ratio": 0.20,
            }
        }
        history = deque([BOT.FrameState(1.0, 0.20, 0, 0, 0, 0), BOT.FrameState(2.0, 0.20, 0, 0, 0, 0)])
        self.assertTrue(BOT.detect_threat(history, cfg)[0])

    def test_low_hp_does_not_trigger_in_safe_zone(self):
        cfg = {
            "detection": {
                "hp_drop_window_seconds": 2.5,
                "minimum_hp_drop_ratio": 0.025,
                "minimum_cyan_pixels": 900,
                "minimum_hostile_magenta_pixels": 2500,
                "minimum_pvp_red_pixels": 500,
                "safe_zone_cyan_pixels": 150,
                "emergency_hp_ratio": 0.20,
            }
        }
        history = deque([BOT.FrameState(1.0, 0.20, 0, 0, 0, 200), BOT.FrameState(2.0, 0.20, 0, 0, 0, 200)])
        self.assertFalse(BOT.detect_threat(history, cfg)[0])

    def test_monster_damage_above_twenty_percent_does_not_trigger(self):
        cfg = {
            "detection": {
                "hp_drop_window_seconds": 2.5,
                "minimum_hp_drop_ratio": 0.025,
                "minimum_cyan_pixels": 900,
                "minimum_hostile_magenta_pixels": 2500,
                "minimum_pvp_red_pixels": 500,
                "safe_zone_cyan_pixels": 150,
                "emergency_hp_ratio": 0.20,
            }
        }
        history = deque([BOT.FrameState(1.0, 0.21, 0, 0, 0, 0)])
        self.assertFalse(BOT.detect_threat(history, cfg)[0])

    def test_already_below_five_percent_still_triggers_emergency_return(self):
        cfg = {"detection": {"hp_drop_window_seconds": 2.5, "minimum_hp_drop_ratio": 0.025, "minimum_cyan_pixels": 900, "minimum_hostile_magenta_pixels": 2500, "minimum_pvp_red_pixels": 500, "safe_zone_cyan_pixels": 150, "emergency_hp_ratio": 0.20}}
        history = deque([BOT.FrameState(1.0, 0.04, 0, 0, 0, 0), BOT.FrameState(2.0, 0.04, 0, 0, 0, 0)])
        self.assertTrue(BOT.detect_threat(history, cfg)[0])

    def test_monster_pack_colors_and_hp_drop_do_not_trigger_without_pvp_ui(self):
        cfg = {"detection": {"hp_drop_window_seconds": 2.5, "minimum_hp_drop_ratio": 0.025, "minimum_cyan_pixels": 900, "minimum_hostile_magenta_pixels": 2500, "minimum_pvp_red_pixels": 500, "safe_zone_cyan_pixels": 150, "emergency_hp_ratio": 0.20}}
        history = deque([
            BOT.FrameState(1.0, 0.991, 7079, 2698, 3, 0),
            BOT.FrameState(2.0, 0.961, 7079, 2698, 3, 0),
        ])
        self.assertFalse(BOT.detect_threat(history, cfg)[0])

    def test_pvp_detection_can_be_disabled_during_stabilization(self):
        cfg = {"detection": {"hp_drop_window_seconds": 2.5, "minimum_hp_drop_ratio": 0.025, "minimum_cyan_pixels": 900, "minimum_hostile_magenta_pixels": 2500, "minimum_pvp_red_pixels": 500, "safe_zone_cyan_pixels": 150, "emergency_hp_ratio": 0.20, "pvp_detection_enabled": False}}
        history = deque([
            BOT.FrameState(1.0, 0.80, 9000, 12000, 2000, 0),
            BOT.FrameState(2.0, 0.70, 9000, 12000, 2000, 0),
        ])
        self.assertFalse(BOT.detect_threat(history, cfg)[0])

    def test_real_pk_signature_from_incident_triggers_after_two_frames(self):
        cfg = {"detection": {"hp_drop_window_seconds": 2.5, "minimum_hp_drop_ratio": 0.025, "minimum_cyan_pixels": 900, "minimum_hostile_magenta_pixels": 2500, "minimum_pvp_red_pixels": 500, "safe_zone_cyan_pixels": 150, "critical_hp_ratio": 0.15, "emergency_hp_ratio": 0.25, "emergency_confirm_frames": 2, "pvp_detection_enabled": True, "strong_pvp_red_pixels": 2000, "strong_pvp_confirm_frames": 2}}
        history = deque([
            BOT.FrameState(1.0, 1.0, 4120, 3857, 2693, 0),
            BOT.FrameState(2.0, 1.0, 3454, 3519, 3186, 0),
        ])
        triggered, reason = BOT.detect_threat(history, cfg)
        self.assertTrue(triggered)
        self.assertIn("strong-pvp-confirmed", reason)

    def test_previous_1076_red_pixel_false_positive_does_not_trigger(self):
        cfg = {"detection": {"hp_drop_window_seconds": 2.5, "minimum_hp_drop_ratio": 0.025, "minimum_cyan_pixels": 900, "minimum_hostile_magenta_pixels": 2500, "minimum_pvp_red_pixels": 500, "safe_zone_cyan_pixels": 150, "critical_hp_ratio": 0.15, "emergency_hp_ratio": 0.25, "emergency_confirm_frames": 2, "pvp_detection_enabled": True, "strong_pvp_red_pixels": 2000, "strong_pvp_confirm_frames": 2}}
        history = deque([
            BOT.FrameState(1.0, 0.589, 3348, 1930, 493, 0),
            BOT.FrameState(2.0, 0.584, 2991, 2866, 1076, 0),
        ])
        self.assertFalse(BOT.detect_threat(history, cfg)[0])

    def test_critical_hp_triggers_on_first_valid_frame(self):
        cfg = {"detection": {"hp_drop_window_seconds": 2.5, "minimum_hp_drop_ratio": 0.025, "minimum_cyan_pixels": 900, "minimum_hostile_magenta_pixels": 2500, "minimum_pvp_red_pixels": 500, "safe_zone_cyan_pixels": 150, "critical_hp_ratio": 0.15, "emergency_hp_ratio": 0.25, "emergency_confirm_frames": 2}}
        self.assertTrue(BOT.detect_threat(deque([BOT.FrameState(1.0, 0.10, 0, 0, 0, 0)]), cfg)[0])

    def test_quest_mode_ignores_combat_color_false_positive_above_twenty_percent(self):
        cfg = {"detection": {"hp_drop_window_seconds": 2.5, "minimum_hp_drop_ratio": 0.025, "minimum_cyan_pixels": 900, "minimum_hostile_magenta_pixels": 2500, "minimum_pvp_red_pixels": 500, "safe_zone_cyan_pixels": 150, "emergency_hp_ratio": 0.20}}
        history = deque([BOT.FrameState(1.0, 0.80, 9000, 12000, 900, 0), BOT.FrameState(2.0, 0.70, 9000, 12000, 900, 0)])
        self.assertFalse(BOT.detect_threat(history, cfg, emergency_only=True)[0])

    def test_quest_mode_still_returns_at_twenty_percent_hp(self):
        cfg = {"detection": {"hp_drop_window_seconds": 2.5, "minimum_hp_drop_ratio": 0.025, "minimum_cyan_pixels": 900, "minimum_hostile_magenta_pixels": 2500, "minimum_pvp_red_pixels": 500, "safe_zone_cyan_pixels": 150, "emergency_hp_ratio": 0.20}}
        history = deque([BOT.FrameState(1.0, 0.20, 0, 0, 0, 0), BOT.FrameState(2.0, 0.20, 0, 0, 0, 0)])
        self.assertTrue(BOT.detect_threat(history, cfg, emergency_only=True)[0])

    def test_world_boss_low_hp_escapes_even_when_arena_says_safe_zone(self):
        cfg = {
            "detection": {
                "hp_drop_window_seconds": 2.5,
                "minimum_hp_drop_ratio": 0.025,
                "minimum_cyan_pixels": 900,
                "minimum_hostile_magenta_pixels": 2500,
                "minimum_pvp_red_pixels": 500,
                "safe_zone_cyan_pixels": 150,
                "emergency_hp_ratio": 0.20,
            }
        }
        history = deque([BOT.FrameState(1.0, 0.20, 0, 0, 0, 200), BOT.FrameState(2.0, 0.20, 0, 0, 0, 200)])
        self.assertTrue(BOT.detect_threat(history, cfg, emergency_in_safe_zone=True)[0])

    def test_world_boss_schedule_window(self):
        cfg = {
            "schedule": ["14:00", "23:00"],
            "schedule_before_seconds": 90,
            "schedule_after_seconds": 180,
        }
        self.assertTrue(BOT.world_boss_schedule_active(datetime(2026, 8, 15, 22, 59), cfg))
        self.assertTrue(BOT.world_boss_schedule_active(datetime(2026, 8, 15, 23, 2), cfg))
        self.assertFalse(BOT.world_boss_schedule_active(datetime(2026, 8, 15, 23, 10), cfg))
        self.assertFalse(BOT.world_boss_schedule_active(datetime(2026, 8, 15, 18, 0), cfg))

    def test_world_boss_icon_requires_diamond_and_gold_caption(self):
        image = Image.new("RGB", (100, 100), "black")
        draw = ImageDraw.Draw(image)
        quadrants = [[0, 0, 20, 20], [20, 0, 40, 20], [0, 20, 20, 40], [20, 20, 40, 40]]
        for rect in quadrants:
            draw.rectangle(tuple(rect), fill=(220, 20, 20))
        draw.rectangle((0, 60, 60, 80), fill=(220, 150, 30))
        cfg = {
            "icon_quadrants": quadrants,
            "minimum_icon_quadrant_red_pixels": 25,
            "icon_caption_region": [0, 60, 60, 80],
            "minimum_icon_caption_gold_pixels": 120,
        }
        self.assertTrue(BOT.world_boss_icon_visible(image, cfg))
        ImageDraw.Draw(image).rectangle((0, 60, 60, 80), fill="black")
        self.assertFalse(BOT.world_boss_icon_visible(image, cfg))

    def test_priority_loot_prefers_purple_then_red_then_blue(self):
        image = Image.new("RGB", (128, 64), "black")
        draw = ImageDraw.Draw(image)
        draw.rectangle((5, 5, 30, 25), fill=(60, 110, 220))
        draw.rectangle((45, 5, 70, 25), fill=(230, 60, 40))
        draw.rectangle((85, 5, 110, 25), fill=(180, 70, 210))

        target = BOT.find_priority_loot_target(image, [0, 0, 128, 64])

        self.assertEqual("legendary-purple", target[0])
        self.assertGreaterEqual(target[1][0], 85)

    def test_world_boss_icon_starts_entry_state(self):
        image = Image.new("RGB", (100, 100), "black")
        ImageDraw.Draw(image).rectangle((0, 0, 30, 30), fill=(220, 20, 20))
        global_cfg = {
            "dry_run": False,
            "world_boss": {
                "enabled": True,
                "schedule": ["23:00"],
                "schedule_before_seconds": 90,
                "schedule_after_seconds": 1200,
                "icon_region": [0, 0, 40, 40],
                "minimum_icon_red_pixels": 150,
            },
        }
        device_cfg = {
            "actions_enabled": True,
            "world_boss": {"enabled": True, "icon_point": [10, 10]},
        }
        runtime = BOT.WorldBossRuntime()
        runtime.icon_frames = 2

        with (
            patch.object(BOT, "tap") as tapped,
            patch.object(BOT, "world_boss_icon_visible", return_value=True),
            patch.object(BOT, "save_world_boss_marker") as marker,
        ):
            state = BOT.world_boss_tick(
                image,
                100.0,
                datetime(2026, 8, 15, 23, 0),
                "adb",
                "device",
                global_cfg,
                device_cfg,
                runtime,
                Mock(),
            )

        self.assertEqual("menu", state)
        tapped.assert_called_once_with("adb", "device", 10, 10)
        marker.assert_called_once_with("device", "2026-08-15T23:00")



if __name__ == "__main__":
    unittest.main()
