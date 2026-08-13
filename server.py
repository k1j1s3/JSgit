#!/usr/bin/env python3
# Clean-room local compatibility test for the user's own captured guest session.
# Does not connect to the real game server.

import socket
import select
import time
import zlib
import base64
import struct
import sqlite3
import sys
from pathlib import Path

from core import (
    CoreGame,
    extend_inventory_snapshot,
    make_character_status,
    make_inventory_entry,
    make_inventory_snapshot,
    captured_inventory_entry,
    rewrite_inventory_entry,
)

HOST = "0.0.0.0"
PORT = 7867
VERSION = "WORLD-INTERACTION-PACK-1.0"
SEED1 = 0x412A6C59
SEED2 = 0x5216255D
SESSION_STARTED_AT = time.monotonic()

S_HELLO_REPLY = bytes.fromhex("55 35 03 08 00 10 07 18 8e 87 bd 8d 07 20 8e 87 bd 8d 07 28 fd ac ef c0 07 30 8e 87 bd 8d 07 38 98 f1 eb d3 06 40 00 48 00 50 82 fb fd e7 07 58 99 db ec d3 06 60 fa ed a5 dc 06 68 e5 e3 cf 47 70 e5 f3 dc 4c 78 8b b2 ca df 06 80 01 d9 9a d7 df 06 88 01 00 3f 81")
POST_LOGIN = [
    bytes.fromhex("55 ee 27 0a 00 12 01 30 18 00 19 61"),
    bytes.fromhex("78 64 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("a3 3d 00 8d 27 00 00 00 00 00"),
]
AFTER_33 = [
    bytes.fromhex("0f 01 04"),
    bytes.fromhex("55 41 03 08 07 10 00 a1 68"),
    bytes.fromhex("13 0a 01 00 00 00 00 00"),
    bytes.fromhex("5d eb a7 88 ea b3 b0 ec 82 ac 31 00 00 0d 00 00 00 1c 02 5c 00 00 0a 11 0c 10 06 07 09 00 cb 27 35 01 34 2d 7b 6a 0f 00 00 00 00 56 a0 00 00"),
    bytes.fromhex("13 40"),
]
FINAL_REPLY_TO_8E = bytes.fromhex("55 27 28 08 01 55 e0")

# 133 S->C plaintext packets recovered from the user's successful session,
# covering the large world/character initialization burst after client opcode 0x05.
WORLD_BURST_B64 = """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"""

POST_INIT_REPLY_1 = bytes.fromhex("55 f5 27 08 00 98 c4")
POST_INIT_REPLY_2 = bytes.fromhex("55 3f 28 08 b9 af 57 10 01 6c e7")
POST_15_REPLY = bytes.fromhex("55 50 02 08 11 10 f8 19 22 07 24 32 33 30 32 30 32 22 09 e5 a4 9a e5 a4 9a e5 a4 9a 22 00 22 00 50 00 50 00 50 00 50 00 72 00 97 0d")
WELCOME_WORLD = bytes.fromhex("61 00 17 8e 01 00 e6 ad a1 e8 bf 8e e4 be 86 e5 88 b0 e9 81 8a e6 88 b2 e4 b8 96 e7 95 8c 00 00 00 00")

# Object/actor id observed for the user's captured character.
ACTOR_ID = 1431481
CHAR_UID = bytes.fromhex("eb a7 88 ea b3 b0 ec 82 ac 31")

# Step 9: data-driven monster test.
DB_PATH = Path(__file__).parent / "data" / "lineager_server_data.sqlite"
TEST_NPC_ID = 14464         # 凶暴的山豬 (fierce wild boar) used by the packet template
TEST_MONSTER_OBJ_ID = 9000001
CONFIG_PATH = Path(__file__).parent / "config" / "server.json"
RUNTIME_DB_PATH = Path(__file__).parent / "data" / "runtime.sqlite"



def unpack_world_burst():
    raw = zlib.decompress(base64.b64decode(WORLD_BURST_B64))
    out = []
    pos = 0
    while pos < len(raw):
        n = int.from_bytes(raw[pos:pos+2], "little")
        pos += 2
        out.append(raw[pos:pos+n])
        pos += n
    return out


WORLD_BURST = unpack_world_burst()
BASE_INVENTORY_PACKET = next(
    packet for packet in WORLD_BURST if packet.startswith(b"\x55\x4c\x02")
)
CAPTURED_INVENTORY_PACKETS = tuple(
    packet for packet in WORLD_BURST if packet.startswith(b"\x55\x4c\x02")
)


def captured_item_template(item_id):
    for packet in CAPTURED_INVENTORY_PACKETS:
        try:
            return captured_inventory_entry(packet, item_id)
        except KeyError:
            continue
    raise KeyError(f"captured item template not found: {item_id}")


def init_state(seed1, seed2):
    key = seed1.to_bytes(4, "little") + seed2.to_bytes(4, "little")
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % 8]) & 0xFF
        s[i], s[j] = s[j], s[i]
    return s


