"""Core game-domain package for the local compatibility server."""

from .game import CoreGame
from .models import AttackResult, DropReward, InventoryActionResult, MonsterState, PlayerState, WorldEvent
from .ui_protocol import extend_inventory_snapshot, make_character_status, make_inventory_entry

__all__ = [
    "AttackResult", "CoreGame", "DropReward", "InventoryActionResult",
    "MonsterState", "PlayerState", "WorldEvent",
    "extend_inventory_snapshot", "make_character_status", "make_inventory_entry"
]
