from __future__ import annotations

import struct

from .models import PlayerState


def _varint(value: int) -> bytes:
    value = int(value) & 0xFFFFFFFFFFFFFFFF
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(output)


def _pb_varint(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _pb_bytes(field: int, value: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(value)) + value


def make_character_status(player: PlayerState) -> bytes:
    """Build the captured 0x0E fixed-width character-status layout."""
    # Unknown/reserved fields remain byte-identical to the working capture.
    payload = bytearray.fromhex(
        "0e b9 d7 15 00 0a c0 35 00 00 11 00 09 00 06 00 0c 00 "
        "10 00 07 00 1c 02 12 02 5c 00 5c 00 00 00 00 00 f0 ea "
        "1c 35 28 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 "
        "00 00"
    )
    stats = (
        player.strength,
        player.intelligence,
        player.wisdom,
        player.dexterity,
        player.constitution,
        player.charisma,
    )
    payload[1:5] = struct.pack("<I", player.object_id)
    payload[5] = max(1, min(255, player.level))
    payload[6:10] = struct.pack("<I", max(0, player.exp))
    payload[10:22] = struct.pack(
        "<6H", *(max(0, min(65535, value)) for value in stats)
    )
    payload[22:30] = struct.pack(
        "<4H", player.hp, player.max_hp, player.mp, player.max_mp
    )
    payload[30:32] = struct.pack("<h", player.armor_class)
    return bytes(payload)


def make_inventory_entry(item: dict, object_id: int, count: int) -> bytes:
    """Build one item entry for the captured 0x55/0x024C inventory snapshot."""
    name_token = str(item.get("name_token") or f"${item['item_id']}").encode("utf-8")
    option = b"".join([
        _pb_bytes(1, _pb_varint(1, 23)),
        _pb_varint(2, int(item.get("use_type") or 0)),
        _pb_varint(3, int(item.get("weight") or 0)),
        _pb_bytes(4, b""),
        _pb_varint(6, 0x7FFF),
    ])
    return b"".join([
        _pb_varint(1, object_id),
        _pb_varint(2, int(item["item_id"])),
        _pb_varint(3, object_id + 1_000_000),
        _pb_varint(4, max(1, count)),
        _pb_varint(5, 0),
        _pb_varint(7, int(item.get("grd_gfx") or 0)),
        _pb_varint(8, int(item.get("item_bless") or 2)),
        _pb_varint(9, int(item.get("inv_gfxid") or 0)),
        _pb_varint(11, 0),
        _pb_varint(13, 0),
        _pb_varint(14, 3),
        _pb_bytes(18, name_token),
        _pb_bytes(19, option),
        _pb_varint(22, 1),
        _pb_varint(23, 0),
        _pb_varint(24, int(item.get("equip") or 0)),
        _pb_varint(25, int(item.get("item_stage") or 1)),
        _pb_varint(26, 1),
        _pb_varint(27, 1),
        _pb_varint(108, int(item.get("item_desc") or item["item_id"])),
        _pb_varint(111, 0),
    ])


def extend_inventory_snapshot(base_packet: bytes, entries: tuple[bytes, ...]) -> bytes:
    if not base_packet.startswith(b"\x55\x4c\x02"):
        raise ValueError("not an inventory snapshot")
    base_proto = base_packet[3:-2]
    additions = b"".join(_pb_bytes(1, entry) for entry in entries)
    return b"\x55\x4c\x02" + base_proto + additions + b"\x00\x00"
