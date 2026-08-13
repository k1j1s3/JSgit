import socket, threading, argparse
from pathlib import Path
from datetime import datetime

ap=argparse.ArgumentParser()
ap.add_argument('--port',type=int,default=20000)
ap.add_argument('--host',default='0.0.0.0')
a=ap.parse_args()
LOG=Path(__file__).parent/'logs'/f'tcp_{a.port}.log'; LOG.parent.mkdir(exist_ok=True)

def handle(c,addr):
    print('[TCP] connect',addr)
    with LOG.open('a',encoding='utf-8') as f: f.write(f'\n=== CONNECT {datetime.now().isoformat()} {addr} ===\n')
    try:
        while True:
            d=c.recv(65535)
            if not d: break
            print(f'[TCP] {addr} {len(d)} bytes: {d[:64].hex()}')
            with LOG.open('a',encoding='utf-8') as f:
                f.write(f'{datetime.now().isoformat()} RX {len(d)} {d.hex()}\n')
            # No fabricated protocol reply yet; first capture the client's opening packet.
    finally:
        c.close(); print('[TCP] close',addr)

s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); s.bind((a.host,a.port)); s.listen()
print(f'[TCP] listening on {a.host}:{a.port}')
while True:
    c,addr=s.accept(); threading.Thread(target=handle,args=(c,addr),daemon=True).start()
