from __future__ import annotations

from pathlib import Path
import time

from .combat import CombatEngine
from .models import AttackResult, DropReward, GroundItemState, InventoryActionResult, MonsterState, PlayerState, WorldEvent
from .repository import ContentRepository, RuntimeRepository, load_config


class CoreGame:
    def __init__(self, content_db: Path, runtime_db: Path, config_path: Path, rng=None, clock=None):
        self.config = load_config(config_path)
        self.content = ContentRepository(content_db)
        self.runtime = RuntimeRepository(runtime_db)
        self.combat = CombatEngine(self.content, self.config["combat"], rng=rng)
        self.clock = clock or time.monotonic
        self.players: dict[int, PlayerState] = {}
        self.monsters: dict[int, MonsterState] = {}
        self.ground_items: dict[int, GroundItemState] = {}
        self._next_ground_object_id = int(self.config.get("world", {}).get("ground_object_id_start", 9200000))

    def load_player(self, object_id: int) -> PlayerState:
        player = self.runtime.load_player(object_id, self.config["default_player"])
        # Progression is runtime-owned, while base character creation stats are
        # configuration-owned until equipment/stat allocation is implemented.
        # Reconcile old rows so a protocol-capture default cannot leak back into
        # the UI after reconnecting.
        if self.config.get("sync_default_stats_on_login", True):
            defaults = self.config["default_player"]
            for field in (
                "strength", "dexterity", "intelligence", "wisdom",
                "constitution", "charisma",
            ):
                if field in defaults:
                    setattr(player, field, int(defaults[field]))
            self.runtime.save_player(player)
        retired_items = {int(item_id) for item_id in self.config.get("retired_inventory_items", [])}
        for item_id in retired_items:
            self.runtime.delete_item(object_id, item_id)
        if player.weapon_item_id in retired_items:
            player.weapon_item_id = int(self.config["default_player"]["weapon_item_id"])
            player.weapon_enchant = int(self.config["default_player"].get("weapon_enchant", 0))
            self.runtime.save_player(player)
        configured_enchants = self.config.get("item_enchant_levels", {})
        expected_enchant = int(configured_enchants.get(str(player.weapon_item_id), player.weapon_enchant))
        if player.weapon_enchant != expected_enchant:
            player.weapon_enchant = expected_enchant
            self.runtime.save_player(player)
        for item_id, count in self.config.get("starter_inventory", {}).items():
            self.runtime.ensure_item(object_id, int(item_id), int(count))
        self.players[object_id] = player
        self._recalculate_equipment_stats(player)
        return player

    def spawn_monster(self, npc_id: int, object_id: int, x: int, y: int) -> MonsterState:
        monster = self.content.load_monster(npc_id, object_id, x, y)
        self.monsters[object_id] = monster
        return monster

    def move_player(self, object_id: int, x: int, y: int) -> None:
        player = self.players[object_id]
        player.x, player.y = x, y
        self.runtime.save_player(player)

    def attack(self, player_id: int, target_id: int) -> AttackResult:
        player = self.players.get(player_id)
        monster = self.monsters.get(target_id)
        if player is None:
            return AttackResult(False, False, 0, 0, 0, False, reason="unknown-player")
        if monster is None:
            return AttackResult(False, False, 0, 0, 0, False, reason="unknown-target")
        if player.hp <= 0:
            return AttackResult(False, False, 0, monster.hp, monster.hp, False, reason="player-dead")
        attack_range = int(self.config.get("combat", {}).get("player_attack_range", 3))
        if max(abs(player.x - monster.x), abs(player.y - monster.y)) > attack_range:
            return AttackResult(False, False, 0, monster.hp, monster.hp, False, reason="out-of-range")
        result = self.combat.attack(player, monster)
        if result.killed:
            now = self.clock()
            monster.corpse_remove_at = now + float(self.config["world"]["corpse_seconds"])
            monster.respawn_at = now + float(self.config["world"]["respawn_seconds"])
            player.exp += result.exp_gained
            self._apply_level_ups(player)
            if bool(self.config["world"].get("auto_loot", True)):
                self.runtime.add_items(player.object_id, result.drops)
            else:
                self._create_ground_drops(player.object_id, monster, result.drops, now)
            self.runtime.save_player(player)
        return result

    def _create_ground_drops(self, owner_id, monster, drops, now) -> None:
        lifetime = float(self.config.get("world", {}).get("ground_item_seconds", 120.0))
        for drop in drops:
            object_id = self._next_ground_object_id
            self._next_ground_object_id += 1
            self.ground_items[object_id] = GroundItemState(
                object_id, drop.item_id, drop.name, drop.count,
                monster.x, monster.y, owner_id, now + lifetime,
            )

    def pickup_ground_item(self, player_id: int, ground_object_id: int, count: int = 0) -> InventoryActionResult:
        player = self.players.get(player_id)
        ground = self.ground_items.get(ground_object_id)
        if player is None:
            return InventoryActionResult(False, "Unknown player")
        if player.hp <= 0:
            return InventoryActionResult(False, "Cannot pick up while dead")
        if ground is None:
            return InventoryActionResult(False, f"Ground item {ground_object_id} not found")
        if ground.owner_id != player_id:
            return InventoryActionResult(False, "Ground item belongs to another player", ground.item_id, ground.count)
        pickup_range = int(self.config.get("world", {}).get("pickup_range", 3))
        if max(abs(player.x - ground.x), abs(player.y - ground.y)) > pickup_range:
            return InventoryActionResult(False, "Ground item is out of range", ground.item_id, ground.count)
        take = ground.count if count <= 0 else min(count, ground.count)
        self.runtime.add_items(player_id, (DropReward(ground.item_id, ground.name, take),))
        ground.count -= take
        if ground.count <= 0:
            del self.ground_items[ground_object_id]
        return InventoryActionResult(True, f"Picked up {ground.name} x{take}", ground.item_id, max(0, ground.count))

    def ground_items_text(self) -> str:
        if not self.ground_items:
            return "No ground drops"
        return "Drops " + ", ".join(
            f"obj {obj}: item {drop.item_id} x{drop.count} at {drop.x},{drop.y}"
            for obj, drop in sorted(self.ground_items.items())
        )

    def monster_attack(self, monster_id: int, player_id: int) -> AttackResult:
        monster = self.monsters.get(monster_id)
        player = self.players.get(player_id)
        if monster is None:
            return AttackResult(False, False, 0, 0, 0, False, reason="unknown-monster")
        if player is None:
            return AttackResult(False, False, 0, 0, 0, False, reason="unknown-player")
        result = self.combat.monster_attack(monster, player)
        if result.accepted:
            self.runtime.save_player(player)
        return result

    def revive_player(self, object_id: int) -> PlayerState:
        player = self.players[object_id]
        player.hp = player.max_hp
        player.mp = player.max_mp
        self.runtime.save_player(player)
        return player

    def tick(self, now: float | None = None) -> tuple[WorldEvent, ...]:
        current = self.clock() if now is None else now
        events = []
        for monster in self.monsters.values():
            if monster.alive:
                continue
            if not monster.removed and monster.corpse_remove_at is not None:
                if current >= monster.corpse_remove_at:
                    monster.removed = True
                    events.append(WorldEvent("remove", monster.object_id, monster.npc_id))
            if monster.respawn_at is not None and current >= monster.respawn_at:
                monster.hp = monster.max_hp
                monster.alive = True
                monster.removed = False
                monster.corpse_remove_at = None
                monster.respawn_at = None
                events.append(WorldEvent("respawn", monster.object_id, monster.npc_id))
        for object_id, ground in tuple(self.ground_items.items()):
            if ground.expires_at is not None and current >= ground.expires_at:
                del self.ground_items[object_id]
                events.append(WorldEvent("ground-expire", object_id, 0))
        return tuple(events)

    def status_text(self, object_id: int) -> str:
        player = self.players[object_id]
        next_exp = self.exp_required(player.level + 1)
        return (
            f"Lv.{player.level} EXP {player.exp}/{next_exp} "
            f"STR {player.strength} DEX {player.dexterity} "
            f"weapon +{player.weapon_enchant} {player.weapon_item_id} "
            f"AC {player.armor_class} armor_slots {len(self.runtime.equipment(object_id))}"
        )

    def inventory_text(self, object_id: int) -> str:
        inventory = self.runtime.inventory(object_id)
        if not inventory:
            return "Inventory is empty"
        return "Inventory " + ", ".join(
            f"item {item_id} x{count}" for item_id, count in sorted(inventory.items())
        )

    def equip_weapon(self, object_id: int, item_id: int) -> InventoryActionResult:
        player = self.players[object_id]
        inventory = self.runtime.inventory(object_id)
        item = self.content.try_load_item(item_id)
        if item is None:
            return InventoryActionResult(False, f"Unknown item {item_id}", item_id)
        if inventory.get(item_id, 0) < 1:
            return InventoryActionResult(False, f"Item {item_id} is not in inventory", item_id)
        if int(item.get("weapon_type") or 0) <= 0:
            return InventoryActionResult(False, f"Item {item_id} is not a weapon", item_id)
        player.weapon_item_id = item_id
        player.weapon_enchant = int(
            self.config.get("item_enchant_levels", {}).get(str(item_id), 0)
        )
        self.runtime.save_player(player)
        name = str(item.get("name_zh_tw") or item.get("name_token") or item_id)
        return InventoryActionResult(
            True, f"Equipped +{player.weapon_enchant} {item_id}:{name}",
            item_id, inventory[item_id],
        )

    def unequip_weapon(self, object_id: int) -> InventoryActionResult:
        player = self.players[object_id]
        old_item_id = player.weapon_item_id
        player.weapon_item_id = 0
        player.weapon_enchant = 0
        self.runtime.save_player(player)
        return InventoryActionResult(True, f"Unequipped weapon {old_item_id}", old_item_id)

    def item_detail_text(self, item_id: int) -> str:
        item = self.content.try_load_item(item_id)
        if item is None:
            return f"Unknown item {item_id}"
        override = self.config.get("item_display", {}).get(str(item_id), {})
        name = str(
            override.get("name") or item.get("name_zh_tw")
            or item.get("name_token") or item_id
        )
        enchant = int(self.config.get("item_enchant_levels", {}).get(str(item_id), 0))
        if int(item.get("weapon_type") or 0) > 0:
            small = max(1, int(item.get("dmg_small") or 1)) + enchant
            large = max(1, int(item.get("dmg_large") or 1)) + enchant
            return f"+{enchant} {name}: damage small {small}, large {large}"
        return f"{name}: non-weapon item"

    def use_item(self, object_id: int, item_id: int) -> InventoryActionResult:
        player = self.players[object_id]
        consumable = self.config.get("consumables", {}).get(str(item_id))
        if consumable is None:
            return InventoryActionResult(False, f"Item {item_id} is not usable", item_id)
        inventory = self.runtime.inventory(object_id)
        if inventory.get(item_id, 0) < 1:
            return InventoryActionResult(False, f"Item {item_id} is not in inventory", item_id)
        heal = max(0, int(consumable.get("hp_restore", 0)))
        if heal and player.hp >= player.max_hp:
            return InventoryActionResult(False, "HP is already full", item_id, inventory[item_id])
        if not self.runtime.remove_item(object_id, item_id, 1):
            return InventoryActionResult(False, f"Could not consume item {item_id}", item_id)
        before = player.hp
        player.hp = min(player.max_hp, player.hp + heal)
        self.runtime.save_player(player)
        remaining = self.runtime.inventory(object_id).get(item_id, 0)
        return InventoryActionResult(
            True, f"Used {item_id}: HP {before}->{player.hp} (remaining {remaining})",
            item_id, remaining,
        )

    def equip_armor(self, object_id: int, item_id: int) -> InventoryActionResult:
        player = self.players[object_id]
        inventory = self.runtime.inventory(object_id)
        item = self.content.try_load_item(item_id)
        if item is None:
            return InventoryActionResult(False, f"Unknown item {item_id}", item_id)
        if inventory.get(item_id, 0) < 1:
            return InventoryActionResult(False, f"Item {item_id} is not in inventory", item_id)
        slot = int(item.get("equipment_index") or 0)
        if slot <= 0 or int(item.get("weapon_type") or 0) > 0:
            return InventoryActionResult(False, f"Item {item_id} is not armor", item_id)
        enchant = int(self.config.get("item_enchant_levels", {}).get(str(item_id), 0))
        self.runtime.equip_item(object_id, slot, item_id, enchant)
        self._recalculate_equipment_stats(player)
        name = str(
            self.config.get("item_display", {}).get(str(item_id), {}).get("name")
            or item.get("name_zh_tw") or item.get("name_token") or item_id
        )
        return InventoryActionResult(True, f"Equipped armor {name}; AC {player.armor_class}", item_id, 1)

    def unequip_armor(self, object_id: int, item_id: int) -> InventoryActionResult:
        player = self.players[object_id]
        equipment = self.runtime.equipment(object_id)
        slot = next((slot for slot, value in equipment.items() if value[0] == item_id), None)
        if slot is None:
            return InventoryActionResult(False, f"Armor {item_id} is not equipped", item_id)
        self.runtime.unequip_slot(object_id, slot)
        self._recalculate_equipment_stats(player)
        return InventoryActionResult(True, f"Unequipped armor {item_id}; AC {player.armor_class}", item_id, 1)

    def _recalculate_equipment_stats(self, player: PlayerState) -> None:
        defaults = self.config["default_player"]
        effects_by_item = self.config.get("equipment_effects", {})
        totals = {
            "strength": 0, "dexterity": 0, "intelligence": 0,
            "wisdom": 0, "constitution": 0, "charisma": 0,
            "max_hp": 0, "max_mp": 0, "ac": 0,
        }
        for item_id, enchant in self.runtime.equipment(player.object_id).values():
            item = self.content.load_item(item_id)
            effects = effects_by_item.get(str(item_id), {})
            database_ac = max(0, -int(item.get("armor_ac") or 0))
            totals["ac"] += int(effects.get("ac", database_ac)) + max(0, enchant)
            for field in totals:
                if field != "ac":
                    totals[field] += int(effects.get(field, 0))
        for field in (
            "strength", "dexterity", "intelligence", "wisdom",
            "constitution", "charisma",
        ):
            model_default = PlayerState.__dataclass_fields__[field].default
            setattr(player, field, int(defaults.get(field, model_default)) + totals[field])
        player.max_hp = max(
            1, int(defaults.get("max_hp", PlayerState.max_hp)) + totals["max_hp"]
        )
        player.max_mp = max(
            0, int(defaults.get("max_mp", PlayerState.max_mp)) + totals["max_mp"]
        )
        player.hp = min(player.hp, player.max_hp)
        player.mp = min(player.mp, player.max_mp)
        player.armor_class = int(defaults.get("armor_class", PlayerState.armor_class)) - totals["ac"]
        self.runtime.save_player(player)

    def equipment_text(self, object_id: int) -> str:
        equipment = self.runtime.equipment(object_id)
        if not equipment:
            return "No armor equipped"
        return "Equipment " + ", ".join(
            f"slot {slot}: +{enchant} item {item_id}"
            for slot, (item_id, enchant) in sorted(equipment.items())
        )

    def _apply_level_ups(self, player: PlayerState) -> None:
        while player.exp >= self.exp_required(player.level + 1):
            player.level += 1

    @staticmethod
    def exp_required(level: int) -> int:
        # Early client EXP table confirmed from the UI:
        # total 300 is level 2 at 100%, and total 400 is level 3 at 50%.
        # Keep the currently exercised low-level range deterministic until the
        # complete client table is imported from data.
        if level <= 1:
            return 0
        if level == 2:
            return 100
        return 300 + (level - 3) * 200
