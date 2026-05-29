# CL5X v4 — Block-aligned segmenter + Adaptive FEC + SACK

What's new:
- 512B **block-aligned fragmentation** (better for FEC and caches).
- **Adaptive FEC**: K chosen by loss-EMA from SACK bitmaps (>=5%→K=4, >=2%→K=5, >=1%→K=6; else off).
- **SACK-in-ACK** kept from v3 (ack | window | sack_base | sack_bitmap32).

This pack includes:
- `cl5x_echo.py` — simple TCP echo demo (server/client).
- v1/v2/v3 simulation outputs + v4 (this README).

Run echo locally:
```bash
python cl5x_echo.py --mode server --port 5555
# in another terminal
python cl5x_echo.py --mode client --host 127.0.0.1 --port 5555 --count 20 --size 2048
```

Notes:
- The echo is intentionally minimal (no FEC/adaptive logic) to keep it easy to test wire framing end-to-end.
- Integrate v4 transport logic in your stack to enable full features (FEC/adaptive/SACK).
