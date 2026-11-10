# Independent application module image

This generic definition assembles one reviewed native runtime and the Schemaxis
wheel. Existing family-specific Dockerfiles remain usable. It adds packaging
routes for Blender and batch FreeCAD without claiming those images have been
built, qualified or published. No image combinations are required.

Use `containers/` as context. Provide `artifacts/runtime.tar` and
`artifacts/schemaxis.whl`, their exact SHA-256 build arguments, `RUNTIME_FAMILY`
(`blender`, `freecad`, or an existing assembler family) and `RUNTIME_VERSION`.
The archive follows [the existing build contract](../README.md): native binaries,
dependency libraries/resources, complete licences and source/build provenance.

Blender needs `/opt/runtime/bin/blender`. Batch FreeCAD needs a portable launcher
at `/opt/runtime/bin/freecadcmd`, with its matching modules and resource paths.
These can be wrappers around the reviewed distribution's actual layout. They
must work independently of workstation paths and interactive shell settings.
Full desktop GUI sessions are outside this worker definition.

Follow the existing dedicated-builder resource gate before building. Do not run
an unbounded Docker build. After assembly, run actual native acceptance inside
the exact image, including offscreen graphics or CAD library loading, file-input
capture, independent verification and cancellation/cleanup. Retain image identity
and redistribution materials. A pending Dockerfile label or a manifest field
never establishes qualification. Only then create a reviewed app-module manifest
and register it using `schemaxis modules register`.
