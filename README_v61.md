# CL5X v6.1 — Residual Delta, Entropy Packing, MSD, Adaptive D2, QoS Helpers

## Novità
- **Residual Delta (VCDIFF-like)**: delta contro `summary_bin` con op COPY/ADD (min_match=16), S-Frame RESIDUAL carica `ref_hash` sul summary.
- **Entropy packing (auto)**: `raw` vs **Huffman-lite** vs **zlib** → sceglie in automatico il migliore per i payload S-Frame.
- **MSD (Message Schema Dictionary)**: `cl5x_msd.SchemaRegistry`, `SCHEMA_TOOL_CALL`, `SCHEMA_TOOL_RESULT` → encoding O(1) per I/O strumenti.
- **Adaptive D2**: suggerisce frasi ricorrenti e crea micro-update CKB (layer D2).
- **QoS helpers**: wrapper `publish_semantic(tx, kind, data, chid)` con profili SUMMARY/RESIDUAL/PLAN/OBS/ACT/REFLECT.

## Uso rapido
```python
from cl5x_delta_vcdiff import delta_encode, delta_decode
from cl5x_entropy import entropy_pack_auto, entropy_unpack
from cl5x_msd import REG, SCHEMA_TOOL_CALL, SCHEMA_TOOL_RESULT
from cl5x_adaptive_d2 import suggest_phrases, make_ckb_update_frame
from cl5x_qos_profiles import publish_semantic

# Residual delta
residual_payload = delta_encode(summary_bin, full_bin)
full_rebuilt = delta_decode(summary_bin, residual_payload)

# Entropy
kind, packed = entropy_pack_auto(residual_payload)
raw = entropy_unpack(kind, packed)

# MSD
sid = SCHEMA_TOOL_CALL
b = REG.encode(sid, {'tool':'python','args':{'code':'print(1)'},'timeout':3,'id':'x'})
obj = REG.decode(b)

# Adaptive D2
phr = suggest_phrases(["...recent text..."])  # -> list
ckb_d2 = make_ckb_update_frame(phr)
```

## Integrazione con CL5X v5/v6
- SUMMARY (topic 101) prima, RESIDUAL (topic 102) dopo; nel RESIDUAL usa `delta_encode` con `ref_hash` del SUMMARY.
- Applica `entropy_pack_auto` sui payload più grandi e includi (kind) nel campo `dict_id` o nell'header interno, se vuoi.

## Note oneste
- L'Huffman-lite è **intenzionalmente semplice**: su payload testuali piccoli può perdere contro zlib; l'auto-scelta evita regressioni.
- Il delta è greedy con finestra 16: veloce e robusto; non è un VCDIFF completo, ma porta già un guadagno sensibile.