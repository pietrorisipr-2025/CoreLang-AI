# CL5X Advanced Transport + Simulator

Files:
- `cl5x.py` — minimal reference encoder/decoder.
- `README_CL5X.md` — protocol one-pager.
- `cl5x_transportsim.py` — advanced transport (scheduler, dedup, compression heuristic, retransmit) + network simulator.
- `sim/metrics.csv` — latest run metrics.
- `sim/*.png` — charts.

Usage (local):
```bash
python - <<'PY'
from cl5x_transportsim import LinkParams, run_scenario
# Build a minimal message set
msgs=[(1,b'hello'*200,2) for _ in range(10)]
print(run_scenario('demo', enhanced=True, link=LinkParams(rtt_ms=80, loss_pct=1.0, jitter_ms=5), messages=msgs))
PY
```
