"""Core game-domain package for the local compatibility server."""

from .game import CoreGame
from .models import AttackResult, DropReward, MonsterState, PlayerState

__all__ = ["AttackResult", "CoreGame", "DropReward", "MonsterState", "PlayerState"]

