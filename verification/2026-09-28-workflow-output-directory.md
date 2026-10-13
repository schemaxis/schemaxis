# Workflow output-directory usability fix

The [clean RLC AI comparison](2026-09-28-ai-workflow-clean-rlc.md) exposed two
avoidable failures: a missing output parent failed, and pre-creating the final
directory also failed. This fix was made after the measured comparison; its
timings and transcripts are unchanged.

Both sequential and scheduled workflow execution now create missing parents and
accept an existing empty destination. A file, final-path symlink, or directory
with any entries still produces `OUTPUT_EXISTS` without replacing its contents.
An unusable parent produces `INVALID_OUTPUT_PATH` with the affected path and OS
reason. The error for a populated directory suggests a new/empty destination or
supported unchanged-workflow resume.

The shared storage helper publishes `authored.json` exclusively before execution.
Concurrent fresh starts cannot both claim the destination. The input remains if
execution fails, preserving the distinction between an empty directory and an
incomplete run. Existing workflow coordinator locking and verified resume remain
in place. No force-overwrite option or automatic deletion was added.

This change is bounded to workflow output roots. Standalone adaptor, inspection,
scaffolding and legacy MVP destination contracts are unchanged; the user guide
states that distinction. No native adaptor implementation, application location
or user PATH changed.

## Verification

The 26 focused storage, sequential-workflow and scheduler tests passed. Six new
tests cover nested/empty destinations, protection of ordinary and hidden files,
file/symlink refusal, an invalid parent, concurrent fresh starts, and resume after
the new preparation path. Existing scheduling and failure tests also passed.

Two real CLI runs of `examples/schemaxis/ngspice-rlc-to-calc.json` completed using
ngspice 47 and LibreOffice 26.8.0.3:

| Destination condition | Native run and verify | Repeated fresh run | Unchanged resume |
| --- | --- | --- | --- |
| Missing nested parents | Passed: two jobs, six artifacts | Refused; all retained file hashes unchanged | Passed |
| Pre-created empty directory | Passed: two jobs, six artifacts | Refused; all retained file hashes unchanged | Passed |

These are post-fix execution checks, not new AI efficiency measurements. Bulk
evidence is in `evidence/output-directory-fix/`, including `summary.json`, run,
verification, collision and resume logs, and the complete native output bundles.
The full host regression transcript is
`evidence/2026-09-28-output-directory-tests.log`.

The full suite ran 803 tests: 780 passed, 22 were skipped, and one generated
reference check detected the new storage imports missing from `modules.json`.
The generated reference was refreshed; the complete schema/reference test module
and the 56-file reference check then passed when rerun separately. This is a targeted
repair verification, not a claim that the entire suite was run a second time.
