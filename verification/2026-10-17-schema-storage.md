# Shared schema storage verification — 2026-10-17

The existing exact-byte snapshot helper was generalised at the framework boundary,
with a workspace-owned canonical store, a separate provenance index, backward
compatible reads, verified portable export, explicit metadata repair, and
conservative cleanup protection. The optional ParaView category bundle remains
separate and unchanged.

## Host checks

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_schema_storage.py -v
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_schema_snapshots.py -q
PYTHONPATH=src python3 -m unittest discover -s tests/unit -p test_paraview_schema_bundle.py -q
```

Fifteen shared-storage tests and seven unchanged legacy snapshot tests passed.
The five unchanged ParaView bundle tests passed in 87.9 seconds.

The shared-storage suite covers all 22 registered document routes for the 20
existing applications, plus the workflow envelope, with a native-import blocker.
This is schema/framework verification, not native application qualification.

Subsequent programme integration enumerated all 23 routes for 21 applications
after adding Pandoc; every route captured and read its declared schema. Actual
native Godot and Pandoc acceptance produced nine and eight verified schema
references respectively, including their workflow/study records. Each application's
set contained its own schema identity and the workflow schema identity. Exporting
one completed run from each application and moving the export retained a local,
independently verified schema dependency. This checks schema portability; absolute
paths elsewhere in native receipts remain a separate limitation.
Registry enumeration will include newly installed routes in subsequent runs.

The new cases demonstrate:

- Calc and FFmpeg repeat captures share one object per distinct schema; key order
  and whitespace normalise, while changed constraints/annotations remain distinct.
- Content identity is independent of provenance; differing observations share the
  same content while both remain represented in the index.
- Nine concurrent captures across three processes retain one complete object and
  both distinct provenance records, without lost index updates.
- Interrupted index or manifest publication is retryable, lock contention has a
  bounded structured failure, and failed exports preserve the source and mark the
  partial destination incomplete. Interrupted index publication leaves a complete object and no dangling manifest;
  explicit repair restores metadata. Missing/corrupt indexes do not prevent reads,
  but prevent new captures until repair. Corrupt objects are never overwritten.
- Missing dependencies, manifest tampering, path escape, duplicate JSON keys,
  non-finite values, wrong document versions, symlinks, and external schema
  dependencies are rejected. Literal annotation data containing `$ref` survives.
- Whole-workspace relocation works. Removing one disposable run leaves the other
  readable. Exporting nested v1/v2 captures, then removing the disposable original
  and moving the export again, retains every required schema.
- Existing v1 captures remain exact-byte readable. Older run evidence without a
  snapshot and unversioned legacy input are accepted without fabricated contracts.
- Unrelated ancestor `authored.json` files do not choose the store; recognised
  workflow and common-study parents do.

All removal/move scenarios use disposable temporary fixtures. No retained user
outputs, installations or evidence were migrated, removed or rewritten.

## Measured repeated-capture savings

Ten fresh run captures used actual generated authored schemas. Totals include all
schema objects, the index, lock file and ten reference manifests. Independent-copy
baselines count ten copies of the same compact canonical bytes. These are logical
file sizes, not allocated filesystem blocks.

| Adaptor | One schema | Ten separate copies | Shared store and references | Bytes avoided | Reduction |
| --- | ---: | ---: | ---: | ---: | ---: |
| Calc | 38,614 | 386,140 | 45,495 | 340,645 | 88.22% |
| FFmpeg | 37,604 | 376,040 | 44,551 | 331,489 | 88.15% |
| ParaView | 4,077,402 | 40,774,020 | 4,084,470 | 36,689,550 | 89.98% |

Each object is stored once at its output root. No saving is claimed against
previous runs that never stored a schema. The new automatic capture adds one
retained contract plus small references where previously no such evidence existed.

| Adaptor | Generate and durably capture ten | Verify and read one |
| --- | ---: | ---: |
| Calc | 0.153 s | 0.010 s |
| FFmpeg | 0.144 s | 0.004 s |
| ParaView | 10.894 s | 0.410 s |

These are single warm-process samples on one host, including schema generation,
validation, canonical serialisation, hashing, filesystem publication and index
updates. They are not native execution timings, cold-start benchmarks or a promise
for other filesystems. Capture deliberately regenerates from current declarations
rather than using a stale content cache. Large-schema repeated generation is a
measurable cost for future optimisation.

## Compression measurement for the output-storage analysis

An exploratory standard-library gzip test used those same canonical bytes with
`mtime=0`. Compression is a proposal; shared-store files remain plain JSON.

| Adaptor | Canonical JSON | gzip bytes | Compress | Decompress |
| --- | ---: | ---: | ---: | ---: |
| Calc | 38,614 | 2,842 | 0.0006 s | 0.00008 s |
| FFmpeg | 37,604 | 2,772 | 0.0006 s | 0.00008 s |
| ParaView | 4,077,402 | 113,909 | 0.0360 s | 0.0038 s |

These timings exclude a compressed-storage protocol, extra format negotiation and
failure handling, editor interoperability, decompression limits, and durable writes.
Deduplication and compression address different costs; their percentages must not
be added. Future compressed objects would need explicit versioning while retaining
an uncompressed-content identity and verified offline readers.

## Qualification limits

The store uses POSIX advisory locks and local filesystem atomic publication;
network filesystems and non-POSIX hosts are not qualified. Hashes do not authenticate
provenance. Shared-store inspection never proves complete reference ownership and
never authorises garbage collection. Export verifies schema dependencies, not the
relocatability or scientific validity of all native artifacts. Native execution
integration and broader regression checks are recorded by the programme's
integration owner separately.

See [schema storage design and use](../docs/schema-storage.md) for contracts,
recovery steps, legacy behaviour and representative directory layout.
