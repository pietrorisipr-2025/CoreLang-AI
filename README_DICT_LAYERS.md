# CL5X v6 — Dizionari a livelli (D0 + D1/Corelang5 per blocco)

Questo pacchetto contiene:
- **D0** (control tokens): 14 simboli fissi a bassa latenza.
- **D1** (Corelang5) per **8** blocchi, potati a **250** frasi ciascuno.
- **dict_mask**: mappa blocco→bit (0..15) per attivare solo i blocchi necessari per topic/CHID.

## Come inviare i CKB
```python
# D0 prima (sempre)
tx.publish(topic=100, data=open("ckb_D0_control.bin","rb").read(), priority=3, ttl_ms=1000, chid=1)

# Attiva solo i blocchi necessari: es. Algorithms + DataStructures
mask_bits = {'CoreLang5_Block10_Domain_Adapters (4)': 0, 'CoreLang5_Block11_Crypto_Interop (2)': 1, 'CoreLang5_Block1_Logic_and_ControlFlow (7)': 2, 'CoreLang5_Block5_IO_And_Serialization (8)': 3, 'CoreLang5_Block6_Concurrency_And_Async (5)': 4, 'CoreLang5_Block7_Interop_And_FFI (4)': 5, 'CoreLang5_Block8_Systems_And_Networking (6)': 6, 'CoreLang5_Block9_Optimization_And_Profiling (6)': 7}
need = ["CoreLang5_Block10_Domain_Adapters (4)","CoreLang5_Block11_Crypto_Interop (2)"]
for blk in need:
    path = f"ckb_D1_{blk}.bin"
    tx.publish(topic=100, data=open(path,"rb").read(), priority=3, ttl_ms=1500, chid=1)
```

## Note
- Puoi cacheare per versione (`version_hint`) per evitare re-invii.
- Puoi comprimere i payload CKB se il link è debole (FLAG_COMPRESS lato frame CL5X, o pre-compressione).
