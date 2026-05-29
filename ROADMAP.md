# CL5X — Roadmap & Stato Avanzamento (v4 → v6.1)

## Completato finora
- **v4 (transport)**: SACK negli ACK, FEC(1,K) adattivo, segmentazione 512B, dedup hash, ritrasmissione selettiva, AIMD.
- **TCP Echo (asyncio)**: client/server su transport v4 reale.
- **QUIC Echo (v4)**: incapsulamento frame CL5X su aioquic (single-stream).
- **v5 (transport)**: deadlines (TTL ms) + backpressure per CHID (token bucket), pub/sub (topic + subscribe), multistream-friendly I/O.
- **QUIC multistream (v5)**: 1 CHID = 1 stream → parallelismo reale e priorità.
- **v6 (semantic layer)**: S-Frames (encoder/decoder + codebook), dual-rail (summary/residual), CKB (codebook announce), QVEC int8.
- **Dizionari Corelang5 (D1)**: estrazione dai Block*.zip, pruning per blocco, CKB per blocco + D0 control tokens.

## Scelte architetturali chiave
- **Topic/QoS**: 100=CKB, 101=SUMMARY, 102=RESIDUAL (lossless tail). Pri/TTL differenziati.
- **dict_mask**: attivo solo i blocchi D1 necessari per topic/CHID.
- **Cache CKB per versione**: niente re-invio se `version_hint` combacia.

## Prossimo step proposto (v6.1)
1) **Residual Delta (VCDIFF-like)** contro `summary_bin`:
   - COPY/ADD varint; ancori su hash delle finestre del summary; mira a battere JSON+zlib anche sul lossless totale.
2) **Packing Entropico** per S-Frames:
   - Huffman/ANS su tag/varint/ID; bitpacking header; RLE per piccoli varint ripetuti.
3) **MSD (Message Schema Dictionary)**:
   - schema_id per I/O dei tool (JSON ricorrente) + delta campo → parsing O(1) e payload minimi.
4) **Phrasebook adattivo (D2)**:
   - micro-update CKB con soglia di guadagno; eviction LRU con pin per top frasi.
5) **QoS semantico avanzato**:
   - classi PLAN/OBS/ACT/REFLECT con FEC/TTL dedicati; drop selettivo safe su OBS/LOG.

## KPI/Metriche da tracciare
- Byte totali vs JSON/zlib
- Latency p50/p95 fino al first-summary
- Hit-rate dizionario (D1/D2) e costo update
- Retrans/FEC overhead vs loss

## Integrazione (come usare)
- Invia `ckb_D0_control.bin` (topic 100) poi i blocchi D1 necessari (vedi manifest).
- Pubblica SUMMARY (topic 101) con TTL corto/priorità alta; RESIDUAL (topic 102) con TTL più lungo.
- QUIC multistream: mappa CHID→stream per evitare head-of-line a livello app.

## Aggiornamento v6.1
- Aggiunto residual delta (COPY/ADD), entropy packing auto, MSD, D2 adattivo, QoS helpers.
