# QUIC Echo for CL5X (aioquic)

## Prerequisites
- Python 3.9+
- `pip install aioquic`

## Self-signed cert (dev)
```bash
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=localhost"
```

## Run
Server:
```bash
python cl5x_quic_echo.py --mode server --host 0.0.0.0 --port 4433 --cert cert.pem --key key.pem
```

Client:
```bash
python cl5x_quic_echo.py --mode client --host 127.0.0.1 --port 4433 --count 200 --size 2048 --chid 1
```

The transport uses **SACK-in-ACK**, **adaptive FEC(1,K)**, and **512B block segmentation** exactly like the TCP version; QUIC handles congestion + loss below, while CL5X manages prioritization and framing at the app layer.
