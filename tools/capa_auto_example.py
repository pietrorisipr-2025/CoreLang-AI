
"""
Minimal example integrating CapaAuto with your transport.
Replace send_control/recv_control/publish_ckb with your real functions.
"""
import json, time
from capa_auto import CapaAuto

class IOAdapter:
    def __init__(self, send_control, recv_control, publish_ckb):
        self.send_control = send_control
        self.recv_control = recv_control
        self.publish_ckb = publish_ckb

# Dummy stubs (replace with your transport)
def _send_control(b: bytes): 
    # send on control channel
    print("[control→]", b.decode(errors="ignore")[:120])

def _recv_control(timeout=None) -> bytes:
    # fake READY for demo purposes
    time.sleep(0.1)
    return b'{"type":"READY"}'

def _publish_ckb(kind, blob, **meta):
    print(f"[CKB publish] kind={kind} bytes={len(blob)} meta={meta}")

if __name__ == "__main__":
    io = IOAdapter(_send_control, _recv_control, _publish_ckb)
    capa = CapaAuto(io, config_path="tools/capa_config.json")
    ok = capa.ensure_ready(my_peer_id="local", peer_id="remote-peer-123")
    print("READY:", ok)
