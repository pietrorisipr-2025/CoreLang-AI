# cl5x_tcp_echo_full.py
# Async TCP echo using CL5XTransport v4 (SACK + adaptive FEC + 512B blocks)
import asyncio, time, argparse
from cl5x_transport_v4 import CL5XTransport

def now_ms(): return int(time.time()*1000)

async def run_server(host:str, port:int):
    async def handle(reader:asyncio.StreamReader, writer:asyncio.StreamWriter):
        peer=writer.get_extra_info("peername")
        print("client connected:", peer)
        # On receive, immediately echo back the same bytes as an app message
        def on_msg(chid:int, data:bytes):
            tx.enqueue_message(chid=chid, priority=2, data=data, now_ms=now_ms())
        tx=CL5XTransport(on_message=on_msg)
        async def sender_loop():
            while True:
                frames = tx.next_frames_to_send(now_ms())
                for raw in frames:
                    writer.write(raw)
                await writer.drain()
                await asyncio.sleep(0.003)
        async def receiver_loop():
            try:
                while True:
                    data = await reader.read(8192)
                    if not data: break
                    frames_out = tx.feed_bytes(now_ms(), data)
                    for raw in frames_out:
                        writer.write(raw)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        await asyncio.gather(sender_loop(), receiver_loop())
    server=await asyncio.start_server(handle, host, port)
    addrs=", ".join(str(sock.getsockname()) for sock in server.sockets)
    print(f"CL5X TCP echo listening on {addrs}")
    async with server: await server.serve_forever()

async def run_client(host:str, port:int, count:int, size:int, chid:int, priority:int):
    reader, writer = await asyncio.open_connection(host, port)
    got=0
    def on_msg(chid:int, data:bytes):
        nonlocal got
        got += 1
        # print("echoed", len(data))
    tx=CL5XTransport(on_message=on_msg)
    async def sender_loop():
        # queue messages
        for i in range(count):
            tx.enqueue_message(chid=chid, priority=priority, data=os.urandom(size), now_ms=now_ms())
        while got < count:
            frames = tx.next_frames_to_send(now_ms())
            for raw in frames: writer.write(raw)
            await writer.drain()
            await asyncio.sleep(0.003)
        writer.close(); await writer.wait_closed()
    async def receiver_loop():
        while True:
            data = await reader.read(8192)
            if not data: break
            frames_out = tx.feed_bytes(now_ms(), data)
            for raw in frames_out: writer.write(raw)
            await writer.drain()
    import os
    await asyncio.gather(sender_loop(), receiver_loop())
    print("client done, received", got, "echoes")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["server","client"], required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5556)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--chid", type=int, default=1)
    ap.add_argument("--priority", type=int, default=2)
    args=ap.parse_args()
    if args.mode=="server":
        asyncio.run(run_server(args.host, args.port))
    else:
        asyncio.run(run_client(args.host, args.port, args.count, args.size, args.chid, args.priority))

if __name__=="__main__":
    main()
