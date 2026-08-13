import socket
import threading
import time
from pathlib import Path

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 7867
UPSTREAM_HOST = "35.236.188.39"
UPSTREAM_PORT = 7867

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "tcp_proxy_capture.log"

lock = threading.Lock()

def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with lock:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

def hex_preview(data, limit=512):
    shown = data[:limit]
    s = shown.hex(" ")
    if len(data) > limit:
        s += f" ... (+{len(data)-limit} bytes)"
    return s

def relay(src, dst, direction):
    try:
        while True:
            data = src.recv(65535)
            if not data:
                log(f"{direction} CLOSE")
                break
            log(f"{direction} {len(data)} bytes | {hex_preview(data)}")
            dst.sendall(data)
    except Exception as e:
        log(f"{direction} ERROR: {e}")
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except:
            pass

def handle(client, addr):
    log(f"CLIENT CONNECT {addr[0]}:{addr[1]}")
    upstream = None
    try:
        upstream = socket.create_connection((UPSTREAM_HOST, UPSTREAM_PORT), timeout=10)
        upstream.settimeout(None)
        client.settimeout(None)
        log(f"UPSTREAM CONNECT {UPSTREAM_HOST}:{UPSTREAM_PORT}")

        t1 = threading.Thread(target=relay, args=(client, upstream, "C->S"), daemon=True)
        t2 = threading.Thread(target=relay, args=(upstream, client, "S->C"), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception as e:
        log(f"SESSION ERROR: {e}")
    finally:
        try:
            client.close()
        except:
            pass
        if upstream:
            try:
                upstream.close()
            except:
                pass
        log(f"SESSION END {addr[0]}:{addr[1]}")

def main():
    log(f"PROXY listening {LISTEN_HOST}:{LISTEN_PORT} -> {UPSTREAM_HOST}:{UPSTREAM_PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((LISTEN_HOST, LISTEN_PORT))
        s.listen(20)
        while True:
            client, addr = s.accept()
            threading.Thread(target=handle, args=(client, addr), daemon=True).start()

if __name__ == "__main__":
    main()
