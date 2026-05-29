# cl5x_echo.py — minimal TCP echo using CL5X v4 framing
import socket, struct, threading, time, argparse, zlib
from dataclasses import dataclass
from typing import Optional, List, Tuple

MAGIC=b"CL5X"; VER=1
TYPE_DATA=1; TYPE_ACK=2
FLAG_CH_PRESENT=0x02; FLAG_SEQ_PRESENT=0x04; FLAG_MORE=0x08

def enc_varint(x:int)->bytes:
    out=bytearray()
    while True:
        b=x & 0x7F; x >>= 7
        out.append(b | (0x80 if x else 0))
        if not x: break
    return bytes(out)

def dec_varint(buf:bytes, off:int)->Tuple[int,int]:
    shift=0; val=0; pos=off
    while True:
        b=buf[pos]; pos+=1
        val |= (b & 0x7F) << shift
        if (b & 0x80)==0: return val,pos
        shift += 7

@dataclass
class Frame:
    type:int; flags:int; dict_id:int; payload:bytes; chid:int=1; seq:int=0

def _crc32(b:bytes)->int:
    import zlib; return zlib.crc32(b) & 0xFFFFFFFF

def encode_frame(f:Frame)->bytes:
    head=bytearray()
    head += MAGIC
    head += struct.pack("B", VER)
    head += struct.pack("B", f.type & 0xFF)
    head += struct.pack("B", f.flags & 0xFF)
    head += enc_varint(f.chid)
    head += enc_varint(f.dict_id)
    head += enc_varint(f.seq)
    head += enc_varint(len(f.payload))
    body=bytes(head)+f.payload
    return body + struct.pack(">I", _crc32(body))

def recv_exact(sock, n):
    buf=b""
    while len(buf)<n:
        chunk=sock.recv(n-len(buf))
        if not chunk: raise ConnectionError("closed")
        buf+=chunk
    return buf

def read_frame(sock)->Frame:
    # naive framing: scan for MAGIC (not optimized)
    prefix=b""
    while True:
        prefix += recv_exact(sock, 1)
        idx=prefix.find(MAGIC)
        if idx==-1: 
            if len(prefix)>4096: prefix=prefix[-4:]
            continue
        if len(prefix)-idx < 4+1+1+1: prefix += recv_exact(sock, (4+1+1+1)-(len(prefix)-idx))
        base = prefix[idx:]
        ver=base[4]; t=base[5]; flags=base[6]
        off=7
        chid, off = dec_varint(base, off)
        dict_id, off = dec_varint(base, off)
        seq, off = dec_varint(base, off)
        # read len varint (may require more bytes)
        while len(base)<off+1: base += recv_exact(sock, 1)
        # attempt to parse len varint progressively
        tmp_off=off
        while True:
            if len(base)<=tmp_off: base += recv_exact(sock, 1)
            b=base[tmp_off]; tmp_off+=1
            if (b & 0x80)==0: break
        # compute length value
        def dec_varint_once(buf, off):
            shift=0; val=0; pos=off
            while True:
                b=buf[pos]; pos+=1
                val |= (b & 0x7F) << shift
                if (b & 0x80)==0: return val,pos
                shift+=7
        length, off2 = dec_varint_once(base, off)
        # ensure we have payload+crc
        need = off2 + length + 4
        while len(base)<need: base += recv_exact(sock, need-len(base))
        payload=base[off2:off2+length]
        return Frame(t, flags, dict_id, payload, chid, seq)

def server(port:int):
    s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port)); s.listen(16)
    print(f"CL5X echo server listening on :{port}")
    while True:
        conn, addr = s.accept()
        print("client:", addr)
        threading.Thread(target=handle_client, args=(conn,), daemon=True).start()

def handle_client(conn:socket.socket):
    with conn:
        while True:
            f = read_frame(conn)
            # echo back same payload, same chid, increasing seq
            reply = Frame(TYPE_DATA, FLAG_CH_PRESENT|FLAG_SEQ_PRESENT, f.dict_id, f.payload, chid=f.chid, seq=f.seq)
            raw = encode_frame(reply)
            conn.sendall(raw)

def client(host:str, port:int, count:int=10, size:int=1024):
    s=socket.socket(); s.connect((host,port))
    seq=0
    for i in range(count):
        payload = os.urandom(size)
        f=Frame(TYPE_DATA, FLAG_CH_PRESENT|FLAG_SEQ_PRESENT, 0x1A3, payload, chid=1, seq=seq); seq+=1
        raw=encode_frame(f)
        s.sendall(raw)
        r=read_frame(s)
        assert r.payload==payload
        print("echo ok", len(payload))
    s.close()

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["server","client"], required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5555)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--size", type=int, default=1024)
    args=ap.parse_args()
    if args.mode=="server": server(args.port)
    else: client(args.host, args.port, args.count, args.size)
