# CL5X — AI-to-AI Efficient Communication (v1)

**Goals:** low-latency, low-bytes, deterministic parsing, optional compression, simple reliability, easy multiplexing (channels), and group communication.

## Wire Format (big picture)

```
MAGIC(4='CL5X') | VER(1) | TYPE(1) | FLAGS(1)
[CHID(varint)]? | DICT_ID(varint) | [SEQ(varint)]? | LEN(varint) | PAYLOAD(bytes) | CRC32(4, big-endian)
```

- `TYPE`: 0=CONTROL, 1=DATA, 2=ACK, 3=ERROR
- `FLAGS` (u8): COMP(0x01), CH_PRESENT(0x02), SEQ_PRESENT(0x04), MORE(0x08), REF(0x10), PRIO1(0x20), PRIO2(0x40)
- CRC is IEEE CRC32 of all bytes before the CRC field.
- When `FLAG_COMPRESS` is set, `PAYLOAD` is **zlib-compressed**.
- When `FLAG_MORE` is set, more fragments follow and `SEQ` **must** be present.
- PRIORITY uses `PRIO1/PRIO2` (2 bits → 4 levels: 0..3).

## Negotiation (CONTROL/NEGOTIATE)

First exchange (both ways) with JSON payload:
```json
{"type":"NEGOTIATE","dict_id":<id>,"ver":1,"max_frame":65535,"compress":true}
```

Agree on: dictionary id, maximum frame size, and whether compression is enabled.

## Reliability & Flow

- `SEQ` numbers increase by 1 per frame **per channel** (if present).
- Fragmentation: sender splits large payload into fragments, sets `FLAG_MORE` on all but the last fragment.
- `ACK` frames carry `ack_seq` and `window` as varints inside `PAYLOAD` (minimal TLV or plain varints OK).

## Group / Multi-AI

- Use `CHID` to multiplex logical conversations (group, topic, or actor).
- A simple convention: CHID=0 for control, CHID>=1 for data topics/groups.
- Optional CONTROL messages: JOIN/LEAVE <group>, but not strictly required.

## Dedup / References

- With `FLAG_REF`, the `PAYLOAD` holds a content hash (e.g., BLAKE2s-256 in future). The receiver substitutes from its cache.

## Error handling

- `ERROR` frames carry a small UTF-8 message. Parsers should attempt re-sync by scanning for `MAGIC`.

## Extensibility

- Unknown flags are ignored if not required by receiver. Future `TYPE` values reserved 4..31.
- Dictionary updates can be sent via CONTROL (out of scope for this minimal reference).

---

## Python Reference (cl5x.py)

The included `cl5x.py` file implements:
- varint encode/decode
- frame encode/decode (with compression, channels, seq, priority)
- streaming decoder (incremental, resync on bad data)
- simple fragment reassembler
- a helper to build a NEGOTIATE payload

