# ParaView runtime inputs

[runtime-inputs.json](runtime-inputs.json) pins the official ParaView 5.13.3
OSMesa/MPI/Python 3.10 binary archive and candidate Debian Trixie library packages.
These are source and dependency metadata; each assembled variant needs its own
contained native observations.
The distribution contains mixed component licences; its redistribution gate is
unresolved. ParaView's own BSD licence does not cover every bundled component.

Prepare the reviewed runtime bundle from the pinned archive's `bin`, `lib`,
`plugins` and `share` directories, preserving internal relative symlinks and
resources. Exclude any separately retained application source checkout. Add the
required candidate shared libraries under `runtime/lib` and all corresponding
package copyright/licence texts under `runtime/LICENCES`. Verify every archive
and package SHA-256 before extraction. Candidate packages do not establish the
complete transitive ELF closure; validate resolution inside the exact image.

For the OSMesa variant, retain the official `lib/mesa/libglapi.so.0` and add the
relative symlink `runtime/lib/libglapi.so.0 -> mesa/libglapi.so.0`. The bundled
executables search the top-level `lib` directory. A bounded offline loader
diagnostic of `pvbatch-real`, `pvpython-real` and Mesa `libOSMesa.so.8` identified
this missing SONAME and resolved their complete reported dependency closures
with the bundled Mesa provider. No binary patch or extra Mesa package is used.
Record this relocation in the runtime provenance and its per-file symlink list.

The initial native case is a synthetic sphere and a 64×64 headless rendering.
Use the bundled OSMesa runtime without a host display or device mount. This case
cannot establish MPI scaling, broad upstream coverage or redistribution rights.
Corresponding source and relink obligations, and any proposed smaller plugin
subset, require their own exact dependency and licence review.
