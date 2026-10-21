# Schemaxis development instructions

This file describes the current Schemaxis repository.

## Scope and sources

- Work in this repository. Do not modify neighbouring repositories.
- Develop from Schemaxis's current code, user requirements and public application APIs.
  Do not copy proprietary third-party implementation material into this repository.
- Preserve accurate provenance. Current development rules are not a retrospective
  claim about all historical references or sessions.
- Never commit private session transcripts, AI working notes, credentials,
  workstation paths or material that belongs to a third party.
- README.md describes shipped features; `docs/design` holds design direction and
  may describe work that is not yet implemented.

## Product contract

Humans and agents share declared input, discovery, planning, inspection, execution
and verification. Keep discovery and planning free of native application imports.
Native applications execute in their own processes; handles stay process-local,
while durable artifacts cross workflows with explicit verification and loss limits.
A successful process or existing file alone is not proof of a successful workflow.

## Layout

- `src/schemaxis`: application-independent declarative framework.
- `src/schemaxis/adaptors/<app>`: application policies, native code and `adaptor.json`.
  The registry discovers these manifests; do not add app-name branches to the
  framework or import another adaptor for shared utilities. See `docs/adaptors.md`.
- `src/schemaxis/core`: retained shared input, contracts, faults, runners and planning utilities.
- `src/schemaxis/adaptors/paraview/mvp`: retained ParaView MVP and native catalogue.
- `examples/schemaxis`: runnable workflows and independent acceptance checks.
- `tests/unit`, `tests/conformance`: host tests and native qualification.
- `verification`: compact evidence summaries; bulk local results go in `evidence`.

## Implementation

- Keep the host runtime dependency-free (Python 3.10+).
- Use structured faults with a stable code, location and useful recovery information.
- Validate values before native assignment; read back native settings where available.
- Preserve dependency ordering, analytic synchronization, invalidation and object reuse.
- Keep absent, invalid, unavailable and unsupported states distinct.
- Do not expose arbitrary Python execution or native reflection through authored input.
- New native options need meaningful tests and a bounded native acceptance example.
- Preserve existing uncommitted changes. Do not silently loosen verification to pass.
- Use Canadian spelling. Use “adaptor” consistently in prose, filenames, modules,
  identifiers and public keys. Preserve actual third-party API names and URLs.
  Follow existing Python/JSON naming conventions.

## Studio conceptual guidance

- Preserve user-facing operation and field explanations in each adaptor’s
  `guidance.json` as declarations/schema routes change. Follow
  `docs/studio-adaptor-contract.md`; native names and type constraints do not
  replace conceptual guidance. Seed and audit with `tools/studio_guidance.py`.
- Keep missing text pending, retain provenance for imported explanations, and
  request domain input where scientific meaning is uncertain.

## Commits and pull requests

- Pull requests are welcome. Keep each one focused on a single change, include
  tests, and run the host suite and `python3 tools/release_gate.py` before
  submitting.
- Summarise the changes in one first line; it may exceed 80 characters.
- Prefer that single summary line. Add further detail only when necessary;
  additional lines should be rare.
- Keep every subsequent line, including trailers, at most 80 characters.
- Do not add Co-Authored-By trailers. Keep the actual human author and any
  required DCO sign-off; tool assistance is described in the project documentation.

## Distribution boundary

- The core, Studio, geometry, meshing, post-processing and general-purpose
  application/database adaptors are distributed under Apache-2.0, subject to
  retained third-party notices.
- Ordinary local case files, execution receipts, workflow resume, scheduling
  and explicit storage preservation stay in the core.
- Integrated database-backed case catalogues, cross-case history and workflow
  intelligence belong in a separate private repository. Do not add that service
  to the core or make the core depend on it.
- CFD solver execution and CFD-specific boundary-condition/case preparation
  belong in separately maintained integrations, not the public core.
- See docs/distribution.md for the release boundary and extension contract.

## Verification and local configuration

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
PYTHONPATH=src python3 -m schemaxis discover
```

Configure native application locations during installation with `schemaxis configure`.
Keep each user's locations in the git-ignored `.schemaxis.local.json`, or select a
private configuration file with `SCHEMAXIS_CONFIG`. See `docs/installation.md`.
Never put workstation paths, installed-tool inventories or machine-specific
instructions in this file. Explicit executable/root arguments override local
configuration. Do not modify the user's application PATH settings.

Native serial verification is authorised. Do not claim MPI or exhaustive native
coverage from serial examples. Report newly run checks separately from old receipts.

## Upstream application updates

Target the latest stable upstream release of each application. Keep one implementation
per app; introduce separate runtime families only for unavoidable incompatible
platforms (for example Python 2 versus Python 3), with an explicit rationale.
Document versions are input contracts, not upstream application versions.
Run `schemaxis updates` to list unabsorbed releases and uncertain checks. Use
`schemaxis updates --prepare evidence/updates` to generate repair briefs for an AI
agent. Estimates are triage heuristics, not promises of compatibility. Keep the
absorbed version unchanged until host checks and bounded native acceptance pass;
retain evidence and scope in the adaptor's `upstream.json`. See `docs/updates.md`.
