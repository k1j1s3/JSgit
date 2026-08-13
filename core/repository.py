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

    def load_item(self, item_id: int) -> dict:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM items WHERE item_id=?", (item_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown item_id={item_id}")
        return dict(row)

    def try_load_item(self, item_id: int) -> dict | None:
        try:
            return self.load_item(item_id)
        except KeyError:
            return None


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
                    intelligence INTEGER NOT NULL DEFAULT 9,
                    wisdom INTEGER NOT NULL DEFAULT 6,
                    constitution INTEGER NOT NULL DEFAULT 16,
                    charisma INTEGER NOT NULL DEFAULT 7,
                    armor_class INTEGER NOT NULL,
                    hp INTEGER NOT NULL DEFAULT 100,
                    max_hp INTEGER NOT NULL DEFAULT 100,
                    mp INTEGER NOT NULL DEFAULT 50,
                    max_mp INTEGER NOT NULL DEFAULT 50,
                    alignment INTEGER NOT NULL DEFAULT 0,
                    weapon_item_id INTEGER NOT NULL,
                    weapon_enchant INTEGER NOT NULL DEFAULT 0,
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS equipment (
                    object_id INTEGER NOT NULL,
                    slot INTEGER NOT NULL,
                    item_id INTEGER NOT NULL,
                    enchant INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (object_id, slot)
                )
                """
            )
            existing = {
                row[1] for row in connection.execute("PRAGMA table_info(players)")
            }
            migrations = {
                "intelligence": "INTEGER NOT NULL DEFAULT 9",
                "wisdom": "INTEGER NOT NULL DEFAULT 6",
                "constitution": "INTEGER NOT NULL DEFAULT 16",
                "charisma": "INTEGER NOT NULL DEFAULT 7",
                "hp": "INTEGER NOT NULL DEFAULT 100",
                "max_hp": "INTEGER NOT NULL DEFAULT 100",
                "mp": "INTEGER NOT NULL DEFAULT 50",
                "max_mp": "INTEGER NOT NULL DEFAULT 50",
                "alignment": "INTEGER NOT NULL DEFAULT 0",
                "weapon_enchant": "INTEGER NOT NULL DEFAULT 0",
            }
            for column, definition in migrations.items():
                if column not in existing:
                    connection.execute(
                        f"ALTER TABLE players ADD COLUMN {column} {definition}"
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
                    object_id, name, level, exp, strength, dexterity, intelligence,
                    wisdom, constitution, charisma, armor_class, hp, max_hp, mp,
                    max_mp, alignment, weapon_item_id, weapon_enchant, x, y
                ) VALUES (
                    :object_id, :name, :level, :exp, :strength, :dexterity,
                    :intelligence, :wisdom, :constitution, :charisma,
                    :armor_class, :hp, :max_hp, :mp, :max_mp, :alignment,
                    :weapon_item_id, :weapon_enchant, :x, :y
                )
                ON CONFLICT(object_id) DO UPDATE SET
                    name=excluded.name, level=excluded.level, exp=excluded.exp,
                    strength=excluded.strength, dexterity=excluded.dexterity,
                    intelligence=excluded.intelligence, wisdom=excluded.wisdom,
                    constitution=excluded.constitution, charisma=excluded.charisma,
                    armor_class=excluded.armor_class,
                    hp=excluded.hp, max_hp=excluded.max_hp, mp=excluded.mp,
                    max_mp=excluded.max_mp, alignment=excluded.alignment,
                    weapon_item_id=excluded.weapon_item_id,
                    weapon_enchant=excluded.weapon_enchant,
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

    def ensure_item(self, object_id: int, item_id: int, count: int = 1) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO inventories (object_id, item_id, count)
                VALUES (?, ?, ?)
                ON CONFLICT(object_id, item_id) DO NOTHING
                """,
                (object_id, item_id, max(1, count)),
            )
            connection.commit()

    def remove_item(self, object_id: int, item_id: int, count: int = 1) -> bool:
        count = max(1, int(count))
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT count FROM inventories WHERE object_id=? AND item_id=?",
                (object_id, item_id),
            ).fetchone()
            if row is None or int(row["count"]) < count:
                return False
            remaining = int(row["count"]) - count
            if remaining:
                connection.execute(
                    "UPDATE inventories SET count=? WHERE object_id=? AND item_id=?",
                    (remaining, object_id, item_id),
                )
            else:
                connection.execute(
                    "DELETE FROM inventories WHERE object_id=? AND item_id=?",
                    (object_id, item_id),
                )
            connection.commit()
            return True

    def delete_item(self, object_id: int, item_id: int) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM inventories WHERE object_id=? AND item_id=?",
                (object_id, item_id),
            )
            connection.commit()

    def inventory(self, object_id: int) -> dict[int, int]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT item_id, count FROM inventories WHERE object_id=?", (object_id,)
            ).fetchall()
        return {int(row["item_id"]): int(row["count"]) for row in rows}

    def equipment(self, object_id: int) -> dict[int, tuple[int, int]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT slot, item_id, enchant FROM equipment WHERE object_id=?",
                (object_id,),
            ).fetchall()
        return {
            int(row["slot"]): (int(row["item_id"]), int(row["enchant"]))
            for row in rows
        }

    def equip_item(self, object_id: int, slot: int, item_id: int, enchant: int = 0) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO equipment (object_id, slot, item_id, enchant)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(object_id, slot) DO UPDATE SET
                    item_id=excluded.item_id, enchant=excluded.enchant
                """,
                (object_id, slot, item_id, enchant),
            )
            connection.commit()

    def unequip_slot(self, object_id: int, slot: int) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM equipment WHERE object_id=? AND slot=?",
                (object_id, slot),
            )
            connection.commit()


def load_config(path: Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)
