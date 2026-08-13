from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlayerState:
    object_id: int
    name: str = "local-player"
    level: int = 1
    exp: int = 0
    strength: int = 16
    dexterity: int = 12
    armor_class: int = 10
    weapon_item_id: int = 1
    x: int = 0
    y: int = 0


@dataclass
class MonsterState:
    object_id: int
    npc_id: int
    name: str
    level: int
    max_hp: int
    hp: int
    armor_class: int
    size_type: int = 0
    x: int = 0
    y: int = 0
    alive: bool = True


@dataclass(frozen=True)
class DropReward:
    item_id: int
    name: str
    count: int = 1


@dataclass(frozen=True)
class AttackResult:
    accepted: bool
    hit: bool
    damage: int
    hp_before: int
    hp_after: int
    killed: bool
    critical: bool = False
    exp_gained: int = 0
    drops: tuple[DropReward, ...] = field(default_factory=tuple)
    reason: str = ""