def crypt_packet(state, payload):
    i = 0
    j = 0
    out = bytearray(payload)
    for k in range(len(out)):
        i = (i + 1) & 0xFF
        j = (j + state[i]) & 0xFF
        state[i], state[j] = state[j], state[i]
        out[k] ^= state[(state[i] + state[j]) & 0xFF]
    return bytes(out)


def recv_exact(sock, n):
    b = bytearray()
    while len(b) < n:
        chunk = sock.recv(n - len(b))
        if not chunk:
            raise ConnectionError("client closed")
        b.extend(chunk)
    return bytes(b)


def recv_frame(sock):
    hdr = recv_exact(sock, 2)
    total = int.from_bytes(hdr, "little")
    if total < 2 or total > 65535:
        raise ValueError(f"invalid frame length {total}")
    return hdr + recv_exact(sock, total - 2)


def recv_plain(sock, c_state, label):
    frame = recv_frame(sock)
    plain = crypt_packet(c_state, frame[2:])
    op = plain[0] if plain else None
    elapsed = time.monotonic() - SESSION_STARTED_AT
    print(f"[+{elapsed:07.3f}s] {label} len={len(plain)} op={('0x%02X' % op) if op is not None else 'NONE'} | {plain.hex(' ')}")
    return plain


def send_plain(sock, s_state, payload, label=None):
    encrypted = crypt_packet(s_state, payload)
    frame = (len(encrypted) + 2).to_bytes(2, "little") + encrypted
    sock.sendall(frame)
    if label:
        elapsed = time.monotonic() - SESSION_STARTED_AT
        print(f"[+{elapsed:07.3f}s] {label} len={len(payload)} op=0x{payload[0]:02X}")


def make_seed():
    p = b"\xCC" + SEED1.to_bytes(4, "little") + SEED2.to_bytes(4, "little") + b"\x00\x00"
    return (len(p) + 2).to_bytes(2, "little") + p


def make_move_ack(x, y, heading):
    # Observed S->C movement update:
    # 0x23 | actor_id:u32 LE | x:u16 LE | y:u16 LE | heading:u8 | 0:u16
    return (
        b"\x23"
        + ACTOR_ID.to_bytes(4, "little")
        + int(x).to_bytes(2, "little")
        + int(y).to_bytes(2, "little")
        + bytes([heading & 0xFF])
        + b"\x00\x00"
    )


def make_object_action(obj_id, action_id):
    """S_ACTION (0x51): object id u32 LE + action id u8.

    The current client native handler reads exactly these two fields and queues
    the action on the matching PixesAvatar. Step 10 uses action 1 for the
    attacker swing and action 2 for the target damage reaction.
    """
    return b"\x51" + struct.pack("<I", int(obj_id) & 0xFFFFFFFF) + bytes([int(action_id) & 0xFF])



def encode_varint(value):
    value = int(value)
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def pb_varint(field_no, value):
    return encode_varint((field_no << 3) | 0) + encode_varint(value)


def pb_bytes(field_no, data):
    return (
        encode_varint((field_no << 3) | 2)
        + encode_varint(len(data))
        + data
    )


def make_object_remove(obj_id):
    return bytes([0xB9]) + int(obj_id).to_bytes(4, "little", signed=False)


def make_chat_reply(text, actor_id, x, y):
    """
    Reconstructed from the normal server response observed immediately
    after LOCALTEST123.

    Wire form:
      55 | 04 02 | protobuf | 00 00

    The captured protobuf decoded as:
      field 1  = 71
      field 2  = 0
      field 3  = chat UTF-8 text
      field 5  = 10-byte character UID
      field 6  = 7
      field 7  = sender object ID
      field 8  = sender X
      field 9  = sender Y
      field 12 = 1
      field 13 = 0

    0x0204 is the server-side chat message ID observed in the trace.
    """
    text_b = text.encode("utf-8", errors="replace")[:240]

    proto = b"".join([
        pb_varint(1, 71),
        pb_varint(2, 0),
        pb_bytes(3, text_b),
        pb_bytes(5, CHAR_UID),
        pb_varint(6, 7),
        pb_varint(7, actor_id),
        pb_varint(8, x),
        pb_varint(9, y),
        pb_varint(12, 1),
        pb_varint(13, 0),
    ])

    return b"\x55\x04\x02" + proto + b"\x00\x00"



def encode_varint_u64(value):
    """Raw protobuf varint, including two's-complement int64 negatives."""
    value = int(value) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def pb_int64(field_no, value):
    return encode_varint((field_no << 3) | 0) + encode_varint_u64(value)


def pack_xy(x, y):
    """ObjactInfo.objXY is a signed 32-bit (y<<16 | x) stored in int64."""
    packed = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
    if packed & 0x80000000:
        packed -= 0x100000000
    return packed


