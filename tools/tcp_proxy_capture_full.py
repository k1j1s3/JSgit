import socket
import threading
import time
from pathlib import Path

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 7867
UPSTREAM_HOST = "35.236.188.39"
UPSTREAM_PORT = 7867

OUT = Path("captures")
OUT.mkdir(exist_ok=True)

lock = threading.Lock()
session_counter = 0

def log(line, fh=None):
    msg = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {line}"
    print(msg, flush=True)
    if fh:
        with lock:
            fh.write(msg + "\n")
            fh.flush()

def parse_frames(buf):
    frames = []
    pos = 0
    while len(buf) - pos >= 2:
        L = int.from_bytes(buf[pos:pos+2], "little")
        if L < 2 or L > 65535:
            break
        if len(buf) - pos < L:
            break
        frames.append(buf[pos:pos+L])
        pos += L
    return frames, buf[pos:]

def relay(src, dst, direction, rawfh, txtfh):
    pending = b""
    try:
        while True:
            data = src.recv(65535)
            if not data:
                log(f"{direction} CLOSE", txtfh)
                break

            # Save exact raw stream with direction + chunk length
            tag = b"C" if direction == "C->S" else b"S"
            rawfh.write(tag + len(data).to_bytes(4, "little") + data)
            rawfh.flush()

            pending += data
            frames, pending = parse_frames(pending)
            for f in frames:
                log(f"{direction} FRAME {len(f)} | {f.hex(' ')}", txtfh)

            dst.sendall(data)

    except Exception as e:
        log(f"{direction} ERROR: {e}", txtfh)
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass

def handle(client, addr, sid):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    txt_path = OUT / f"session_{sid:03d}_{stamp}.log"
    raw_path = OUT / f"session_{sid:03d}_{stamp}.bin"

    with txt_path.open("w", encoding="utf-8") as txtfh, raw_path.open("wb") as rawfh:
        log(f"CLIENT CONNECT {addr[0]}:{addr[1]}", txtfh)
        upstream = None
        try:
            upstream = socket.create_connection((UPSTREAM_HOST, UPSTREAM_PORT), timeout=10)
            upstream.settimeout(None)
            client.settimeout(None)
            log(f"UPSTREAM CONNECT {UPSTREAM_HOST}:{UPSTREAM_PORT}", txtfh)

            t1 = threading.Thread(target=relay, args=(client, upstream, "C->S", rawfh, txtfh), daemon=True)
            t2 = threading.Thread(target=relay, args=(upstream, client, "S->C", rawfh, txtfh), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except Exception as e:
            log(f"SESSION ERROR: {e}", txtfh)
        finally:
            try:
                client.close()
            except Exception:
                pass
            if upstream:
                try:
                    upstream.close()
                except Exception:
                    pass
            log(f"SESSION END {addr[0]}:{addr[1]}", txtfh)

def main():
    global session_counter
    print(f"[FULL CAPTURE] listening {LISTEN_HOST}:{LISTEN_PORT} -> {UPSTREAM_HOST}:{UPSTREAM_PORT}", flush=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((LISTEN_HOST, LISTEN_PORT))
        s.listen(20)
        while True:
            client, addr = s.accept()
            session_counter += 1
            threading.Thread(target=handle, args=(client, addr, session_counter), daemon=True).start()

if __name__ == "__main__":
    main()
