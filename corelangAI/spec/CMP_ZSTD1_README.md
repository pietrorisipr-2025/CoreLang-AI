# CMP_ZSTD1 — integrazione Zstandard per corelangAI

**Modalità:** block/stream • **Dizionari:** supportati (training e annuncio `ZSTD_DICT1`) • **Parametri:** livello (1–22), threads (0=auto)

## Annuncio capacità (CAPA)
- `CMP_ZSTD1` nel registro codec
- `ZSTD_DICT1{version,name,size}+blob` per distribuire dizionari addestrati

## Wire (riassunto)
- Se presente dict attivo: include `dict_ref` o `dict_hash` nel header S-Frame
- Negotiation: `CAPA.neg` blocca livello massimo e threads
- Dict precompute lato TX/RX

## Note performance
- Preferire **zstd** rispetto a **zlib** per corpora grandi
- Abilitare dizionari per log ripetitivi e payload strutturati
- Usare threads>0 su macchine multicore
