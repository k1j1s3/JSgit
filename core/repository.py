from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import DropReward, MonsterState, PlayerState


class ContentRepository:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def load_monster(self, npc_id: int, object_id: int, x: int, y: int) -> MonsterState:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM npcs WHERE npc_id=?", (npc_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown npc_id={npc_id}")
        max_hp = max(1, int(row["hp"] or 1))
        return MonsterState(
            object_id=object_id,
            npc_id=npc_id,
            name=str(row["name_zh_tw"] or row["name_token"] or npc_id),
            level=max(1, int(row["level"] or 1)),
            max_hp=max_hp,
            hp=max_hp,
            armor_class=int(row["ac"] or 0),
            size_type=int(row["size_type"] or 0),
            x=x,
            y=y,
        )

    def weapon_damage(self, item_id: int, target_size: int) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT dmg_small, dmg_large FROM items WHERE item_id=?", (item_id,)
            ).fetchone()
        if row is None:
            return 1
        column = "dmg_large" if target_size else "dmg_small"
        return max(1, int(row[column] or 1))

    def drops_for(self, npc_id: int) -> tuple[DropReward, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT item_id, item_name_zh_tw FROM npc_drops WHERE npc_id=?",
                (npc_id,),
            ).fetchall()
        return tuple(
            DropReward(int(row["item_id"]), str(row["item_name_zh_tw"] or row["item_id"]))
            for row in rows
        )


class RuntimeRepository:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS players (
                    object_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    exp INTEGER NOT NULL,
                    strength INTEGER NOT NULL,
                    dexterity INTEGER NOT NULL,
                    armor_class INTEGER NOT NULL,
                    weapon_item_id INTEGER NOT NULL,
                    x INTEGER NOT NULL,
                    y INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS inventories (
                    object_id INTEGER NOT NULL,
                    item_id INTEGER NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (object_id, item_id)
                )
                """
            )
            connection.commit()

    def load_player(self, object_id: int, defaults: dict) -> PlayerState:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM players WHERE object_id=?", (object_id,)
            ).fetchone()
        if row is None:
            return PlayerState(object_id=object_id, **defaults)
        return PlayerState(**dict(row))

    def save_player(self, player: PlayerState) -> None:
        values = vars(player)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO players (
                    object_id, name, level, exp, strength, dexterity,
                    armor_class, weapon_item_id, x, y
                ) VALUES (
                    :object_id, :name, :level, :exp, :strength, :dexterity,
                    :armor_class, :weapon_item_id, :x, :y
                )
                ON CONFLICT(object_id) DO UPDATE SET
                    name=excluded.name, level=excluded.level, exp=excluded.exp,
                    strength=excluded.strength, dexterity=excluded.dexterity,
                    armor_class=excluded.armor_class,
                    weapon_item_id=excluded.weapon_item_id,
                    x=excluded.x, y=excluded.y
                """,
                values,
            )
            connection.commit()

    def add_items(self, object_id: int, rewards: tuple[DropReward, ...]) -> None:
        with closing(self._connect()) as connection:
            for reward in rewards:
                connection.execute(
                    """
                    INSERT INTO inventories (object_id, item_id, count)
                    VALUES (?, ?, ?)
                    ON CONFLICT(object_id, item_id) DO UPDATE SET
                        count=count + excluded.count
                    """,
                    (object_id, reward.item_id, reward.count),
                )
            connection.commit()

    def inventory(self, object_id: int) -> dict[int, int]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT item_id, count FROM inventories WHERE object_id=?", (object_id,)
            ).fetchall()
        return {int(row["item_id"]): int(row["count"]) for row in rows}


def load_config(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)
