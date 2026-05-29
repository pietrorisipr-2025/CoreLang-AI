# cl5x_quic_echo.py
# QUIC echo using aioquic (install: pip install aioquic). Uses CL5XTransport for framing.
# NOTE: Requires TLS certs; see README_quic.md for instructions.
import asyncio, time, argparse, os
from cl5x_transport_v4 import CL5XTransport

def now_ms(): return int(time.time()*1000)

async def quic_server(host, port, cert, key):
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.asyncio import serve
    from aioquic.asyncio.protocol import QuicConnectionProtocol

    class CL5XQuicServer(QuicConnectionProtocol):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            def on_msg(chid:int, data:bytes):
                # echo back on same CHID
                self.tx.enqueue_message(chid, 2, data, now_ms())
            self.tx = CL5XTransport(on_message=on_msg)

        def quic_event_received(self, event):
            from aioquic.quic.events import StreamDataReceived, ProtocolNegotiated
            if isinstance(event, ProtocolNegotiated):
                # open a bidirectional stream for CL5X channel 1 by default (we multiplex in-frame by CHID)
                pass
            elif isinstance(event, StreamDataReceived):
                self._on_stream_data(event.stream_id, event.data, event.end_stream)

        def _on_stream_data(self, stream_id: int, data: bytes, end_stream: bool):
            out = self.tx.feed_bytes(now_ms(), data)
            for raw in out + self.tx.next_frames_to_send(now_ms()):
                self._quic.send_stream_data(stream_id, raw, end_stream=False)
            self.transmit()

    configuration = QuicConfiguration(is_client=False, alpn_protocols=["cl5x/1"])
    configuration.load_cert_chain(cert, key)
    await serve(host, port, configuration=configuration, create_protocol=CL5XQuicServer)

async def quic_client(host, port, count, size, chid):
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.asyncio import connect
    configuration = QuicConfiguration(is_client=True, alpn_protocols=["cl5x/1"])
    async with connect(host, port, configuration=configuration) as client:
        quic = client._quic
        stream_id = quic.get_next_available_stream_id(is_unidirectional=False)
        client._quic.send_stream_data(stream_id, b"", end_stream=False)
        def on_msg(chid:int, data:bytes):
            nonlocal got
            got += 1
        tx = CL5XTransport(on_message=on_msg)
        got=0
        # queue messages
        for i in range(count):
            tx.enqueue_message(chid, 2, os.urandom(size), now_ms())
        while got < count:
            frames = tx.next_frames_to_send(now_ms())
            for raw in frames:
                quic.send_stream_data(stream_id, raw, end_stream=False)
            await client.wait_closed(timeout=0.001)
            await asyncio.sleep(0.003)
        # we're done
        quic.send_stream_data(stream_id, b"", end_stream=True)
        await asyncio.sleep(0.1)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["server","client"], required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4433)
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
