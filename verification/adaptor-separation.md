# Adaptor separation verification — 2026-09-20

Fresh checks for the manifest-discovered adaptor refactor:

- Baseline host suite before edits: 532 tests, 11 skipped, no failures.
- Final host suite: 535 tests in 134.859 seconds, 11 skipped, no failures.
  Command: `PYTHONPATH=src python3 -m unittest discover -s tests/unit -q`.
- New architecture tests reject framework-to-app imports, cross-app imports,
  native imports in the framework, and app-name dispatch comparisons in shared
  code. Explicit compatibility aliases are excluded.
- A test-only adaptor folder was installed in an isolated source copy. Discovery,
  CLI description/plan/schema/run/verify, query, authored schemas, console,
  workflows and verified resume passed without framework edits. Removing every
  built-in adaptor from that copy still left the test app functional.
- `python3 -m fusion reference --check`: all 31 generated files match.
- A wheel was built with `pip wheel . --no-build-isolation --no-deps`; its five
  manifests, relocated ParaView catalogue/notice and runner were checked. Discovery
  from an isolated installation matched discovery from its generated runtime ZIP.
- Fresh serial ParaView and Blender checks each passed run, receipt verification
  and node inspection. ParaView used a sphere geometry publication; Blender used
  a prepare-only cube scene. Evidence was retained locally under
  a temporary smoke-test directory.
- Five targeted live tests passed in 15.576 seconds: the Blender persistent edit,
  geometry, image, failure and saved-scene-reopen test, plus `test_paraview_live`.
  These cover resident edits, output evidence, rollback, composite geometry and
  owned-process cleanup. Native applications were supplied explicitly through
  `FUSION_LIVE_BLENDER` and `FUSION_LIVE_PARAVIEW`; PATH was not modified.
- `git diff --check`: clean.

Native checks used the installed Blender 4.5.14 and ParaView 5.13.3 launchers.
This work does not add MPI qualification or new native qualification for FreeCAD,
Godot or Aseprite. Their existing host tests remain passing; capability restrictions
are retained in their adaptor manifests.
