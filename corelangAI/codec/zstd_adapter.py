
from __future__ import annotations
import os, io, json, struct, typing as T
import zstandard as zstd

DEFAULT_LEVEL = 5
DEFAULT_THREADS = 0
DICT_MAGIC = b"CLAI_ZSTD_DICT1\0"
DICT_VERSION = 1

class ZstdDictManager:
    def __init__(self, path: str):
        self.path = path
        self._dict: T.Optional[zstd.ZstdCompressionDict] = None
        self.name: str = ""
        self.version: int = DICT_VERSION

    def load(self) -> T.Optional[zstd.ZstdCompressionDict]:
        if not os.path.exists(self.path): return None
        with open(self.path, "rb") as f:
            data = f.read()
        if not data.startswith(DICT_MAGIC):
            raise ValueError("Invalid dict file magic")
        off = len(DICT_MAGIC)
        ver = int.from_bytes(data[off:off+4], "little"); off += 4
        nlen = int.from_bytes(data[off:off+4], "little"); off += 4
        name = data[off:off+nlen].decode("utf-8"); off += nlen
        raw = data[off:]
        d = zstd.ZstdCompressionDict(raw)
        d.precompute_compress(level=DEFAULT_LEVEL)
        self._dict = d
        self.name = name
        self.version = ver
        return d

    def save(self, name: str, raw: bytes) -> None:
        hdr = DICT_MAGIC + (DICT_VERSION).to_bytes(4,"little") + (len(name)).to_bytes(4,"little") + name.encode("utf-8")
        with open(self.path, "wb") as f:
            f.write(hdr + raw)
        self.name = name

    def ensure_loaded(self) -> T.Optional[zstd.ZstdCompressionDict]:
        return self._dict or self.load()

def train_dictionary(samples: T.Iterable[bytes], dict_size: int = 64*1024) -> bytes:
    trainer = zstd.ZstdTrainer(dict_size=dict_size)
    for s in samples:
        trainer.add_sample(s)
    return trainer.train()

def compress_block(data: bytes, level: int = DEFAULT_LEVEL, dct: T.Optional[zstd.ZstdCompressionDict]=None, threads: int = DEFAULT_THREADS) -> bytes:
    cctx = zstd.ZstdCompressor(level=level, dict_data=dct, threads=threads)
    return cctx.compress(data)

def decompress_block(data: bytes, dct: T.Optional[zstd.ZstdCompressionDict]=None) -> bytes:
    dctx = zstd.ZstdDecompressor(dict_data=dct)
    return dctx.decompress(data)

def compress_stream(src: io.BufferedReader, dst: io.BufferedWriter, level: int = DEFAULT_LEVEL, dct=None, threads: int = DEFAULT_THREADS, chunk=256*1024):
    cctx = zstd.ZstdCompressor(level=level, dict_data=dct, threads=threads)
    with cctx.stream_writer(dst) as writer:
        while True:
            buf = src.read(chunk)
            if not buf: break
            writer.write(buf)

def decompress_stream(src: io.BufferedReader, dst: io.BufferedWriter, dct=None, chunk=256*1024):
    dctx = zstd.ZstdDecompressor(dict_data=dct)
    with dctx.stream_reader(src) as reader:
        while True:
            buf = reader.read(chunk)
            if not buf: break
            dst.write(buf)

def capa_descriptor() -> dict:
    return {
        "symbol": "CMP_ZSTD1",
        "type": "codec",
        "modes": ["block","stream"],
        "dict": True,
        "params": {
            "level": {"min":1, "max":22, "default": DEFAULT_LEVEL},
            "threads": {"min":0, "max":16, "default": DEFAULT_THREADS}
        },
        "announce": {
            "ZSTD_DICT1": {"fields": ["version","name","size"], "blob": True}
        }
    }
