
"""
CAPA Auto Orchestrator for CorelangAI
-------------------------------------
Zero-touch CAPA negotiation + provisioning + resume + ready.
Drop-in: put this file into corelangAI/tools/capa_auto.py and call ensure_ready().
"""
import os, json, time, hashlib, threading

def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _read(path):
    with open(path,"rb") as f: return f.read()

class CapaAuto:
    def __init__(self, io, config_path="tools/capa_config.json"):
        """
        io: object with three callables
            io.send_control(b: bytes) -> None
            io.recv_control(timeout: float=None) -> bytes
            io.publish_ckb(kind: str, blob: bytes, **meta) -> None
        config_path: JSON with defaults (timeouts, residual, limits)
        """
        self.io = io
        self.cfg = self._load_config(config_path)
        self.peer_cache_dir = self.cfg.get("peer_cache_dir", "peers")
        os.makedirs(self.peer_cache_dir, exist_ok=True)

    def _load_config(self, path):
        try:
            return json.load(open(path,"r",encoding="utf-8"))
        except Exception:
            # defaults
            return {
                "proto_ver": "1.0",
                "features": ["zstd","crc32"],
                "residual": {"codec":"zstd","dict_id":"d1","level":6},
                "limits": {"max_frame":32768, "anchor_every":8},
                "timeouts": {"init_sec":4.0, "ack_sec":4.0, "ready_sec":4.0},
                "retries": {"init":3, "publish":2},
                "peer_cache_dir": "peers",
                "accept_d1_supplement": True
            }

    def _profile_path(self, peer_id):
        return os.path.join(self.peer_cache_dir, f"PROFILE_{peer_id}.json")

    def _load_profile(self, peer_id):
        p = self._profile_path(peer_id)
        if os.path.exists(p):
            try: return json.load(open(p,"r",encoding="utf-8"))
            except Exception: return None
        return None

    def _save_profile(self, peer_id, snapshot):
        try:
            json.dump(snapshot, open(self._profile_path(peer_id),"w",encoding="utf-8"), indent=2)
        except Exception:
            pass

    def _offer_snapshot(self):
        # prepares current D0/D1/D3 hashes and sizes
        d = "dict"
        d0 = _read(os.path.join(d,"ckb_D0_control.bin"))
        d3_blob = _read(os.path.join(d,"ckb_D3_phrases.json")) if os.path.exists(os.path.join(d,"ckb_D3_phrases.json")) else b""
        d1_list = []
        for fname in sorted(os.listdir(d)):
            lf = fname.lower()
            if lf.startswith("ckb_d1_") and lf.endswith(".bin"):
                blob = _read(os.path.join(d,fname))
                name = fname.split("ckb_D1_")[-1].replace(".bin","")
                d1_list.append({"name": name, "file": fname, "sha": _sha256_bytes(blob), "bytes": len(blob)})
        snap = {
            "D0": {"sha": _sha256_bytes(d0), "bytes": len(d0)},
            "D1": [{"name": e["name"], "sha": e["sha"], "bytes": e["bytes"]} for e in d1_list],
            "D3": {"sha": _sha256_bytes(d3_blob), "bytes": len(d3_blob)} if d3_blob else None
        }
        return snap, d1_list, d0, d3_blob

    def ensure_ready(self, my_peer_id: str, peer_id: str) -> bool:
        """Run CAPA RESUME if possible, else full CAPA INIT/ACK + provisioning, then READY↔READY."""
        cfg = self.cfg
        profile = self._load_profile(peer_id)
        snap, d1_list, d0_blob, d3_blob = self._offer_snapshot()

        # Try RESUME if we have a profile
        if profile and "ckb_offer" in profile:
            msg = {
                "type":"CAPA_RESUME",
                "peer_id": my_peer_id,
                "proto_ver": cfg.get("proto_ver","1.0"),
                "ckb_have": profile["ckb_offer"],
            }
            self.io.send_control(json.dumps(msg).encode())
            try:
                resp = json.loads(self.io.recv_control(timeout=cfg["timeouts"]["ack_sec"]).decode("utf-8","ignore"))
                if resp.get("type")=="CAPA_ACK" and resp.get("resume_ok") is True:
                    self.io.send_control(b'{"type":"READY"}')
                    r = json.loads(self.io.recv_control(timeout=cfg["timeouts"]["ready_sec"]).decode("utf-8","ignore"))
                    return r.get("type")=="READY"
            except Exception:
                pass  # fall back to full CAPA

        # Full CAPA
        capa_init = {
            "type":"CAPA_INIT",
            "peer_id": my_peer_id,
            "proto_ver": cfg.get("proto_ver","1.0"),
            "features": cfg.get("features", []),
            "ckb_offer": {
                "D0": snap["D0"],
                "D1": snap["D1"],
                "D3": snap["D3"],
            },
            "residual": cfg.get("residual", {"codec":"zstd","dict_id":"d1","level":6}),
            "limits": cfg.get("limits", {"max_frame":32768,"anchor_every":8}),
            "keepalive": {"interval_ms": 3000}
        }
        self.io.send_control(json.dumps(capa_init).encode())
        ack = json.loads(self.io.recv_control(timeout=cfg["timeouts"]["ack_sec"]).decode("utf-8","ignore"))
        need = ack.get("ckb_need", {}) if isinstance(ack, dict) else {}

        # D0
        if need.get("D0") in ("request","missing"):
            self.io.publish_ckb("D0", d0_blob)

        # D1
        need_d1 = set(need.get("D1", []))
        for b in d1_list:
            if b["name"] in need_d1:
                self.io.publish_ckb("D1", _read(os.path.join("dict", b["file"])), block=b["name"], sha=b["sha"])

        # D1 supplement (optional)
        supp_path = os.path.join("dict","ckb_D1_supplement_notes.bin")
        if os.path.exists(supp_path) and ack.get("features", {}).get("accept_d1_supplement", True):
            self.io.publish_ckb("D1", _read(supp_path), block="supplement")

        # D3
        if need.get("D3") in ("request","missing"):
            if snap["D3"]:
                self.io.publish_ckb("D3", d3_blob)

        # READY
        self.io.send_control(b'{"type":"READY"}')
        r = json.loads(self.io.recv_control(timeout=cfg["timeouts"]["ready_sec"]).decode("utf-8","ignore"))
        ok = (r.get("type")=="READY")
        if ok:
            self._save_profile(peer_id, {"ckb_offer": capa_init["ckb_offer"], "residual": capa_init["residual"], "limits": capa_init["limits"]})
        return ok
