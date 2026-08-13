import json
import random
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from core import CoreGame
from core import (
    extend_inventory_snapshot, make_character_status, make_inventory_entry,
    make_inventory_snapshot,
    captured_inventory_entry, rewrite_inventory_entry,
)


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
                "CREATE TABLE items (item_id INTEGER PRIMARY KEY, dmg_small INTEGER, "
                "dmg_large INTEGER, weapon_type INTEGER)"
            )
            connection.execute("INSERT INTO items VALUES (1, 4, 6, 1)")
            connection.execute("INSERT INTO items VALUES (292532, 8, 9, 102)")
            connection.execute(
                "CREATE TABLE npc_drops (npc_id INTEGER, item_id INTEGER, item_name_zh_tw TEXT)"
            )
            connection.execute("INSERT INTO npc_drops VALUES (14464, 17923, 'food bag')")
            connection.commit()
        config = {
            "default_player": {
                "name": "tester", "level": 1, "exp": 0, "strength": 16,
                "dexterity": 50, "armor_class": 10, "weapon_item_id": 292532,
                "weapon_enchant": 6,
                "x": 1, "y": 2,
            },
            "combat": {
                "base_hit_chance": 0.95, "minimum_damage": 1,
                "armor_divisor": 5, "critical_chance": 0.0,
                "critical_multiplier": 2, "exp_per_level": 10,
            },
            "world": {
                "corpse_seconds": 1.5, "respawn_seconds": 10.0, "auto_loot": True,
            },
            "starter_inventory": {"292532": 1},
            "retired_inventory_items": [1],
            "item_enchant_levels": {"292532": 6},
            "item_display": {"292532": {"name": "Desert Runesword"}},
            "consumables": {"17923": {"hp_restore": 25}},
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

    def test_early_client_exp_thresholds(self):
        self.assertEqual(300, self.game.exp_required(3))
        self.assertEqual(500, self.game.exp_required(4))

    def test_login_reconciles_base_stats_without_losing_progress(self):
        self.player.level = 3
        self.player.exp = 400
        self.player.strength = 9
        self.game.runtime.save_player(self.player)
        reloaded = CoreGame(self.content_db, self.runtime_db, self.config_path)
        player = reloaded.load_player(100)
        self.assertEqual((3, 400), (player.level, player.exp))
        self.assertEqual(16, player.strength)

    def test_unknown_target_is_rejected(self):
        result = self.game.attack(100, 999)
        self.assertFalse(result.accepted)
        self.assertEqual("unknown-target", result.reason)

    def test_starter_weapon_is_seeded_once(self):
        self.assertEqual(1, self.game.runtime.inventory(100)[292532])
        self.game.load_player(100)
        self.assertEqual(1, self.game.runtime.inventory(100)[292532])

    def test_weapon_equip_and_unequip_are_persisted(self):
        equipped = self.game.equip_weapon(100, 292532)
        self.assertTrue(equipped.accepted)
        self.assertEqual(6, self.player.weapon_enchant)
        self.game.unequip_weapon(100)
        reloaded = CoreGame(self.content_db, self.runtime_db, self.config_path)
        self.assertEqual(0, reloaded.load_player(100).weapon_item_id)
        self.assertEqual(0, reloaded.load_player(100).weapon_enchant)

    def test_item_detail_includes_enhanced_weapon_damage(self):
        detail = self.game.item_detail_text(292532)
        self.assertIn("+6 Desert Runesword", detail)
        self.assertIn("small 14", detail)
        self.assertIn("large 15", detail)

    def test_enchant_bonus_is_applied_to_combat(self):
        self.player.strength = 10
        self.player.level = 1
        self.player.weapon_enchant = 6
        result = self.game.attack(100, 200)
        if result.hit:
            self.assertGreaterEqual(result.damage, 7)

    def test_non_weapon_cannot_be_equipped(self):
        self.game.runtime.add_items(100, self.game.content.drops_for(14464))
        result = self.game.equip_weapon(100, 17923)
        self.assertFalse(result.accepted)

    def test_consumable_heals_decrements_and_persists(self):
        self.game.runtime.add_items(100, self.game.content.drops_for(14464))
        self.player.hp = 50
        result = self.game.use_item(100, 17923)
        self.assertTrue(result.accepted)
        self.assertEqual(75, self.player.hp)
        self.assertNotIn(17923, self.game.runtime.inventory(100))
        reloaded = CoreGame(self.content_db, self.runtime_db, self.config_path)
        self.assertEqual(75, reloaded.load_player(100).hp)

    def test_consumable_is_not_wasted_at_full_hp(self):
        self.game.runtime.add_items(100, self.game.content.drops_for(14464))
        result = self.game.use_item(100, 17923)
        self.assertFalse(result.accepted)
        self.assertEqual(1, self.game.runtime.inventory(100)[17923])

    def test_corpse_removal_and_respawn_lifecycle(self):
        while self.monster.alive:
            self.game.attack(100, 200)
        removed = self.game.tick(self.monster.corpse_remove_at)
        self.assertEqual("remove", removed[0].kind)
        self.assertTrue(self.monster.removed)
        respawned = self.game.tick(self.monster.respawn_at)
        self.assertEqual("respawn", respawned[0].kind)
        self.assertTrue(self.monster.alive)
        self.assertEqual(self.monster.max_hp, self.monster.hp)

    def test_status_and_inventory_commands(self):
        while self.monster.alive:
            self.game.attack(100, 200)
        self.assertIn("EXP 100/", self.game.status_text(100))
        self.assertIn("item 17923 x1", self.game.inventory_text(100))

    def test_character_status_packet_contains_runtime_values(self):
        packet = make_character_status(self.player)
        self.assertEqual(0x0E, packet[0])
        self.assertEqual(100, int.from_bytes(packet[1:5], "little"))
        self.assertEqual(self.player.level, packet[5])
        self.assertEqual(self.player.exp, int.from_bytes(packet[6:10], "little"))
        self.assertEqual(56, len(packet))

    def test_inventory_snapshot_preserves_base_and_adds_item(self):
        item = self.game.content.load_item(1)
        entry = make_inventory_entry(item, 9_100_000, 3)
        base = b"\x55\x4c\x02\x10\x01\x50\x64\x00\x00"
        packet = extend_inventory_snapshot(base, (entry,))
        self.assertTrue(packet.startswith(b"\x55\x4c\x02\x10\x01\x50\x64"))
        self.assertIn(entry, packet)
        self.assertTrue(packet.endswith(b"\x00\x00"))

    def test_runtime_inventory_snapshot_removes_captured_items(self):
        captured_item = b"\x08\x6f"
        base = b"\x55\x4c\x02\x0a\x02" + captured_item + b"\x10\x01\x50\x64\xaa\xbb"
        runtime_item = b"\x08\xde\x01"
        packet = make_inventory_snapshot(base, (runtime_item,))
        self.assertNotIn(captured_item, packet)
        self.assertIn(runtime_item, packet)
        self.assertIn(b"\x10\x01\x50\x64", packet)

    def test_inventory_entry_encodes_equipped_state(self):
        item = self.game.content.load_item(1)
        unequipped = make_inventory_entry(item, 9_100_000, 1, equipped=False)
        equipped = make_inventory_entry(item, 9_100_000, 1, equipped=True)
        self.assertEqual(unequipped, equipped)

    def test_captured_weapon_template_is_rewritten_without_losing_description(self):
        entry = b"\x08\x01\x10\xb4\xed\x11\x18\x02\x20\x01\x28\x01\x92\x01\x03abc"
        base = b"\x55\x4c\x02\x0a" + bytes([len(entry)]) + entry + b"\x10\x01\xaa\xbb"
        template = captured_inventory_entry(base, 292532)
        rewritten = rewrite_inventory_entry(template, 9_100_000, 2, False)
        self.assertIn(b"abc", rewritten)
        self.assertIn(b"\x28\x01", rewritten)
        self.assertIn(b"\x18\x02", rewritten)


if __name__ == "__main__":
    unittest.main()
