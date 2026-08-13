import json
import random
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from core import CoreGame


class CoreGameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.content_db = root / "content.sqlite"
        self.runtime_db = root / "runtime.sqlite"
        self.config_path = root / "server.json"
        with closing(sqlite3.connect(self.content_db)) as connection:
            connection.execute(
                "CREATE TABLE npcs (npc_id INTEGER PRIMARY KEY, name_zh_tw TEXT, "
                "name_token TEXT, level INTEGER, hp INTEGER, ac INTEGER, size_type INTEGER)"
            )
            connection.execute(
                "INSERT INTO npcs VALUES (14464, 'boar', '$27331', 10, 12, 0, 0)"
            )
            connection.execute(
                "CREATE TABLE items (item_id INTEGER PRIMARY KEY, dmg_small INTEGER, dmg_large INTEGER)"
            )
            connection.execute("INSERT INTO items VALUES (1, 4, 6)")
            connection.execute(
                "CREATE TABLE npc_drops (npc_id INTEGER, item_id INTEGER, item_name_zh_tw TEXT)"
            )
            connection.execute("INSERT INTO npc_drops VALUES (14464, 17923, 'food bag')")
            connection.commit()
        config = {
            "default_player": {
                "name": "tester", "level": 1, "exp": 0, "strength": 16,
                "dexterity": 50, "armor_class": 10, "weapon_item_id": 1,
                "x": 1, "y": 2,
            },
            "combat": {
                "base_hit_chance": 0.95, "minimum_damage": 1,
                "armor_divisor": 5, "critical_chance": 0.0,
                "critical_multiplier": 2, "exp_per_level": 10,
            },
        }
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        self.game = CoreGame(
            self.content_db, self.runtime_db, self.config_path, rng=random.Random(3)
        )
        self.player = self.game.load_player(100)
        self.monster = self.game.spawn_monster(14464, 200, 4, 5)

    def tearDown(self):
        self.temp.cleanup()

    def test_attack_reduces_hp_and_eventually_kills(self):
        results = []
        while self.monster.alive:
            results.append(self.game.attack(100, 200))
        self.assertTrue(all(result.accepted for result in results))
        self.assertEqual(0, self.monster.hp)
        self.assertTrue(results[-1].killed)
        self.assertEqual(100, results[-1].exp_gained)
        self.assertEqual(17923, results[-1].drops[0].item_id)

    def test_dead_monster_rejects_further_attacks(self):
        while self.monster.alive:
            self.game.attack(100, 200)
        result = self.game.attack(100, 200)
        self.assertFalse(result.accepted)
        self.assertEqual("target-dead", result.reason)

    def test_rewards_and_position_are_persisted(self):
        self.game.move_player(100, 9, 10)
        while self.monster.alive:
            self.game.attack(100, 200)
        reloaded = CoreGame(self.content_db, self.runtime_db, self.config_path)
        player = reloaded.load_player(100)
        self.assertEqual((9, 10), (player.x, player.y))
        self.assertEqual(100, player.exp)
        self.assertEqual(1, reloaded.runtime.inventory(100)[17923])

    def test_unknown_target_is_rejected(self):
        result = self.game.attack(100, 999)
        self.assertFalse(result.accepted)
        self.assertEqual("unknown-target", result.reason)


if __name__ == "__main__":
    unittest.main()
