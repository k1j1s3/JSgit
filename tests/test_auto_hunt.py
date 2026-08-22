import importlib.util
import json
import sys
import unittest
from collections import deque
from datetime import datetime
from pathlib import Path
from unittest.mock import ANY, Mock, patch

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
        self.assertTrue(config["devices"][0]["actions_enabled"])
        test_device = BOT.resolve_device_config(config, config["devices"][1])
        self.assertEqual("emulator-5556", test_device["device"])
        self.assertTrue(test_device["actions_enabled"])
        self.assertTrue(test_device["world_boss"]["enabled"])
        self.assertFalse(config["world_boss"]["observe_only"])
        self.assertEqual([170, 330], test_device["world_boss"]["entry_point"])
        self.assertEqual(config["devices"][0]["town_actions"], test_device["town_actions"])
        self.assertEqual(config["devices"][0]["fixed_town_actions"], test_device["fixed_town_actions"])
        self.assertEqual(config["devices"][0]["hunting_routes"], test_device["hunting_routes"])
        self.assertEqual("round_robin", test_device["hunting_route_mode"])
        self.assertEqual(2, len(test_device["hunting_routes"]))
        self.assertEqual("blessed-teleport-saved-place-1-sanjeok3", test_device["hunting_routes"][0]["name"])
        self.assertEqual("blessed-teleport-saved-place-2-gaemi6", test_device["hunting_routes"][1]["name"])

    def test_hunting_routes_use_blessed_scroll_and_first_two_saved_places(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        routes = config["devices"][0]["hunting_routes"]
        self.assertEqual([[935, 635], [935, 635]], [route["actions"][0]["point"] for route in routes])
        self.assertEqual([[190, 255], [190, 328]], [route["actions"][2]["point"] for route in routes])
        self.assertEqual([[335, 255], [335, 328]], [route["actions"][4]["point"] for route in routes])

    def test_normal_recovery_disables_auto_in_town_and_restores_it_on_field(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        town_actions = config["devices"][0]["town_actions"]
        fixed_town_actions = config["devices"][0]["fixed_town_actions"]
        actions = config["devices"][0]["hunting_routes"][0]["actions"]
        self.assertEqual("ensure_auto_off", fixed_town_actions[0]["type"])
        self.assertEqual("ensure_auto", actions[-1]["type"])
        self.assertEqual([998, 548], fixed_town_actions[0]["point"])
        self.assertEqual([998, 548], actions[-1]["point"])

    def test_return_command_is_immediately_followed_by_auto_disable(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        actions = config["devices"][0]["return_actions"]
        self.assertEqual("close_main_menu_if_open", actions[0]["type"])
        self.assertEqual("tap", actions[1]["type"])
        self.assertEqual([1232, 635], actions[1]["point"])
        self.assertEqual("ensure_auto_off", actions[2]["type"])
        self.assertEqual([998, 548], actions[2]["point"])

    def test_return_waits_for_menu_animation_and_retries_quickly(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        device = config["devices"][0]
        self.assertGreaterEqual(device["return_actions"][0]["wait_after_seconds"], 0.5)
        self.assertLessEqual(device["return_actions"][-1]["seconds"], 1.0)
        self.assertGreaterEqual(device["return_retry_attempts"], 3)

    def test_survival_profile_returns_before_hp_becomes_critical(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        detection = config["detection"]
        self.assertGreaterEqual(detection["critical_hp_ratio"], 0.40)
        self.assertGreaterEqual(detection["emergency_hp_ratio"], 0.55)
        self.assertLessEqual(config["poll_interval_seconds"], 0.4)
        self.assertEqual(1, detection["strong_pvp_confirm_frames"])

    def test_rapid_hp_drop_triggers_return_without_pvp_colors(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        history = deque([
            BOT.FrameState(1.0, 0.95, 0, 0, 0, 0),
            BOT.FrameState(1.4, 0.60, 0, 0, 0, 0),
        ])
        threat, reason = BOT.detect_threat(history, cfg)
        self.assertTrue(threat)
        self.assertIn("rapid-hp-drop", reason)

    def test_return_to_town_retries_after_failed_verification(self):
        device = {
            "return_actions": [{"type": "tap", "point": [1, 2]}],
            "regions": {"zone_label": [0, 0, 1, 1]},
            "safe_zone_cyan_pixels": 100,
            "return_retry_attempts": 3,
            "return_verify_timeout_seconds": 0.0,
        }
        with (
            patch.object(BOT, "execute_actions", return_value=True) as execute,
            patch.object(BOT, "screenshot"),
            patch.object(BOT, "count_safe_zone_color", return_value=0),
        ):
            self.assertFalse(BOT.return_to_town("adb", "device", device, Mock()))
        self.assertEqual(3, execute.call_count)

    def test_fixed_town_route_selects_giran_before_npc_actions(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        actions = config["devices"][0]["fixed_town_actions"]
        aden_index = next(index for index, action in enumerate(actions) if action.get("point") == [435, 105])
        favorites_index = next(index for index, action in enumerate(actions) if action.get("point") == [130, 655])
        self.assertLess(aden_index, favorites_index)
        self.assertIn([130, 655], [action.get("point") for action in actions])
        self.assertIn([130, 535], [action.get("point") for action in actions])
        self.assertNotIn("swipe", [action["type"] for action in actions])
        self.assertTrue(any("Giran village" in action.get("label", "") for action in actions))
        verification = next(action for action in actions if action["type"] == "verify_reference")
        self.assertLessEqual(verification["minimum_similarity"], 0.857)

    def test_warehouse_loads_auto_storage_before_deposit_all(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        actions = config["devices"][0]["town_actions"]
        load_index = next(
            index for index, action in enumerate(actions)
            if action.get("point") == [990, 648]
            and "automatic-storage" in action.get("label", "")
        )
        deposit_index = next(
            index for index, action in enumerate(actions)
            if action.get("point") == [1150, 648]
            and "deposit all" in action.get("label", "")
        )
        self.assertLess(load_index, deposit_index)

    def test_shop_buys_orange_potions_at_max_weight_without_auto_order(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        actions = config["devices"][0]["town_actions"]
        points = [action.get("point") for action in actions]
        self.assertNotIn([990, 648], [
            action.get("point") for action in actions
            if "order" in action.get("label", "").lower()
        ])
        potion_index = points.index([190, 310])
        max_index = points.index([735, 648])
        buy_index = next(
            index for index, action in enumerate(actions)
            if action.get("point") == [1150, 648]
            and "orange potions" in action.get("label", "")
        )
        self.assertLess(potion_index, max_index)
        self.assertLess(max_index, buy_index)
        self.assertNotIn("close_overlay_if_open", [action["type"] for action in actions])

    def test_recovery_runs_town_actions_before_hunting_route(self):
        cfg = {
            "return_actions": [{"type": "tap", "point": [1, 1]}],
            "fixed_town_actions": [{"type": "tap", "point": [9, 9]}],
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
            [cfg["return_actions"], cfg["fixed_town_actions"], cfg["town_actions"], cfg["hunting_routes"][0]["actions"]],
        )

    def test_round_robin_recovery_advances_persisted_route(self):
        routes = [
            {"name": "first", "actions": [{"type": "tap", "point": [3, 3]}]},
            {"name": "second", "actions": [{"type": "tap", "point": [4, 4]}]},
        ]
        cfg = {
            "return_actions": [],
            "town_actions": [],
            "hunting_routes": routes,
            "hunting_route_mode": "round_robin",
        }
        with (
            patch.object(BOT, "execute_actions", return_value=True),
            patch.object(BOT, "load_hunting_route_index", return_value=1),
            patch.object(BOT, "save_hunting_route_index") as save,
        ):
            selected = BOT.recover_and_resume("adb", "device", cfg, Mock())
        self.assertEqual("second", selected["name"])
        save.assert_called_once_with("device", 0)

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

    def test_ensure_auto_does_not_tap_when_later_sample_is_active(self):
        inactive = Image.new("RGB", (1280, 720), (40, 40, 40))
        active = inactive.copy()
        ImageDraw.Draw(active).rectangle((960, 500, 989, 529), fill=(220, 110, 20))
        action = {
            "type": "ensure_auto",
            "point": [998, 548],
            "sample_count": 3,
            "sample_interval_seconds": 0,
        }
        logger = Mock()
        with patch.object(BOT, "screenshot", side_effect=[inactive, active]), patch.object(BOT, "tap") as tap:
            BOT.execute_actions("adb", "device", [action], logger)
        tap.assert_not_called()

    def test_ensure_auto_off_only_taps_an_active_auto_button(self):
        inactive = Image.new("RGB", (1280, 720), (40, 40, 40))
        active = inactive.copy()
        ImageDraw.Draw(active).rectangle((960, 500, 989, 529), fill=(220, 110, 20))
        action = {"type": "ensure_auto_off", "point": [998, 548]}
        with patch.object(BOT, "screenshot", return_value=active), patch.object(BOT, "tap") as tap:
            BOT.execute_actions("adb", "device", [action], Mock())
        tap.assert_called_once_with("adb", "device", 998, 548)

        with patch.object(BOT, "screenshot", return_value=inactive), patch.object(BOT, "tap") as tap:
            BOT.execute_actions("adb", "device", [action], Mock())
        tap.assert_not_called()

    def test_close_overlay_detection_requires_red_close_button(self):
        field = Image.new("RGB", (70, 70), (40, 40, 40))
        menu = field.copy()
        ImageDraw.Draw(menu).rectangle((10, 10, 30, 30), fill=(180, 35, 35))
        self.assertFalse(BOT.is_close_overlay_open(field, [0, 0, 70, 70]))
        self.assertTrue(BOT.is_close_overlay_open(menu, [0, 0, 70, 70]))

    def test_main_menu_detection_uses_panel_not_red_notification_dot(self):
        closed = Image.new("RGB", (400, 600), (80, 70, 55))
        ImageDraw.Draw(closed).ellipse((360, 0, 380, 20), fill=(220, 20, 20))
        opened = Image.new("RGB", (400, 600), (10, 28, 40))
        self.assertFalse(BOT.is_main_menu_open(closed, [0, 0, 400, 600]))
        self.assertTrue(BOT.is_main_menu_open(opened, [0, 0, 400, 600]))

    def test_death_panel_is_detected(self):
        image = Image.new("RGB", (1280, 720), "black")
        draw = ImageDraw.Draw(image)
        draw.rectangle((390, 65, 890, 605), fill=(70, 45, 30))
        draw.rectangle((555, 547, 725, 591), fill=(35, 65, 110))
        self.assertTrue(BOT.is_death_panel_visible(image, {}))

    def test_normal_field_is_not_death_panel(self):
        image = Image.new("RGB", (1280, 720), (45, 70, 35))
        self.assertFalse(BOT.is_death_panel_visible(image, {}))

    def test_recover_after_death_restarts_then_resumes_hunting(self):
        cfg = {
            "death_restart_point": [640, 570],
            "death_restart_load_seconds": 0,
            "death_recovery_hp_ratio": 0.9,
            "death_recovery_timeout_seconds": 1,
            "safe_zone_cyan_pixels": 100,
            "regions": {"zone_label": [0, 0, 1, 1], "hp_bar": [0, 0, 1, 1]},
            "fixed_town_actions": [{"type": "tap", "point": [1, 1]}],
            "town_actions": [{"type": "tap", "point": [2, 2]}],
            "hunting_routes": [{"name": "route", "actions": [{"type": "tap", "point": [3, 3]}]}],
        }
        with (
            patch.object(BOT, "tap") as tapped,
            patch.object(BOT, "screenshot", return_value=Image.new("RGB", (1, 1))),
            patch.object(BOT, "count_safe_zone_color", return_value=200),
            patch.object(BOT, "measure_hp", return_value=1.0),
            patch.object(BOT.time, "sleep"),
            patch.object(BOT, "execute_actions", return_value=True) as execute,
            patch.object(BOT, "load_hunting_route_index", return_value=0),
            patch.object(BOT, "save_hunting_route_index") as save,
        ):
            route = BOT.recover_after_death("adb", "device", cfg, Mock())
        tapped.assert_called_once_with("adb", "device", 640, 570)
        self.assertEqual("route", route["name"])
        self.assertEqual(3, execute.call_count)
        save.assert_called_once_with("device", 0)

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

    def test_green_status_effect_hp_bar_measurement(self):
        image = Image.new("RGB", (100, 10), "black")
        ImageDraw.Draw(image).rectangle((0, 0, 88, 9), fill=(55, 190, 45))
        self.assertAlmostEqual(BOT.measure_hp(image, [0, 0, 100, 10]), 0.89, places=2)

    def test_hp_measurement_ignores_isolated_red_ui_noise(self):
        image = Image.new("RGB", (100, 10), "black")
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 0, 79, 9), fill=(220, 20, 20))
        draw.rectangle((0, 0, 0, 9), fill=(220, 20, 20))
        draw.rectangle((95, 0, 96, 9), fill=(220, 20, 20))
        self.assertAlmostEqual(BOT.measure_hp(image, [0, 0, 100, 10]), 0.80, places=2)

    def test_hp_measurement_ignores_sparse_combat_effect_row_damage(self):
        image = Image.new("RGB", (100, 12), (20, 20, 20))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 1, 59, 10), fill=(210, 35, 35))
        draw.rectangle((35, 1, 99, 3), fill=(20, 20, 20))
        self.assertGreaterEqual(BOT.measure_hp(image, [0, 0, 100, 12]), 0.59)

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

    def test_real_world_boss_icon_is_visible_three_minutes_early(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        cfg = config["world_boss"]
        self.assertGreaterEqual(cfg["schedule_before_seconds"], 300)
        self.assertTrue(BOT.world_boss_schedule_active(datetime(2026, 8, 22, 19, 56, 30), cfg))

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

    def test_world_boss_menu_signature_is_verified(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        cfg = json.loads(config_path.read_text(encoding="utf-8"))["world_boss"]
        image = Image.new("RGB", (1280, 720), "black")
        draw = ImageDraw.Draw(image)
        draw.rectangle(tuple(cfg["menu_title_region"]), fill=(220, 150, 30))
        draw.rectangle(tuple(cfg["menu_first_card_region"]), fill=(220, 20, 20))
        self.assertTrue(BOT.world_boss_menu_visible(image, cfg))

    def test_normal_field_does_not_match_world_boss_menu(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        cfg = json.loads(config_path.read_text(encoding="utf-8"))["world_boss"]
        image = Image.new("RGB", (1280, 720), (45, 70, 35))
        self.assertFalse(BOT.world_boss_menu_visible(image, cfg))

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
        marker.assert_not_called()

    def test_verified_world_boss_menu_selects_first_card_and_marks_slot(self):
        config_path = Path(__file__).parents[1] / "config" / "auto_hunt.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        global_cfg = {"dry_run": False, "world_boss": config["world_boss"]}
        device_cfg = {
            "actions_enabled": True,
            "safe_zone_cyan_pixels": 100,
            "regions": {"zone_label": [0, 0, 20, 20]},
            "world_boss": {"enabled": True, "entry_point": [170, 330]},
        }
        runtime = BOT.WorldBossRuntime(
            state="menu", state_since=0.0, pending_slot="2026-08-22T20:00"
        )
        with (
            patch.object(BOT, "screenshot", return_value=Image.new("RGB", (1280, 720))),
            patch.object(BOT, "world_boss_menu_visible", return_value=True),
            patch.object(BOT, "tap") as tapped,
            patch.object(BOT, "save_world_boss_marker") as marker,
        ):
            state = BOT.world_boss_tick(
                Image.new("RGB", (1280, 720)), 2.0, datetime(2026, 8, 22, 20, 0),
                "adb", "device", global_cfg, device_cfg, runtime, Mock(),
            )
        self.assertEqual("entry_verify", state)
        tapped.assert_called_once_with("adb", "device", 170, 330)
        marker.assert_not_called()

        arena = Image.new("RGB", (1280, 720), "black")
        ImageDraw.Draw(arena).rectangle((0, 0, 19, 19), fill=(20, 180, 220))
        with (
            patch.object(BOT, "world_boss_menu_visible", return_value=False),
            patch.object(BOT, "save_world_boss_marker") as marker,
        ):
            state = BOT.world_boss_tick(
                arena, 3.0, datetime(2026, 8, 22, 20, 0),
                "adb", "device", global_cfg, device_cfg, runtime, Mock(),
            )
        self.assertEqual("arena_wait", state)
        marker.assert_called_once_with("device", "2026-08-22T20:00", "arena", ANY)

    def test_world_boss_observe_only_saves_candidate_without_clicking(self):
        image = Image.new("RGB", (100, 100), "black")
        global_cfg = {
            "dry_run": False,
            "evidence_directory": "data/bot-evidence",
            "world_boss": {
                "enabled": True,
                "observe_only": True,
                "schedule": ["23:00"],
                "schedule_before_seconds": 90,
                "schedule_after_seconds": 180,
                "icon_confirm_frames": 3,
            },
        }
        device_cfg = {"actions_enabled": True, "world_boss": {"enabled": True}}
        runtime = BOT.WorldBossRuntime(icon_frames=2)
        with (
            patch.object(BOT, "world_boss_icon_visible", return_value=True),
            patch.object(BOT, "save_evidence") as evidence,
            patch.object(BOT, "tap") as tapped,
        ):
            state = BOT.world_boss_tick(
                image, 100.0, datetime(2026, 8, 15, 23, 0),
                "adb", "device", global_cfg, device_cfg, runtime, Mock(),
            )
        self.assertEqual("idle", state)
        evidence.assert_called_once()
        tapped.assert_not_called()

    def test_radar_selects_first_target(self):
        cfg = {
            "radar_point": [28, 538],
            "radar_first_target_point": [105, 230],
            "radar_wait_seconds": 0,
        }
        with patch.object(BOT, "tap") as tapped:
            BOT.radar_select_first_target("adb", "device", cfg, Mock())
        self.assertEqual(
            [("adb", "device", 28, 538), ("adb", "device", 105, 230)],
            [call.args for call in tapped.call_args_list],
        )

    def test_world_boss_waits_for_countdown_icon_to_disappear_before_attack(self):
        cfg = {
            "dry_run": True,
            "world_boss": {
                "enabled": True,
                "buff_delay_seconds": 2,
                "entry_reposition_delay_seconds": 4,
                "spawn_icon_missing_confirm_frames": 3,
                "post_spawn_lag_seconds": 5,
            },
        }
        device = {"world_boss": {"enabled": True}}
        runtime = BOT.WorldBossRuntime(state="arena_wait", state_since=100, last_action=101)
        frame = Image.new("RGB", (1280, 720))

        with patch.object(BOT, "world_boss_icon_visible", return_value=True):
            BOT.world_boss_tick(frame, 102, datetime.now(), "adb", "device", cfg, device, runtime, Mock())
        self.assertTrue(runtime.spawn_icon_seen)

        with patch.object(BOT, "world_boss_icon_visible", return_value=False):
            for now in (103, 104, 105):
                BOT.world_boss_tick(frame, now, datetime.now(), "adb", "device", cfg, device, runtime, Mock())
            self.assertEqual("arena_wait", runtime.state)
            BOT.world_boss_tick(frame, 109.9, datetime.now(), "adb", "device", cfg, device, runtime, Mock())
            self.assertEqual("arena_wait", runtime.state)
            BOT.world_boss_tick(frame, 110, datetime.now(), "adb", "device", cfg, device, runtime, Mock())
        self.assertEqual("combat", runtime.state)

    def test_world_boss_entry_reposition_moves_once_toward_ten_oclock(self):
        cfg = {
            "entry_move_start": [117, 546],
            "entry_move_end": [82, 511],
            "entry_move_duration_ms": 700,
            "entry_move_settle_seconds": 0,
        }
        with patch.object(BOT, "swipe") as moved:
            BOT.move_toward_world_boss("adb", "device", cfg, Mock())
        moved.assert_called_once_with("adb", "device", [117, 546], [82, 511], 700)

    def test_test_device_world_boss_uses_real_attack_button_center(self):
        config = json.loads((BOT.ROOT / "config" / "auto_hunt.json").read_text(encoding="utf-8"))
        device = BOT.resolve_device_config(config, config["devices"][1])
        self.assertEqual([1097, 548], device["world_boss"]["attack_point"])

    def test_blocked_world_boss_exit_restarts_same_character_then_resumes(self):
        cfg = {
            "game_package": "com.example.game",
            "game_restart_delay_seconds": 0,
            "game_title_wait_seconds": 0,
            "character_select_wait_seconds": 0,
            "character_enter_wait_seconds": 0,
            "game_title_start_point": [640, 500],
            "current_character_enter_point": [1085, 660],
        }
        with (
            patch.object(BOT, "run_adb") as adb,
            patch.object(BOT, "tap") as tapped,
            patch.object(BOT, "recover_and_resume", return_value={"name": "route"}),
        ):
            self.assertTrue(BOT.restart_game_and_resume("adb", "device", cfg, Mock()))
        self.assertEqual("force-stop", adb.call_args_list[0].args[-2])
        self.assertEqual(
            [("adb", "device", 640, 500), ("adb", "device", 1085, 660)],
            [call.args for call in tapped.call_args_list],
        )

    def test_loot_motion_interleaves_pickup_and_short_move(self):
        device = {
            "pickup_point": [1165, 418],
            "joystick_center": [117, 546],
            "loot_micro_move_points": [[117, 510], [153, 546]],
        }
        cfg = {"pickup_burst_count": 8, "pickup_burst_delay_seconds": 0, "loot_micro_move_duration_ms": 180}
        runtime = BOT.WorldBossRuntime()
        with patch.object(BOT, "tap") as tapped, patch.object(BOT, "swipe") as moved:
            BOT.loot_motion_cycle("adb", "device", device, cfg, runtime)
        self.assertEqual(8, tapped.call_count)
        moved.assert_called_once_with("adb", "device", [117, 546], [117, 510], 180)



if __name__ == "__main__":
    unittest.main()
