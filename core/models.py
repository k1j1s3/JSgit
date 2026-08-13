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
    intelligence: int = 9
    wisdom: int = 6
    constitution: int = 16
    charisma: int = 7
    armor_class: int = 10
    hp: int = 100
    max_hp: int = 100
    mp: int = 50
    max_mp: int = 50
    alignment: int = 0
    weapon_item_id: int = 1
    weapon_enchant: int = 0
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
    removed: bool = False
    corpse_remove_at: float | None = None
    respawn_at: float | None = None


@dataclass
class GroundItemState:
    object_id: int
    item_id: int
    name: str
    count: int
    x: int
    y: int
    owner_id: int
    expires_at: float | None = None


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


@dataclass(frozen=True)
class WorldEvent:
    kind: str
    object_id: int
    npc_id: int


@dataclass(frozen=True)
class InventoryActionResult:
    accepted: bool
    message: str
    item_id: int = 0
    remaining: int = 0
