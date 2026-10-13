# Adaptor scaffolding and admission isolation

Milestone 2 adds `schemaxis adaptor scaffold` for node and non-node source overlays.
It generates a package, declarations/schema/planner, explicit native stubs, context
and development decisions, editable example, host tests, acceptance launcher and
checklist. It never installs an adaptor or overwrites an existing destination.
Native stubs fail ADAPTOR_NOT_IMPLEMENTED and admission remains incomplete.

New checks:

- Two scaffold tests pass, including isolated package installation of both models
  without changes to framework routing, public discovery/schema/query/context,
  four generated host checks and shared source/property draft editing and planning.
- A deliberately broken generated runner ignores its timeout and sleeps. The
  independent conformance supervisor terminates it, retains logs/metrics, and raises
  CONFORMANCE_WATCHDOG rather than crediting the adaptor's timeout behaviour.
- Thirteen kit tests pass, including exact receipt/fixture matching, malformed or
  inconsistent evidence, changed fixture freshness, artifact/evidence restoration,
  explicit unavailable qualification and bounded context.
- Three architecture/extension tests and all 47 generated-reference checks pass.
- The bounded Octave native runner passes both analytic cases, saved-evidence
  tampering, timeout and cancellation. Final CAD/non-node and public agent/human
  acceptance follow after code stabilisation.

Qualification digests now include shared assets, owning-adaptor resources and
referenced fixture bytes. Registered receipts are checked against the current
case documents, literal expectations, lifecycle faults and integrity coverage.
Their scope remains the named cases and observed runtimes, not exhaustive support
or an attestation against a dishonest installed package.

Bulk evidence is under `evidence/adaptor-kit/`, including a reviewable generated
`growthdemo` overlay. No candidate adaptor was installed by this milestone.
