import importlib.util, json, sys, tempfile, unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw

ROOT = Path(__file__).parents[1]; MODULE_PATH = ROOT / "tools" / "daily_quest_rotation.py"
SPEC = importlib.util.spec_from_file_location("daily_quest_rotation", MODULE_PATH)
ROTATION = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = ROTATION; SPEC.loader.exec_module(ROTATION)

class DailyQuestRotationTest(unittest.TestCase):
    def setUp(self): self.config = json.loads((ROOT / "config" / "daily_quest_rotation.json").read_text(encoding="utf-8"))
    def test_alt_skips_normal_clan_quest(self):
        tasks = ROTATION.tasks_for(self.config, "광전1"); self.assertEqual("clan_adena_donation_5", tasks[0]); self.assertIn("clan_easy", tasks); self.assertIn("clan_hard", tasks); self.assertNotIn("clan_normal", tasks)
    def test_main_runs_all_three_clan_quests(self): self.assertIn("clan_normal", ROTATION.tasks_for(self.config, "마검1"))
    def test_rotation_returns_to_main(self):
        state = ROTATION.new_state(self.config, date(2026, 8, 16)); state.active_character = "쫄법1"; self.assertEqual("마검1", ROTATION.next_character(self.config, state))
    def test_completed_task_is_persisted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            with patch.object(ROTATION, "state_path", return_value=path):
                state = ROTATION.new_state(self.config, date(2026, 8, 16)); first = ROTATION.next_task(self.config, state, "광전1")
                state.complete("광전1", first); ROTATION.save_state(self.config, state); loaded = ROTATION.load_state(self.config, date(2026, 8, 16))
                self.assertNotEqual(first, ROTATION.next_task(self.config, loaded, "광전1"))
    def test_switch_sequence_uses_recorded_row(self):
        with patch.object(ROTATION, "adb_tap") as tap, patch.object(ROTATION.time, "sleep"): ROTATION.switch_character(self.config, "adb", "암기2")
        points = [call.args[2] for call in tap.call_args_list]; self.assertEqual([1232, 635], points[0]); self.assertIn([250, 335], points); self.assertEqual([1085, 660], points[-1])
    def test_reward_ready_requires_red_reward_button(self):
        image = Image.new("RGB", (200, 80), "black"); self.assertFalse(ROTATION.reward_ready(image, [0, 0, 200, 80]))
        ImageDraw.Draw(image).rectangle((0, 0, 100, 50), fill=(145, 40, 35)); self.assertTrue(ROTATION.reward_ready(image, [0, 0, 200, 80]))
    def test_start_alt_clan_hard_never_taps_normal_row(self):
        with patch.object(ROTATION, "adb_tap") as tap, patch.object(ROTATION.time, "sleep"): ROTATION.start_quest(self.config, "adb", "clan_hard")
        points = [call.args[2] for call in tap.call_args_list]; self.assertIn([1145, 355], points); self.assertNotIn([1145, 270], points); self.assertEqual([998, 548], points[-1])
    def test_adena_donation_taps_general_button_five_times(self):
        with patch.object(ROTATION, "adb_tap") as tap, patch.object(ROTATION.time, "sleep"): ROTATION.donate_adena(self.config, "adb")
        points = [call.args[2] for call in tap.call_args_list]
        self.assertEqual(5, points.count([307, 566])); self.assertNotIn([640, 566], points); self.assertNotIn([973, 566], points)

if __name__ == "__main__": unittest.main()
