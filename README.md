# CoreLang-AI

**A semantic transport protocol for AI-to-AI messaging.** Designed for the case where many small, structured, repetitive messages are exchanged between agents — not for archiving large files.

- **Stream-batch compression**: many messages are encoded into one inner stream and compressed together, instead of one frame at a time.
- **Semantic S-frames**: a compact binary encoding of structured messages (keys, common phrases, and values share a codebook).
- **Optional trained dictionary**: a zstd dictionary trained on a domain corpus, applied at the stream level.
- **QoS topics & resync**: differentiated channels (summary / residual), backpressure, and a resync ring buffer for lossy links.
- **Lossless**: every benchmark below is verified to round-trip byte-for-byte.

> Practical goal: **move a stream of small agent messages in as few bytes as possible**, losslessly, on links where bandwidth actually costs something.

---

## Where this fits in the CoreLang family

This is a sibling of, not a replacement for, the other CoreLang projects:

- **[CoreLang5](https://github.com/pietrorisipr-2025/CoreLang-5)** — block-scoped deterministic tokens; semantic/ABI layer, dual text/binary encoding, verifiable.
- **[CoreLang6](https://github.com/pietrorisipr-2025/CoreLang6)** — packaging and distribution of large binary artifacts (chunking, partial extraction, delta-sync).
- **CoreLang-AI** (this repo) — real-time AI-to-AI message transport. Grew out of the AI-to-AI exchange idea that CoreLang5 originally started from.

They solve different problems and are designed to coexist.

---

## The problem it solves

When multiple AI agents exchange messages, the traffic is **many small, highly repetitive payloads** (the same keys, the same tokens, the same structures, over and over). Compressing those payloads one message at a time wastes most of the available redundancy, because each tiny message restarts compression from scratch.

CoreLang-AI batches messages into a single stream and compresses the stream once, so redundancy *across* messages is captured.

**Before:** each message compressed alone → little gain on small payloads
**With CoreLang-AI:** messages batched into one stream → redundancy across messages is exploited

---

## Benchmark (verified)

Test data: **1,000 real structured messages** (Italian technical text — prompts, solutions, tags — drawn from the [CoreLang5 benchmark dataset](https://huggingface.co/datasets/pietrorisipr-2025/corelang5-benchmark)). Every result below was round-trip verified: decompressed output is identical to the input.

| Method | Size | vs CoreLang-AI |
|---|---:|---:|
| JSON, raw | 628,151 B | — |
| gzip, per-message | 423,413 B | 5.1× larger |
| gzip, whole stream (strict baseline) | 155,787 B | ~1.9–2.1× larger |
| **CoreLang-AI, stream-batch (no dict)** | **83,818 B** | reference |
| **CoreLang-AI, stream-batch + trained dictionary** | **74,405 B** | **best** |

**Readout:**

- Against a naive per-message gzip (the common real-world case), CoreLang-AI is about **5× smaller**.
- Against gzip applied to the *entire* concatenated stream (a deliberately strict baseline), CoreLang-AI is about **2× smaller**.
- The trained dictionary adds a further **~11%** on top, at maximum zstd level.

### On the dictionary, honestly

The bulk of the gain comes from **stream-batch compression**, not from the dictionary. The dictionary is a refinement worth ~11%, and only at high zstd levels (it helps less at fast levels). A small/generic dictionary can actually *hurt*; the one shipped here (`ckb_zstd_dict.bin`, 384 KB, `dict_id=704057133`) was trained on a 117k-case corpus and selected as a size/benefit optimum (larger dictionaries gain only ~2% more for several times the size).

The dictionary helps **specifically because messages are small**. It is *not* expected to help CoreLang6-style large-file packaging, where each chunk is already large enough for the compressor to find its own redundancy — this was measured and confirmed.

---

## What CoreLang-AI is **not**

- **Not a general-purpose compressor.** For compressing a single large file once, plain `zstd` is the right tool.
- **Not a large-artifact packager.** That is what CoreLang6 is for.
- **Not a token-count optimizer.** It reduces *bytes on the wire*, which matters on constrained/metered/mobile links. It does not reduce the number of tokens a model must process — inside a fast datacenter network, the byte savings matter much less.
- **Not production infrastructure (yet).** It is a working research prototype, built with AI coding assistance, maintained by one person. Treat it accordingly.

---

## Status & known limitations

- Round-trip correctness is verified on the benchmark above; broader fuzzing is not yet done.
- The integrity tag is for **integrity, not authentication** (not a robust MAC for adversarial settings).
- FEC is XOR-parity (recovers one loss per group), not Reed-Solomon.
- The dictionary's benefit is corpus-dependent; on data unlike the training corpus it may be neutral or slightly negative.

---

## Repository layout

```
cl6_link.py              # transport: send_object / send_batch / flush_batch, QoS topics
cl5x_entropy.py          # stream-level entropy packing (zstd + trained dict, fallbacks)
cl6_sframe_bitpack.py    # semantic S-frame bit-packing
cl6_capa.py              # capability negotiation
cl6_resync.py            # resync ring buffer
cl5x_bench_v62.py        # benchmark harness
ckb_zstd_dict.bin        # trained zstd dictionary (384 KB)
ckb_zstd_dict.manifest.json
tools/, overlay/, dict/  # capability auto-negotiation, token overlay, dictionaries
```

---

## License

[MIT](LICENSE) © 2026 pietrorisipr-2025

---

*Built with AI coding assistance. Benchmarks independently re-run and round-trip verified.*
