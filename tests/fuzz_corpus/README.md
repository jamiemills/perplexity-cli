# Fuzz seed corpus

Synthetic seeds for the coverage-guided atheris fuzz harnesses in
`tests/_fuzz_harnesses.py`.  Every `.bin` file below is deterministically
replayed (sorted by filename) before mutation, and the directory is passed to
`atheris.Setup` as the libFuzzer seed corpus so mutations start from
realistic inputs.

Each seed is a single raw `bytes` blob consumed by every harness via
`atheris.FuzzedDataProvider`.  All harnesses treat arbitrary bytes safely, so
the corpus is shared across targets; the round-trip oracles generate their
own synthetic *valid* inputs at runtime.

## Seed inventory

| File | Bytes | Purpose |
| --- | ---: | --- |
| `json_object_01.bin` | 154 | Valid JSON object shaped like a thread-list page (`threads` array with `last_query_datetime`, `slug`, `title`, `has_next_page`, `total_threads`). |
| `json_array_02.bin` | 210 | Valid JSON array of `ThreadRecord`-shaped objects (`title`, `url`, `created_at`). |
| `sse_event_lines_03.bin` | 208 | SSE wire lines: `event: answer` and `data: {...}` pairs ending with blank-line event terminators. |
| `near_valid_json_04.bin` | 48 | Near-valid (truncated) JSON object, exercising the reject-path after a promising prefix. |
| `v2_ciphertext_shaped_05.bin` | 92 | Current-format v2 ciphertext-shaped string: valid base64url whose payload begins with the `v2:` version prefix and carries a per-message salt. |
| `legacy_token_shaped_06.bin` | 88 | Legacy-shaped Fernet token string (base64url starting with `gAAAAA`), used to exercise the legacy decrypt readers. |
| `model_payload_07.bin` | 298 | Valid `SSEMessage`/`Block` model payload with `ask_text` and `web_results` blocks. |
| `json_scalar_08.bin` | 4 | JSON scalar (`null`), exercising the non-object/non-array reject paths. |
| `invalid_utf8_09.bin` | 10 | Invalid UTF-8 bytes, exercising `SSEParser._decode_line`'s `UnicodeDecodeError` path and general byte robustness. |
| `empty_10.bin` | 0 | Empty input, exercising every harness's degenerate/empty-input path. |

## Replay contract

* Replay order is deterministic: lexicographic order of the `.bin` filenames.
* A seed that raises an unexpected exception or trips an oracle assertion
  fails the harness subprocess (and therefore the fuzz lane) authoritatively.
* The harness reports each replayed seed and the executed iteration count in
  a machine-readable JSON state file consumed by `tests/test_fuzz.py`.
