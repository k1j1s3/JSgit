from __future__ import annotations

import random

from .models import AttackResult, MonsterState, PlayerState
from .repository import ContentRepository


class CombatEngine:
    def __init__(self, content: ContentRepository, config: dict, rng=None):
        self.content = content
        self.config = config
        self.rng = rng or random.Random()

    def attack(self, player: PlayerState, monster: MonsterState) -> AttackResult:
        if not monster.alive:
            return AttackResult(False, False, 0, monster.hp, monster.hp, False, reason="target-dead")

        hit_chance = self._hit_chance(player, monster)
        if self.rng.random() > hit_chance:
            return AttackResult(True, False, 0, monster.hp, monster.hp, False, reason="miss")

        weapon_max = self.content.weapon_damage(player.weapon_item_id, monster.size_type)
        weapon_roll = self.rng.randint(1, weapon_max)
        strength_bonus = max(0, (player.strength - 10) // 3)
        level_bonus = max(0, player.level // 10)
        defense = max(0, -monster.armor_class // int(self.config["armor_divisor"]))
        critical = self.rng.random() < float(self.config["critical_chance"])
        damage = max(
            int(self.config["minimum_damage"]),
            weapon_roll + strength_bonus + level_bonus - defense,
        )
        if critical:
            damage *= int(self.config["critical_multiplier"])

        hp_before = monster.hp
        monster.hp = max(0, monster.hp - damage)
        monster.alive = monster.hp > 0
        killed = not monster.alive
        exp_gained = self._experience(monster) if killed else 0
        drops = self.content.drops_for(monster.npc_id) if killed else ()
        return AttackResult(
            True, True, damage, hp_before, monster.hp, killed,
            critical=critical, exp_gained=exp_gained, drops=drops,
        )

    def _hit_chance(self, player: PlayerState, monster: MonsterState) -> float:
        base = float(self.config["base_hit_chance"])
        adjustment = (player.dexterity + player.level - monster.level) * 0.005
        return min(0.95, max(0.05, base + adjustment))

    def _experience(self, monster: MonsterState) -> int:
        return max(1, monster.level * int(self.config["exp_per_level"]))