def load_test_npc(npc_id=TEST_NPC_ID):
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Missing {DB_PATH.name}. Keep it in the same folder as this server script."
        )
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT * FROM npcs WHERE npc_id=?", (int(npc_id),)
        ).fetchone()
        if row is None:
            row = con.execute(
                "SELECT * FROM npcs WHERE hp>0 AND gfxid>0 ORDER BY npc_id LIMIT 1"
            ).fetchone()
        if row is None:
            raise RuntimeError("No usable NPC row found in DB")
        return dict(row)
    finally:
        con.close()


def _read_pb_varint_raw(buf, pos):
    start = pos
    value = 0
    shift = 0
    while pos < len(buf):
        b = buf[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, pos, buf[start:pos]
        shift += 7
    raise ValueError("truncated protobuf varint")


def _rewrite_top_level_varints(proto, replacements):
    """Preserve a captured protobuf byte-for-byte except selected varint fields."""
    out = bytearray()
    pos = 0
    while pos < len(proto):
        key, pos_after_key, key_raw = _read_pb_varint_raw(proto, pos)
        field_no = key >> 3
        wire = key & 7
        out += key_raw
        pos = pos_after_key

        if wire == 0:
            old, pos2, raw = _read_pb_varint_raw(proto, pos)
            if field_no in replacements:
                out += encode_varint_u64(replacements[field_no])
            else:
                out += raw
            pos = pos2
        elif wire == 1:
            out += proto[pos:pos+8]
            pos += 8
        elif wire == 2:
            ln, pos2, ln_raw = _read_pb_varint_raw(proto, pos)
            out += ln_raw
            out += proto[pos2:pos2+ln]
            pos = pos2 + ln
        elif wire == 5:
            out += proto[pos:pos+4]
            pos += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
    return bytes(out)


def make_monster_object_packet(npc, obj_id, x, y, heading=6):
    """STEP 9E diagnostic: clone a *real live field monster* packet.

    This packet was captured from the normal server for the monster whose
    rendered name token is $27331 (凶暴的山豬 / fierce wild boar).

    Decoded live fields:
      objGfxId=8414
      objNpcId=28928
      objLevel=10
      type102=10
      NpcMaxHp=50
      activeAttackType=0

    The hot-update DB row for the same monster is:
      npc_id=14464, gfxid=4207, name_token=$27331, level=10, hp=50
    so this is also a confirmed example where wire npc/gfx ids are DB values * 2.

    Only objXY / objId / heading are rewritten; every other actor/state field is
    preserved byte-for-byte from the real normal-server monster packet.
    """
    captured = bytes.fromhex(
        "55 77 00 "
        "08 fd ff a5 82 f8 ff ff ff ff 01 "
        "10 f2 ec 7c "
        "18 de 41 "
        "20 00 "
        "28 01 "
        "30 00 "
        "38 01 "
        "40 17 "
        "4a 06 24 32 37 33 33 31 "
        "52 00 58 00 60 00 68 00 70 00 78 00 "
        "80 01 00 88 01 00 90 01 00 98 01 00 "
        "a2 01 00 aa 01 00 b0 01 00 "
        "b8 01 ff ff ff ff ff ff ff ff ff 01 "
        "c0 01 0a "
        "d0 01 ff ff ff ff ff ff ff ff ff 01 "
        "d8 01 00 e0 01 00 "
        "f0 01 ff ff ff ff ff ff ff ff ff 01 "
        "98 02 00 "
        "b8 02 80 e2 01 "
        "c2 02 0b 30 00 39 00 00 00 00 00 00 00 00 "
        "90 03 00 c8 06 00 80 07 00 "
        "a0 07 0a a8 07 32 b8 07 00 "
        "00 00"
    )
    if not captured.startswith(b"\x55\x77\x00"):
        raise RuntimeError("live monster template malformed")
    proto = captured[3:-2]
    proto = _rewrite_top_level_varints(proto, {
        1: pack_xy(x, y),
        2: int(obj_id),
        5: int(heading),
    })
    return b"\x55\x77\x00" + proto + b"\x00\x00"

def read_varint(buf, pos):
    value = 0
    shift = 0
    while pos < len(buf) and shift < 64:
        b = buf[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, pos
        shift += 7
    raise ValueError("bad protobuf varint")


def parse_chat_rpc(p):
    """
    Observed client packet:
      8e | rpc_id:u16 LE | protobuf_len:u16 LE | protobuf

    LOCALTEST123 capture:
      rpc_id = 0x0202
      protobuf = 1a 0c "LOCALTEST123" 08 01 10 00

    Protobuf fields observed:
      field 1 = chat type/channel-like value (1)
      field 2 = secondary mode/value (0)
      field 3 = UTF-8 chat text
    """
    if len(p) < 5 or p[0] != 0x8E:
        return None

    rpc_id = int.from_bytes(p[1:3], "little")
    n = int.from_bytes(p[3:5], "little")
    body = p[5:5+n]

    result = {
        "rpc_id": rpc_id,
        "declared_len": n,
        "actual_len": len(body),
        "field1": None,
        "field2": None,
        "text": None,
        "body": body,
    }

    pos = 0
    try:
        while pos < len(body):
            tag, pos = read_varint(body, pos)
            field = tag >> 3
            wire = tag & 7

            if wire == 0:
                value, pos = read_varint(body, pos)
                if field == 1:
                    result["field1"] = value
                elif field == 2:
                    result["field2"] = value
            elif wire == 2:
                ln, pos = read_varint(body, pos)
                data = body[pos:pos+ln]
                pos += ln
                if field == 3:
                    result["text"] = data.decode("utf-8", errors="replace")
            elif wire == 1:
                pos += 8
            elif wire == 5:
                pos += 4
            else:
                break
    except Exception:
        pass

    return result


STORE_PAGE0_B64 = """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"""
STORE_PAGE1_B64 = """eNoTZgxVV+dgFGpg5DgbIlQNJASYJBlAwGG+gyIDFGgskDdiVTE0sjS2YnBg9GAI4IhgSWDIAguZFJy4t/QsRwVjEyNDF6O4k2+8kZmBYbx3ZmpOvHtRfnlJRnxAdvosRiYViwWMjBsYGXYxMlxgZLjBuHiy6ANGxheMDB8YGTqYGIRaGDnOhQjVAwmYEwqWIznhgx7ECaZQJzBEMMCcYIbiBDmQE0wNLOOD8stT81KAzgjIL8nMz4t3yq+INzDG4pKZYJdAnCHByOcIANjPRHs="""


def unpack_packet_blob(encoded):
    raw = zlib.decompress(base64.b64decode(encoded))
    packets = []
    pos = 0
    while pos < len(raw):
        n = int.from_bytes(raw[pos:pos+2], "little")
        pos += 2
        packets.append(raw[pos:pos+n])
        pos += n
    return packets


STORE_PAGE0 = unpack_packet_blob(STORE_PAGE0_B64)
STORE_PAGE1 = unpack_packet_blob(STORE_PAGE1_B64)


def handle(client, addr):
    print(f"[{time.strftime('%H:%M:%S')}] CLIENT CONNECT {addr[0]}:{addr[1]}")
    # The client opens its login socket while the animated title screen is
    # still visible. Leave enough time for app startup or human/ADB entry taps.
    client.settimeout(600)
    c_state = init_state(SEED1, SEED2)
    s_state = init_state(SEED1, SEED2)

    client.sendall(make_seed())
    print("S->C SEED")

    # Initial hello
    p = recv_plain(client, c_state, "C->S #1")
    if not p or p[0] != 0x8E:
        raise RuntimeError("expected initial 0x8E")
    send_plain(client, s_state, S_HELLO_REPLY, "S->C hello reply")

    # Device/login packet
    p = recv_plain(client, c_state, "C->S #2")
    if not p or p[0] != 0x01:
        raise RuntimeError("expected 0x01")
    for pkt in POST_LOGIN:
        send_plain(client, s_state, pkt)

    # Ack
    p = recv_plain(client, c_state, "C->S #3")
    if not p or p[0] != 0x33:
        raise RuntimeError("expected 0x33")
    for pkt in AFTER_33:
        send_plain(client, s_state, pkt)

    # Second 0x8E. A reconnect may insert a small 0x10 keepalive here; consume
    # it instead of aborting an otherwise valid login sequence.
    p = recv_plain(client, c_state, "C->S #4")
    while p and p[0] == 0x10:
        print("[LOGIN] Ignored reconnect keepalive opcode 0x10")
        p = recv_plain(client, c_state, "C->S #4-CONTINUE")
    if not p or p[0] != 0x8E:
        raise RuntimeError("expected second 0x8E")
    send_plain(client, s_state, FINAL_REPLY_TO_8E)

    # Delayed character/world-entry request
    client.settimeout(15)
    p = recv_plain(client, c_state, "C->S #5")
    if not p or p[0] != 0x05:
        raise RuntimeError("expected delayed 0x05")

    print()
    print(f"[WORLD] Sending {len(WORLD_BURST)} captured initialization packets...")
    # Send the captured initialization burst without replaying capture timing.
    # Delaying the final packet only extends the client's movement lock.
    for pkt in WORLD_BURST:
        if pkt.startswith(b"\x55\x4c\x02"):
            print("[WORLD] Skipped captured inventory; runtime snapshot will replace it.")
            continue
        send_plain(client, s_state, pkt)
    print("[WORLD] Initial burst sent.")

    # In the successful session the client then emitted 18 init/query packets.
    client.settimeout(10)
    expected_ops = []
    for i in range(18):
        p = recv_plain(client, c_state, f"C->S INIT{i+1:02d}")
        expected_ops.append(p[0] if p else None)

    print("[WORLD] Client init opcodes:", " ".join(
        f"0x{x:02X}" if x is not None else "--" for x in expected_ops
    ))

    send_plain(client, s_state, POST_INIT_REPLY_1, "S->C post-init #1")
    send_plain(client, s_state, POST_INIT_REPLY_2, "S->C post-init #2")

    # Client's larger 0x15 world-state acknowledgement follows a few seconds later.
    client.settimeout(10)
    p = recv_plain(client, c_state, "C->S WORLD-ACK")
    if not p or p[0] != 0x15:
        print("[WARN] expected opcode 0x15")
    else:
        print("[SUCCESS] Client reached world-state acknowledgement 0x15.")

    send_plain(client, s_state, POST_15_REPLY, "S->C world-ack reply")
    # Step10B: do not block the socket for five seconds after world ACK.
    # The old delay made movement appear frozen because MOVE requests were not read/ACKed.
    send_plain(client, s_state, WELCOME_WORLD, "S->C welcome-world")

    print()
    print("[SUCCESS] Local server sent the world-entry sequence.")
    print("[ACTION] If the game field is visible, move exactly ONE tile.")
    print("[ACTION] Movement + chat + shop + captured REAL field-monster spawn + first combat animation response are enabled. Unknown RPCs will be logged.")

    # Keep the local session alive and respond to movement/chat.
    # These are the starting coordinates of the captured local world snapshot.
    local_x = 32720
    local_y = 32817

    game = CoreGame(DB_PATH, RUNTIME_DB_PATH, CONFIG_PATH)
    player_state = game.load_player(ACTOR_ID)
    player_state.x, player_state.y = local_x, local_y
    game.runtime.save_player(player_state)

    # Data-driven monster spawn from the current hot-update DB.
    npc = load_test_npc()
    monster_x = local_x + 3
    monster_y = local_y
    monster_state = game.spawn_monster(
        TEST_NPC_ID, TEST_MONSTER_OBJ_ID, monster_x, monster_y
    )
    last_combat_anim_at = 0.0
    combat_anim_interval = 0.55
    last_monster_attack_at = time.monotonic()
    player_revive_at = None
    monster_packet = make_monster_object_packet(
        npc, TEST_MONSTER_OBJ_ID, monster_x, monster_y, heading=6
    )
    # Step10B: spawn immediately; no extra one-second blocking delay.
    send_plain(client, s_state, monster_packet, "S->C LIVE-MONSTER-CLONE-9E")
    print(
        "[LIVE-MONSTER-9E] spawned "
        f"npc_id={npc['npc_id']} name={npc.get('name_zh_tw')!r} "
        f"template_name='$27331' template_gfx=8414 template_npc_id=28928 DB_reference='14464/4207' "
        f"obj_id={TEST_MONSTER_OBJ_ID} x={monster_x} y={monster_y}"
    )
    print(f"[ACTION] Look 3 tiles to the right. Attack the living fierce wild boar. Step {VERSION} should animate combat without a startup block.")

    def send_notice(text):
        send_plain(
            client,
            s_state,
            make_chat_reply(text, ACTOR_ID, local_x, local_y),
            "S->C SYSTEM-NOTICE",
        )

    def send_ui_state():
        send_plain(
            client,
            s_state,
            make_character_status(player_state),
            "S->C CHARACTER-STATUS-UI",
        )
        inventory = game.runtime.inventory(ACTOR_ID)
        entries = []
        inventory_objects.clear()
        for index, (item_id, count) in enumerate(sorted(inventory.items())):
            item = game.content.load_item(item_id)
            item_object_id = 9_100_000 + index
            if item_id in (292532, 80581):
                # Preserve the exact object id used by the captured equipment
                # and detail caches. Only its runtime count is rewritten.
                item_object_id = 1_431_489 if item_id == 292532 else 1_431_507
                entries.append(rewrite_inventory_entry(
                    captured_item_template(item_id),
                    item_object_id, count,
                    equipped=(
                        item_id == player_state.weapon_item_id
                        or any(value[0] == item_id for value in game.runtime.equipment(ACTOR_ID).values())
                    ),
                ))
            else:
                entries.append(make_inventory_entry(
                    item, item_object_id, count,
                    equipped=(item_id == player_state.weapon_item_id),
                ))
            inventory_objects[item_object_id] = item_id
        send_plain(
            client,
            s_state,
            make_inventory_snapshot(BASE_INVENTORY_PACKET, tuple(entries)),
            "S->C INVENTORY-UI-SNAPSHOT",
        )
        print(
            f"[UI-SYNC] status level={player_state.level} exp={player_state.exp} "
            f"inventory={inventory}"
        )

    inventory_objects = {}

    def process_world_events():
        nonlocal last_monster_attack_at, player_revive_at
        now = time.monotonic()
        attack_interval = float(game.config["combat"].get("monster_attack_interval", 2.5))
        attack_range = int(game.config["combat"].get("monster_attack_range", 3))
        in_attack_range = max(
            abs(player_state.x - monster_state.x),
            abs(player_state.y - monster_state.y),
        ) <= attack_range
        if (
            monster_state.alive and player_state.hp > 0 and in_attack_range
            and now - last_monster_attack_at >= attack_interval
        ):
            last_monster_attack_at = now
            result = game.monster_attack(TEST_MONSTER_OBJ_ID, ACTOR_ID)
            if result.accepted:
                send_plain(
                    client, s_state,
                    make_object_action(TEST_MONSTER_OBJ_ID, 1),
                    "S->C MONSTER-ATTACK-ACTION",
                )
                time.sleep(0.06)
                send_plain(
                    client, s_state,
                    make_object_action(ACTOR_ID, 2),
                    "S->C PLAYER-DAMAGE-ACTION",
                )
                send_plain(client, s_state, make_character_status(player_state), "S->C PLAYER-HP-SYNC")
                print(
                    f"[PLAYER-DAMAGE] damage={result.damage} "
                    f"hp={result.hp_before}->{result.hp_after} AC={player_state.armor_class} "
                    f"killed={result.killed}"
                )
                if result.killed:
                    player_revive_at = now + float(
                        game.config["combat"].get("player_respawn_seconds", 5.0)
                    )
                    send_notice("You were defeated. Automatic revival in 5 seconds.")
        if player_revive_at is not None and now >= player_revive_at:
            game.revive_player(ACTOR_ID)
            player_revive_at = None
            send_plain(client, s_state, make_character_status(player_state), "S->C PLAYER-REVIVE-STATUS")
            send_notice("Revived with full HP and MP")
            print(f"[PLAYER-REVIVE] hp={player_state.hp}/{player_state.max_hp} mp={player_state.mp}/{player_state.max_mp}")
        for event in game.tick():
            if event.kind == "remove":
                send_plain(
                    client,
                    s_state,
                    make_object_remove(event.object_id),
                    "S->C MONSTER-REMOVE",
                )
                print(f"[WORLD] corpse removed obj_id={event.object_id}")
            elif event.kind == "respawn":
                send_plain(
                    client,
                    s_state,
                    monster_packet,
                    "S->C MONSTER-RESPAWN",
                )
                print(
                    f"[WORLD] monster respawned obj_id={event.object_id} "
                    f"hp={monster_state.hp}/{monster_state.max_hp}"
                )
                send_notice("Fierce wild boar respawned")
            elif event.kind == "ground-expire":
                send_plain(client, s_state, make_object_remove(event.object_id), "S->C GROUND-ITEM-EXPIRE")
                print(f"[GROUND-DROP] expired obj_id={event.object_id}")

    # Some reconnects do not emit the optional repeated 0x15 acknowledgement.
    # Send persisted state on every successful world entry, not only from that
    # later branch, so the captured level-10/default status cannot remain shown.
    send_ui_state()

    repeated_world_ack_handled = False
    client.settimeout(30)
    while True:
        readable, _, _ = select.select([client], [], [], 0.25)
        if not readable:
            process_world_events()
            continue
        p = recv_plain(client, c_state, "C->S LIVE")

        if not p:
            continue

        if p[0] == 0x15:
            # The client sends a second world-state acknowledgement after the
            # field becomes visible. At this point it is ready to consume the
            # final 0x61 world-unlock packet; an earlier copy may be ignored
            # while the scene is still loading.
            if not repeated_world_ack_handled:
                repeated_world_ack_handled = True
                print("[WORLD] Repeated world-state acknowledgement received.")
                send_plain(
                    client,
                    s_state,
                    POST_15_REPLY,
                    "S->C repeated world-ack reply",
                )
                send_plain(
                    client,
                    s_state,
                    WELCOME_WORLD,
                    "S->C repeated welcome-world/unlock",
                )
                send_ui_state()
            else:
                print("[UI] Additional 0x15 acknowledgement received; no world/UI replay.")

        elif p[0] == 0x0A and len(p) == 10:
            x = int.from_bytes(p[1:3], "little")
            y = int.from_bytes(p[3:5], "little")
            heading = p[5]
            seq = int.from_bytes(p[6:10], "little")
            local_x, local_y = x, y
            game.move_player(ACTOR_ID, x, y)
            print(f"[WALK] x={x} y={y} heading={heading} seq={seq}")
            send_plain(client, s_state, make_move_ack(x, y, heading), "S->C MOVE-ACK")

        elif p[0] == 0x0B and len(p) >= 13:
            get_x = int.from_bytes(p[1:3], "little")
            get_y = int.from_bytes(p[3:5], "little")
            item_obj_id = int.from_bytes(p[5:9], "little", signed=False)
            item_count = int.from_bytes(p[9:13], "little", signed=False)
            print(
                f"[PICKUP] C_GET x={get_x} y={get_y} "
                f"obj_id={item_obj_id} count={item_count}"
            )
            result = game.pickup_ground_item(ACTOR_ID, item_obj_id, item_count)
            print(f"[PICKUP] accepted={result.accepted} {result.message}")
            send_notice(result.message)
            if result.accepted:
                send_plain(client, s_state, make_object_remove(item_obj_id), "S->C GROUND-ITEM-REMOVE")
                send_ui_state()

        elif p[0] == 0x1C and len(p) >= 5:
            item_object_id = int.from_bytes(p[1:5], "little", signed=False)
            item_id = inventory_objects.get(item_object_id)
            print(f"[ITEM-CLICK] obj_id={item_object_id} item_id={item_id}")
            if item_id is None:
                send_notice(f"Unknown inventory object {item_object_id}; UI refreshed")
                send_ui_state()
                continue
            item = game.content.load_item(item_id)
            if int(item.get("weapon_type") or 0) > 0:
                if player_state.weapon_item_id == item_id:
                    result = game.unequip_weapon(ACTOR_ID)
                else:
                    result = game.equip_weapon(ACTOR_ID, item_id)
            elif int(item.get("equipment_index") or 0) > 0:
                equipped_armor = {
                    value[0] for value in game.runtime.equipment(ACTOR_ID).values()
                }
                if item_id in equipped_armor:
                    result = game.unequip_armor(ACTOR_ID, item_id)
                else:
                    result = game.equip_armor(ACTOR_ID, item_id)
            else:
                result = game.use_item(ACTOR_ID, item_id)
            print(f"[ITEM-ACTION] accepted={result.accepted} {result.message}")
            send_notice(result.message)
            send_ui_state()

        elif p[0] == 0x89 and len(p) >= 5:
            target_id = int.from_bytes(p[1:5], "little", signed=False)
            print(f"[ATTACK] C_ATTACK_CONTINUE target_obj_id={target_id}")
            if target_id == TEST_MONSTER_OBJ_ID:
                now = time.monotonic()
                if now - last_combat_anim_at >= combat_anim_interval:
                    last_combat_anim_at = now
                    result = game.attack(ACTOR_ID, target_id)
                    if not result.accepted:
                        print(f"[COMBAT] rejected reason={result.reason}")
                        continue
                    send_plain(
                        client, s_state,
                        make_object_action(ACTOR_ID, 1),
                        "S->C PLAYER-ATTACK-ACTION",
                    )
                    if result.hit:
                        time.sleep(0.06)
                        action_id = 8 if result.killed else 2
                        label = "S->C MONSTER-DEATH-ACTION" if result.killed else "S->C MONSTER-DAMAGE-ACTION"
                        send_plain(
                            client, s_state,
                            make_object_action(TEST_MONSTER_OBJ_ID, action_id),
                            label,
                        )
                    print(
                        f"[COMBAT] hit={result.hit} damage={result.damage} "
                        f"hp={result.hp_before}->{result.hp_after} "
                        f"critical={result.critical} killed={result.killed}"
                    )
                    if result.killed:
                        drop_text = ", ".join(
                            f"{drop.item_id}:{drop.name}x{drop.count}" for drop in result.drops
                        ) or "none"
                        print(
                            f"[REWARD] exp=+{result.exp_gained} "
                            f"player_level={player_state.level} player_exp={player_state.exp} "
                            f"drops=[{drop_text}] persisted={RUNTIME_DB_PATH.name}"
                        )
                        ground_text = game.ground_items_text()
                        send_notice(
                            f"Defeated boar: EXP +{result.exp_gained}; {ground_text}"
                        )
                        send_ui_state()
                else:
                    print("[COMBAT-ANIM] duplicate auto-attack request throttled")
            elif target_id == 0:
                print("[ATTACK] auto-attack stop")

        elif p[0] == 0x8E:
            rpc = parse_chat_rpc(p)
            if rpc is None:
                print("[RPC] Could not parse 0x8E wrapper")
                continue

            print(
                f"[RPC] id=0x{rpc['rpc_id']:04X} "
                f"declared_len={rpc['declared_len']} actual_len={rpc['actual_len']}"
            )

            if rpc["rpc_id"] == 0x0202 and rpc["text"] is not None:
                print(
                    f"[CHAT] text={rpc['text']!r} "
                    f"field1={rpc['field1']} field2={rpc['field2']}"
                )

                command = rpc["text"].strip().lower()
                if command == ".status":
                    reply_text = game.status_text(ACTOR_ID)
                elif command in (".inventory", ".inv"):
                    reply_text = game.inventory_text(ACTOR_ID)
                elif command in (".equipment", ".gear"):
                    reply_text = game.equipment_text(ACTOR_ID)
                elif command == ".drops":
                    reply_text = game.ground_items_text()
                elif command.startswith(".pickup "):
                    try:
                        object_id = int(command.split(maxsplit=1)[1])
                        result = game.pickup_ground_item(ACTOR_ID, object_id)
                        reply_text = result.message
                        if result.accepted:
                            send_ui_state()
                    except ValueError:
                        reply_text = "Usage: .pickup GROUND_OBJECT_ID"
                elif command.startswith(".equip "):
                    try:
                        item_id = int(command.split(maxsplit=1)[1])
                        reply_text = game.equip_weapon(ACTOR_ID, item_id).message
                        send_ui_state()
                    except ValueError:
                        reply_text = "Usage: .equip ITEM_ID"
                elif command == ".unequip":
                    reply_text = game.unequip_weapon(ACTOR_ID).message
                    send_ui_state()
                elif command.startswith(".use "):
                    try:
                        item_id = int(command.split(maxsplit=1)[1])
                        reply_text = game.use_item(ACTOR_ID, item_id).message
                        send_ui_state()
                    except ValueError:
                        reply_text = "Usage: .use ITEM_ID"
                elif command.startswith(".item "):
                    try:
                        item_id = int(command.split(maxsplit=1)[1])
                        reply_text = game.item_detail_text(item_id)
                    except ValueError:
                        reply_text = "Usage: .item ITEM_ID"
                elif command == ".help":
                    reply_text = "Commands: .status .inventory .equipment .drops .pickup OBJ .item ID .equip ID .unequip .use ID .help"
                else:
                    reply_text = rpc["text"]

                reply = make_chat_reply(reply_text, ACTOR_ID, local_x, local_y)
                send_plain(
                    client,
                    s_state,
                    reply,
                    "S->C LOCAL-CHAT"
                )
                print(
                    f"[CHAT] Local 0x55/0x0204 reply sent "
                    f"actor={ACTOR_ID} x={local_x} y={local_y}."
                )

            elif rpc["rpc_id"] == 0x2725:
                page = rpc["field1"]
                print(f"[SHOP] catalog request page={page}")

                if page == 0:
                    print(
                        f"[SHOP] Sending {len(STORE_PAGE0)} captured "
                        "0x55/0x2726 catalog packets..."
                    )
                    for pkt in STORE_PAGE0:
                        send_plain(client, s_state, pkt)
                    print("[SHOP] Catalog page 0 sent.")

                elif page == 1:
                    print(
                        f"[SHOP] Sending {len(STORE_PAGE1)} captured "
                        "0x55/0x2727 follow-up packet..."
                    )
                    for pkt in STORE_PAGE1:
                        send_plain(client, s_state, pkt)
                    print("[SHOP] Catalog page 1 sent.")

                else:
                    print(
                        f"[SHOP] Unknown catalog page={page}; "
                        "keeping connection open."
                    )

            elif rpc["rpc_id"] == 0x03E9:
                # Periodic client time/keepalive request. The paired server RPC
                # is 0x03EA and echoes the fixed64 timestamp payload.
                heartbeat_reply = b"\x55\xea\x03" + rpc["body"] + b"\x00\x00"
                send_plain(
                    client,
                    s_state,
                    heartbeat_reply,
                    "S->C HEARTBEAT-0x03EA",
                )
                print("[HEARTBEAT] replied 0x03E9 -> 0x03EA")

            else:
                print(
                    f"[RPC UNKNOWN] id=0x{rpc['rpc_id']:04X} "
                    f"protobuf={rpc['body'].hex(' ')}"
                )
                print(
                    "[RPC UNKNOWN] Connection remains open. "
                    "This is likely the next feature to implement."
                )

        else:
            print(
                f"[LIVE] Unhandled opcode 0x{p[0]:02X} "
                f"len={len(p)} payload={p.hex(' ')}"
            )


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    print(f"[LOCAL SERVER STEP {VERSION}] listening on {HOST}:{PORT}")
    print(f"[LOCAL SERVER STEP {VERSION}] embedded world-init packets={len(WORLD_BURST)}")
    print(f"[LOCAL SERVER STEP {VERSION}] Real game server is NOT contacted.")
    print()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(5)

        while True:
            client, addr = server.accept()
            try:
                global SESSION_STARTED_AT
                SESSION_STARTED_AT = time.monotonic()
                client.settimeout(600)
                handle(client, addr)
            except KeyboardInterrupt:
                client.close()
                raise
            except Exception as e:
                print(f"[ERROR] {e}")
            finally:
                try:
                    client.close()
                except Exception:
                    pass
                print(f"[{time.strftime('%H:%M:%S')}] SESSION END")
                print()


if __name__ == "__main__":
    main()
