# Corelang6 v6.8 — nuove funzioni
- **CAPA_NEG** applicata: disabilita automaticamente MSD2/MIC/QPROFILE se il peer non li supporta.
- **RSYN ring buffer**: resend dei SUMMARY+RESIDUAL recenti su `RSYN1/REQ`.
- **Pacing (token bucket)**: parametri `rate_limit_bps` e `burst_bytes`.
- **D3 persistente**: `ckb_D3_phrases.json` annunciato in handshake.
- **CAS/REF**: `cas_put`, `send_ref`, `cas_get` per allegati out-of-band.
- **Batch send**: `send_batch([obj1,obj2,...])`

```python
from cl6_link import CL6Link
link = CL6Link(tx, on_object=..., rate_limit_bps=250000, burst_bytes=65536, rsyn_buffer=128)
# batch
link.send_batch([{"id":"t1","result":{"ok":True}}, {"id":"t1","time_ms":123,"log":"next"}])
# CAS
h = link.cas_put(b"payload molto grande"); link.send_ref(h)
```