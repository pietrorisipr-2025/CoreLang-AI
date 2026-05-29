# cl5x_quic_echo_multistream.py
# QUIC echo that maps each CHID to its own QUIC stream, using CL5XTransportV5.
import asyncio, time, os
from cl5x_transport_v5 import CL5XTransportV5

def now_ms(): return int(time.time()*1000)

async def quic_server(host, port, cert, key):
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.asyncio import serve
    from aioquic.asyncio.protocol import QuicConnectionProtocol

    class Server(QuicConnectionProtocol):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.stream_for_chid = {}  # chid -> stream_id
            def on_msg(chid:int, data:bytes, topic:int=0):
                # echo the same payload back on same CHID (and thus same stream)
                tx.publish(topic=topic, data=data, priority=2, ttl_ms=3000, chid=chid, now_ms=now_ms())
            self.tx = CL5XTransportV5(on_message=on_msg)

        def quic_event_received(self, event):
            from aioquic.quic.events import StreamDataReceived, ProtocolNegotiated
            if isinstance(event, ProtocolNegotiated):
                pass
            elif isinstance(event, StreamDataReceived):
                sid=event.stream_id
                outputs = self.tx.feed_bytes(self._chid_for_stream(sid), now_ms(), event.data)
                # send outputs per CHID on their streams
                for chid, raw in outputs + self.tx.next_frames_to_send(now_ms()):
                    sid2 = self._ensure_stream_for_chid(chid)
                    self._quic.send_stream_data(sid2, raw, end_stream=False)
                self.transmit()

        def _chid_for_stream(self, stream_id:int)->int:
            # reverse map if known, else default to 1 until we parse a frame
            for c,s in self.stream_for_chid.items():
                if s==stream_id: return c
            return 1

        def _ensure_stream_for_chid(self, chid:int)->int:
            sid = self.stream_for_chid.get(chid)
            if sid is None:
                sid = self._quic.get_next_available_stream_id(is_unidirectional=False)
                self.stream_for_chid[chid]=sid
            return sid

    configuration = QuicConfiguration(is_client=False, alpn_protocols=["cl5x/1"])
    configuration.load_cert_chain(cert, key)
    await serve(host, port, configuration=configuration, create_protocol=Server)

async def quic_client(host, port, count, size, chid):
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.asyncio import connect

    configuration = QuicConfiguration(is_client=True, alpn_protocols=["cl5x/1"])
    async with connect(host, port, configuration=configuration) as client:
        quic = client._quic
        stream_for_chid = {}
        def ensure_stream(chid:int)->int:
            sid = stream_for_chid.get(chid)
            if sid is None:
                sid = quic.get_next_available_stream_id(is_unidirectional=False)
                stream_for_chid[chid]=sid
            return sid

        got=0
        def on_msg(ch:int, data:bytes, topic:int=0):
            nonlocal got; got += 1
        tx = CL5XTransportV5(on_message=on_msg)
        # subscribe example topic 42
        tx.subscribe(42, lambda topic,data: None)

        # produce messages across two CHIDs to demonstrate multistream
        for i in range(count):
            ch = chid if i%2==0 else (chid+1)
            tx.publish(topic=42, data=os.urandom(size), priority=2, ttl_ms=2000, chid=ch, now_ms=now_ms())

        # IO loop
        async def reader():
            while got < count:
                event = await client.wait_closed(timeout=0.001)
                await asyncio.sleep(0.001)

        async def sender():
            while got < count:
                for ch, raw in tx.next_frames_to_send(now_ms()):
                    quic.send_stream_data(ensure_stream(ch), raw, end_stream=False)
                await asyncio.sleep(0.003)

        await asyncio.gather(reader(), sender())
        # graceful close
        for sid in list(stream_for_chid.values()):
            quic.send_stream_data(sid, b"", end_stream=True)
        await asyncio.sleep(0.1)

def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["server","client"], required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4434)
    ap.add_argument("--cert", default="cert.pem")
    ap.add_argument("--key", default="key.pem")
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--chid", type=int, default=1)
    args=ap.parse_args()
    if args.mode=="server":
        asyncio.run(quic_server(args.host, args.port, args.cert, args.key))
    else:
        asyncio.run(quic_client(args.host, args.port, args.count, args.size, args.chid))

if __name__=="__main__":
    main()
