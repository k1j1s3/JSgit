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

        weapon_max = (
            self.content.weapon_damage(player.weapon_item_id, monster.size_type)
            if player.weapon_item_id else 1
        )
        weapon_roll = self.rng.randint(1, weapon_max)
        enchant_bonus = max(0, int(player.weapon_enchant))
        strength_bonus = max(0, (player.strength - 10) // 3)
        level_bonus = max(0, player.level // 10)
        defense = max(0, -monster.armor_class // int(self.config["armor_divisor"]))
        critical = self.rng.random() < float(self.config["critical_chance"])
        damage = max(
            int(self.config["minimum_damage"]),
            weapon_roll + enchant_bonus + strength_bonus + level_bonus - defense,
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

    def monster_attack(self, monster: MonsterState, player: PlayerState) -> AttackResult:
        if not monster.alive:
            return AttackResult(False, False, 0, player.hp, player.hp, False, reason="attacker-dead")
        if player.hp <= 0:
            return AttackResult(False, False, 0, player.hp, player.hp, True, reason="target-dead")

        damage_min = max(1, int(self.config.get("monster_damage_min", 5)))
        damage_max = max(damage_min, int(self.config.get("monster_damage_max", 10)))
        raw_damage = self.rng.randint(damage_min, damage_max)
        base_ac = int(self.config.get("player_base_ac", 10))
        divisor = max(1, int(self.config.get("player_defense_divisor", 2)))
        defense = max(0, base_ac - player.armor_class) // divisor
        damage = max(int(self.config.get("minimum_damage", 1)), raw_damage - defense)
        hp_before = player.hp
        player.hp = max(0, player.hp - damage)
        return AttackResult(
            True, True, damage, hp_before, player.hp, player.hp == 0,
        )

    def _hit_chance(self, player: PlayerState, monster: MonsterState) -> float:
        base = float(self.config["base_hit_chance"])
        adjustment = (player.dexterity + player.level - monster.level) * 0.005
        return min(0.95, max(0.05, base + adjustment))

    def _experience(self, monster: MonsterState) -> int:
        return max(1, monster.level * int(self.config["exp_per_level"]))
