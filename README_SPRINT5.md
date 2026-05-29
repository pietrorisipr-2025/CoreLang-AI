# CL5X v5 — Deadlines, Backpressure, Pub/Sub Topics, QUIC Multistream

## Novità
- **Deadlines** per messaggi (TTL ms): lo scheduler droppa i messaggi scaduti prima di frammentarli.
- **Backpressure per CHID** con **token bucket** (byte/ms) → limita l'overload per canale.
- **Pub/Sub**: `publish(topic, ...)` e `subscribe(topic, handler)`; il topic è aggiunto all'header v5 (12B + varint topic).
- **Multistream QUIC**: i frame sono restituiti come `(chid, raw)` così il client può mapparli su stream distinti.

## File
- `cl5x_transport_v5.py` — transport v5 pronto per TCP/QUIC.
- `cl5x_quic_echo_multistream.py` — echo QUIC con uno stream per CHID.

## Uso rapido
```bash
pip install aioquic
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=localhost"

# Server QUIC multistream
python cl5x_quic_echo_multistream.py --mode server --host 0.0.0.0 --port 4434 --cert cert.pem --key key.pem

# Client QUIC multistream (usa due CHID alternati)
python cl5x_quic_echo_multistream.py --mode client --host 127.0.0.1 --port 4434 --count 200 --size 2048 --chid 1
```
