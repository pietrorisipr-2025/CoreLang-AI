# CoreLang AI — stream batch compression patch report

## Environment
- Installed/verified: `zstandard` and `lz4`.
- Benchmark command: `python cl5x_bench_v62.py`.

## Files changed
- `cl6_link.py`
  - `send_batch()` now builds a raw inner S-frame stream and compresses the concatenated stream once.
  - Added `flush_batch()`.
  - Added `batch_window` / `batch_max` parameters for repeated `send_object()` batching.
  - Added stream-batch receiver path while preserving legacy single-frame SUMMARY/RESIDUAL decoding.
- `cl5x_entropy.py`
  - Added `entropy_pack_stream_auto()` and `entropy_unpack_stream()`.
  - Stream compressor bypasses the old `<300 bytes => raw` rule.
  - Uses zstd with a deterministic dictionary trained from local CKB/codebook files when available; falls back to zlib/lz4/raw by best size.
- `cl6_sframe_bitpack.py` and `cl5x_sframe_bitpack.py`
  - Extended `len_kind` so `zstd=4` is representable; old frames decode unchanged.
- `cl5x_bench_v62.py`
  - Updated to report the new stream-batch path while preserving the legacy total for comparison.

## Benchmark results

### Before
```csv
json_bytes,json_zlib_bytes,sframes_total_bytes,summary_bytes,residual_bytes,messages
183610,62206,129209,76603,52206,240
```

### After
```csv
json_bytes,json_zlib_bytes,sframes_total_bytes,legacy_sframes_total_bytes,summary_bytes,residual_bytes,stream_inner_bytes,stream_packed_bytes,stream_codec,stream_dict,messages
183610,62206,20400,129209,76603,52206,166580,19994,zstd,True,240
```

## Readout
- Legacy CL6 path: `129,209` bytes.
- New stream-batch CL6 path: `20,400` bytes.
- gzip/zlib baseline: `62,206` bytes.
- Improvement vs legacy CL6: about `6.33x` smaller.
- Improvement vs gzip/zlib baseline: about `3.05x` smaller.
- The stream codec selected by the benchmark was `zstd` with dictionary: `stream_codec=zstd`, `stream_dict=True`.

## Compatibility check
A local round-trip test was run:
- `send_batch()` published one stream-batch frame and decoded all test objects correctly.
- legacy `send_object()` still published old SUMMARY/RESIDUAL frames and decoded correctly.
- `send_object()` with `batch_max=5` flushed as one stream-batch and decoded correctly.
