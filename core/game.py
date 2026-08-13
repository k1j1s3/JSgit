from __future__ import annotations

from pathlib import Path
import time

from .combat import CombatEngine
from .models import AttackResult, MonsterState, PlayerState, WorldEvent
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
        self.players[object_id] = player
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
        result = self.combat.attack(player, monster)
        if result.killed:
            now = self.clock()
            monster.corpse_remove_at = now + float(self.config["world"]["corpse_seconds"])
            monster.respawn_at = now + float(self.config["world"]["respawn_seconds"])
            player.exp += result.exp_gained
            self._apply_level_ups(player)
            if bool(self.config["world"].get("auto_loot", True)):
                self.runtime.add_items(player.object_id, result.drops)
            self.runtime.save_player(player)
        return result

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
        return tuple(events)

    def status_text(self, object_id: int) -> str:
        player = self.players[object_id]
        next_exp = self.exp_required(player.level + 1)
        return (
            f"Lv.{player.level} EXP {player.exp}/{next_exp} "
            f"STR {player.strength} DEX {player.dexterity} weapon {player.weapon_item_id}"
        )

    def inventory_text(self, object_id: int) -> str:
        inventory = self.runtime.inventory(object_id)
        if not inventory:
            return "Inventory is empty"
        return "Inventory " + ", ".join(
            f"item {item_id} x{count}" for item_id, count in sorted(inventory.items())
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
