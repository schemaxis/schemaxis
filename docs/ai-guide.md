# Guide for agents

1. Read AGENTS.md, then use `schemaxis capabilities browse` or
   `schemaxis capabilities search 'purpose keywords'` to find operation IDs.
   `schemaxis capabilities describe operation/PROVIDER/OPERATION` returns the
   selected contract; `capabilities schema` retrieves bounded schema fragments.
   Direct IDs work without browsing first. See [capability discovery](capability-discovery.md).
   The installed declaration is authoritative; application GUI features do not
   automatically exist in Schemaxis.
   `schemaxis readiness --app PROVIDER` exposes route-specific assumptions,
   inspection/recovery guidance, delivery fixtures and unresolved admission gaps.
   Structural completeness does not establish native qualification; see
   [adaptor readiness](adaptor-readiness.md).
2. Start from a relevant checked example. Produce ordinary JSON with declared
   nodes, ports and options. Never insert Python scripts or arbitrary proxy paths.
3. Plan without native applications. Inspect dependencies, active nodes, defaults,
   state/publication budgets and unsupported requirements before executing.
4. Use explicit native runtime paths and fresh output directories. Preserve native
   faults and logs. A zero exit status or an existing image is insufficient evidence.
5. Verify the completed run. For new capabilities, add independent expectations:
   analytic volume, bounds, field values, tuple counts, or required rendered objects.
6. Report output paths, checks actually performed, runtime version and limitations.
   Distinguish authored input, observed native state and inferred conclusions.

Source boundaries: use Schemaxis code and public application APIs. Do not copy
proprietary third-party implementation material. Never commit private session
transcripts or working notes; they can contain superseded decisions, so do not turn
them into current feature or provenance claims.

For a persistent headless loop, use the [local agent service](agent-service.md):
`schemaxis agent --workspace DIRECTORY` exposes discovery, revision-bound planning,
execution jobs, cancellation, verification and bounded artifact observations over
JSON lines. Keep its subprocess open while native work runs. Scope each task to
the user's authorised providers and fixed attempt/time budgets.

Configure your local toolchain following [installation](installation.md).
Whisper and ComfyUI are independent local tools, not Schemaxis providers. Godot and
Aseprite have bounded native adaptors and scheduled handoffs. FFmpeg and QGIS
add bounded video and vector GIS workflows; see `docs/media-workflows.md` and
`docs/qgis.md`. FreeCAD now has a bounded literal
solid-CAD adaptor; see `docs/cad-and-mesh-workflows.md`. CAD document references resolve before native option validation. It does not support the ParaView/Blender
expression, time-visit or analytic-sweep language.
Do not describe an installation as a verified end-to-end Schemaxis integration.

For parallel human/agent work, use separate branches/worktrees and explicit acceptance
criteria. Avoid simultaneous heavy GPU workloads. Keep implementation changes and
review comments traceable to the intended product outcome.
