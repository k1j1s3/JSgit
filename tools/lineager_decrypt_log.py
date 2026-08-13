#!/usr/bin/env python3
import re
import struct
import sys
from pathlib import Path

FRAME_RE = re.compile(
    r'^\[(?P<ts>[^\]]+)\] (?P<dir>C->S|S->C) FRAME (?P<n>\d+) \| (?P<hex>[0-9a-fA-F ]+)$'
)

def init_rc4_state(seed1: int, seed2: int):
    # APK ByteArray::initKeys(int,int):
    # 8-byte key = seed1 little-endian || seed2 little-endian
    key = seed1.to_bytes(4, 'little') + seed2.to_bytes(4, 'little')
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % 8]) & 0xff
        s[i], s[j] = s[j], s[i]
    return s

def packet_crypt(s, payload: bytes) -> bytes:
    # APK copyNewBuffer/copyNewMsg:
    # i,j reset for EACH packet, while S itself persists/mutates.
    i = 0
    j = 0
    out = bytearray(payload)
    for k in range(len(out)):
        i = (i + 1) & 0xff
        j = (j + s[i]) & 0xff
        s[i], s[j] = s[j], s[i]
        t = (s[i] + s[j]) & 0xff
        out[k] ^= s[t] & 0xff
    return bytes(out)

def decode_known(direction, p):
    if not p:
        return ""
    op = p[0]

    # NetClient::Walk:
    # 0A | x:u16 LE | y:u16 LE | heading:u8 | seq:u32 LE
    if direction == "C->S" and op == 0x0A and len(p) == 10:
        x, y = struct.unpack_from("<HH", p, 1)
        heading = p[5]
        seq = struct.unpack_from("<I", p, 6)[0]
        return f"  [WALK] x={x} y={y} heading={heading} seq={seq}"

    # Observed server movement update candidate:
    # 23 | actor_id:u32 LE | x:u16 LE | y:u16 LE | heading:u8 | unknown:u16
    if direction == "S->C" and op == 0x23 and len(p) == 12:
        actor = struct.unpack_from("<I", p, 1)[0]
        x, y = struct.unpack_from("<HH", p, 5)
        heading = p[9]
        unknown = struct.unpack_from("<H", p, 10)[0]
        return f"  [MOVE_ACK?] actor={actor} x={x} y={y} heading={heading} unknown={unknown}"

    return ""

def main():
    if len(sys.argv) != 2:
        print("Usage: python lineager_decrypt_log.py session_xxx.log")
        raise SystemExit(2)

    src = Path(sys.argv[1])
    lines = src.read_text(encoding="utf-8", errors="replace").splitlines()

    parsed = []
    seed1 = seed2 = None
    seed_line_index = None

    for idx, line in enumerate(lines):
        m = FRAME_RE.match(line)
        if not m:
            continue
        raw = bytes.fromhex(m.group("hex"))
        if len(raw) < 2:
            continue
        wire_len = int.from_bytes(raw[:2], "little")
        payload = raw[2:]
        parsed.append((idx, m.group("ts"), m.group("dir"), wire_len, payload))

        # Seed packet is plaintext:
        # S->C total 13 bytes => payload:
        # CC | seed1:u32 LE | seed2:u32 LE | 00 00
        if (
            seed1 is None
            and m.group("dir") == "S->C"
            and wire_len == 13
            and len(payload) == 11
            and payload[0] == 0xCC
        ):
            seed1 = int.from_bytes(payload[1:5], "little")
            seed2 = int.from_bytes(payload[5:9], "little")
            seed_line_index = idx

    if seed1 is None:
        print("Could not find plaintext 0xCC seed packet.")
        raise SystemExit(1)

    c_state = init_rc4_state(seed1, seed2)
    s_state = init_rc4_state(seed1, seed2)

    out = []
    out.append(f"# Source: {src.name}")
    out.append(f"# seed1=0x{seed1:08X} seed2=0x{seed2:08X}")
    out.append("# First 0xCC S->C seed packet is plaintext and is NOT fed into RC4.")
    out.append("# C->S packets after the seed and S->C packets after the seed use independent cipher states.")
    out.append("")

    seen_seed = False
    for idx, ts, direction, wire_len, payload in parsed:
        if idx == seed_line_index:
            seen_seed = True
            out.append(
                f"[{ts}] {direction} SEED {wire_len} | {payload.hex(' ')}"
                f" | seed1=0x{seed1:08X} seed2=0x{seed2:08X}"
            )
            continue

        if not seen_seed:
            out.append(f"[{ts}] {direction} PRESEED {wire_len} | {payload.hex(' ')}")
            continue

        state = c_state if direction == "C->S" else s_state
        plain = packet_crypt(state, payload)
        note = decode_known(direction, plain)
        out.append(
            f"[{ts}] {direction} PLAIN payload={len(plain)} op=0x{plain[0]:02X} | {plain.hex(' ')}{note}"
        )

    dst = src.with_name(src.stem + "_decrypted.log")
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Seed1: 0x{seed1:08X}")
    print(f"Seed2: 0x{seed2:08X}")
    print(f"Written: {dst}")
    print()
    print("Known WALK packets:")
    for line in out:
        if "[WALK]" in line:
            print(line)

if __name__ == "__main__":
    main()
