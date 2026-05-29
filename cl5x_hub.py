
# cl5x_hub.py — Multi-peer aggregator for CL5XLink peers with dedup / reconciliation
import time, hashlib
from typing import Dict, Callable

def _dec_varint(buf, off):
    shift=0; val=0; pos=off
    while True:
        b=buf[pos]; pos+=1
        val |= (b & 0x7F) << shift
        if (b & 0x80)==0: return val,pos
        shift += 7

class CL5XHub:
    def __init__(self, ttl_seen_sec=30.0):
        self.peers: Dict[str, Callable[[bytes],None]] = {}
        self.seen = {}  # ref_hex -> ts
        self.ttl_seen = ttl_seen_sec

    def register(self, peer_id:str, feed_func:Callable[[bytes],None]):
        self.peers[peer_id] = feed_func

    def broadcast(self, data:bytes, origin:str=None):
        # try to read ref_hash length and content from bitpacked frame
        try:
            off = 2  # skip 2B header (cbv small path)
            ref_len, off = _dec_varint(data, off)
            ref = data[off:off+ref_len]
            ref_hex = ref.hex()
        except Exception:
            ref_hex = hashlib.blake2s(data, digest_size=16).hexdigest()

        now = time.time()
        # purge old entries
        for k,ts in list(self.seen.items()):
            if (now - ts) > self.ttl_seen:
                del self.seen[k]
        if ref_hex in self.seen:
            return
        self.seen[ref_hex] = now

        for pid, feed in self.peers.items():
            if pid == origin: continue
            try:
                feed(data)
            except Exception:
                pass
