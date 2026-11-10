# Apache Arrow subsecond timestamp grammar — 25 October 2026

Scope: `schemaxis.apachearrow/1`, `prepareTable`, the `timestamp_us_utc` scalar
grammar used for CSV cells, filter literals and `fillNull`. This note covers only
that change; it does not re-review the rest of the route.

## Defect

The grammar and guide accept `YYYY-MM-DDTHH:MM:SS[.f…]Z` or `+00:00` with one to six
fractional digits. The host reference then called `datetime.fromisoformat`. The
[Python 3.10 documentation](https://docs.python.org/3.10/library/datetime.html#datetime.datetime.fromisoformat)
limits that parser to `.fff` or `.ffffff`; later versions accept more ISO 8601
forms. On Python 3.10 a value such as `…00:00:00.5Z` would therefore be refused
(`INVALID_ARROW_DATA` or `INVALID_ARROW_LITERAL`) although the same text is
accepted on newer hosts, so a retained run could verify on one host and fail
planning on another. The package supports Python 3.10+.

Reproduced with a host emulation of the documented 3.10 grammar patched into the
reference module (not a Python 3.10 run): 9 of 14 width/offset cases and a
`where` literal with a one-digit fraction were refused.

## Change

`reference.scalar` now reads the date, time and fraction from the existing strict
pattern, right-pads the fraction to six digits and constructs the instant from
integers. `fromisoformat` is not used. Accepted text, UTC-only offsets
(`Z`/`+00:00`), year 0001–9999 range, calendar validation, rejection of hour 24,
leap seconds, naive/other-offset/extra-digit values and the epoch-microsecond
results are unchanged. No native mapping, worker or schema change.

## Checks

| Check | Result |
|---|---|
| Host emulation of the 3.10 grammar, before | 9 of 14 cases and the plan literal refused |
| Same emulation, after | 14 of 14 accepted with the expected microseconds; plan literal accepted; `fromisoformat` calls: 0 |
| `tests/unit/test_apachearrow.py` | 12 tests pass. The two new tests fail against the previous `reference.py` and pass now |
| Grammar test | Every fraction width 0–6 with `Z` and `+00:00`; the datetime constructor receives canonical six-digit microseconds; `fromisoformat` is forbidden; 29 malformed/range/offset values refused |
| Planning/evidence test | Literal and `fillNull` widths, located faults, row/column data fault, padded report values, stale implementation fingerprint refused |
| Native (PyArrow and Arrow C++ 26.0.0, serial, isolated environment) | `subsecond` in `tools/qualify_apachearrow.py`: 11 rows covering widths 0–6, both spellings, pre-epoch and year 0001/9999 values. Native CSV conversion and fresh Parquet readback equal the literal microsecond values; an equality filter with a five-digit fraction selects exactly the expected row; both runs verify |

No Python 3.10 interpreter was available, so nothing here was run on Python 3.10.
The test shows that the parser is never asked for 3.10-unsupported input; it does
not execute that interpreter.

## Compatibility and limits

`implementation()` fingerprints `reference.py`, so retained Arrow run directories
created before this change fail `verify` with “Arrow implementation changed;
requalify retained output with current code”. This is the existing policy and was
not relaxed; rerun the preparation to obtain verifiable output. Values that
already parsed are unchanged.

The registered native qualification receipt is bound to the earlier source digest.
The bounded run above is new, serial and covers only the cases named; it is not the
registered receipt, and the full `tools/qualify_apachearrow.py` acceptance (which
now includes `subsecond`) has to be rerun with a qualified SQLite CLI before
registering. No MPI or exhaustive coverage is claimed. The absorbed upstream
version (26.0.0) is unchanged.
