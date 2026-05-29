
# CL5X v6.4 — Multi-peer + MSD delta2 + RVQ + Policy

**Nuovo:**
- `cl5x_msd_delta2.py`: delta-of-delta con frame 'F' (full) e 'B' (batch).
- `cl5x_qvec_rvq.py`: Residual Vector Quantization multi-stage (stages x k centroids).
- `cl5x_hub.py`: hub multi-peer con dedup su ref_hash globale.
- `CL5X_policy.json`: TTL e soglie D2 centralizzate.

## Hub
```python
from cl5x_hub import CL5XHub
hub = CL5XHub()
hub.register('A', linkA.feed_wire)
hub.register('B', linkB.feed_wire)
hub.broadcast(frame_bytes, origin='A')
```
