# Console audit, 2026-09-20

The initial console was an authored-document wrapper around batch execution.
Its descriptions overstated persistence and visual preview. The existing native
adaptors predate that wrapper and are being retained.

## Findings requiring replacement

1. Edits and undo retained an older native preview. Saving could silently export
   a different model from the active authored document.
2. FreeCAD open discarded definitions, dimensions, settings and tessellation
   tolerance when reconstructing the authored input.
3. Blender save expected `scene.blend`, although the adaptor publishes numbered
   files and may produce several states.
4. Unload cleared a display flag while leaving execution enabled.
5. Authoring accepted nonfinite dimensions, invalid names and inappropriate
   extrusion inputs. Profile preview bypassed graph validation.
6. Native saves copied files without checking receipt hashes or output format.
7. Default checkpoint names collided after a failed run or session restart.
8. Two separate session implementations had diverging behaviours; neither
   represented several documents, persistent native connections or visual picks.

## Replacement acceptance criteria

- Keep complete authored inputs, active document, selection and reversible edits.
- Persist recoverable session state and prevent concurrent workspace writers.
- Bind checkpoints and selections to document revision and artifact evidence.
- Validate edits before changing authored state; report native failures separately.
- Allocate independent attempt identities and retain failed attempts for diagnosis.
- Distinguish configured installations, running native workers and durable artifacts.
- Reuse the same session interface from the terminal and visual companion.
- Show real native geometry; preserve native topology labels with pick coordinates.
- Compose prose with atomic reference tokens; reject stale references on submission.
- Keep arbitrary prose visibly recorded until a bounded operation can execute it.

Qualification results belong in `verification/` after the integrated implementation
has been exercised. The earlier passing unit count did not establish these behaviours.

## Independent review and resolution

A second read-only review of the replacement found seven further edge cases.
The implementation now addresses each:

1. Request submission includes the displayed document and revision, including
   prose-only requests. Model references revalidate native geometry before save.
2. State commits reconcile memory with the published file if parent-directory
   synchronisation fails after replacement, preventing revision reuse.
3. Reference/message persistence publishes a candidate before changing memory;
   reference writes use the same synchronised atomic publisher.
4. FreeCAD live saves validate the FCStd ZIP/XML container and disclose
   `nativeLiveSnapshot`/`independentReopen: false`. This is not misrepresented as
   an independently reopened batch artifact. Separate native qualification
   exercises actual fresh-process reopening.
5. FreeCAD screenshots capture the owned document view, not whichever GUI tab
   happens to be active. Native acceptance checks both views are different and
   the reported image belongs to the owned model.
6. Native-client replacement has exception-safe ownership transfer. Each
   document retains its own client; unloading one does not unload the others.
7. Saved requests are visible/restorable in the UI; drafts persist locally by
   document UUID, and saved indicators include document/revision identity.

Additional integration testing exposed image hashes changing solely because
periodic polling re-rendered the same scene. Image bytes are now retained for
the document/revision/checkpoint, so a pixel reference remains usable while a
sentence is being written. New checkpoints can legitimately replace the image.
Process lifecycle checks also cover cancellation and owner-exit cleanup.

See [the integrated verification summary](../verification/2026-09-20-console.json)
and [live-worker qualification scope](../verification/2026-09-20-live-workers.json).
