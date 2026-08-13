from __future__ import annotations

from pathlib import Path

from .combat import CombatEngine
from .models import AttackResult, MonsterState, PlayerState
from .repository import ContentRepository, RuntimeRepository, load_config


class CoreGame:
    def __init__(self, content_db: Path, runtime_db: Path, config_path: Path, rng=None):
        self.config = load_config(config_path)
        self.content = ContentRepository(content_db)
        self.runtime = RuntimeRepository(runtime_db)
        self.combat = CombatEngine(self.content, self.config["combat"], rng=rng)
        self.players: dict[int, PlayerState] = {}
        self.monsters: dict[int, MonsterState] = {}

    def load_player(self, object_id: int) -> PlayerState:
        player = self.runtime.load_player(object_id, self.config["default_player"])
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
            player.exp += result.exp_gained
            self._apply_level_ups(player)
            self.runtime.add_items(player.object_id, result.drops)
            self.runtime.save_player(player)
        return result

    def _apply_level_ups(self, player: PlayerState) -> None:
        while player.exp >= self.exp_required(player.level + 1):
            player.level += 1

    @staticmethod
    def exp_required(level: int) -> int:
        return max(0, (level - 1) * (level - 1) * 100)

