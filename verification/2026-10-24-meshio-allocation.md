# meshio strengthening review — 24 October 2026

Scope: host and retained-boundary behaviour only. No new native mapping, format
or option; absorbed meshio 5.3.5 is unchanged and matched the latest GitHub
release and PyPI version when checked on 24 October 2026.

Defect: the standard-library reference readers that decide whether a source is
supported ASCII VTU/VTK, and that independently re-read the output during
verification, used Python `int()`, `float()` and `str.split()`. These accept
digit-group underscores (`NumberOfPoints="0_5"`, `1_0`, `0.0_1`) and, in legacy
VTK, VT/FF/FS/GS/RS/US/NEL as separators or line breaks. A source containing
such bytes passed planning and was handed to native meshio, which does not give
them that meaning, so the oracle and the native reader could disagree, and a
refusal would surface only as a generic native failure.

Repair: the readers now tokenise on space, tab, CR and LF only and accept plain
decimal integers and decimals. Anything else is refused before native launch as
`INVALID_MESH_CONTENT` at `$.source`, with no native run or mesh artifact and a
failed `result.json`. Genuine retained output uses plain decimal text, so
offline verification of such receipts is unaffected. XML attribute padding is
still tolerated as formatting.

Evidence (host): before the repair, seventeen subtests in the new
`tests/unit/test_meshio_allocation.py` failed, including a stub interpreter that
was launched for a malformed source. After it, the new file and
`tests/unit/test_meshio.py` pass (eleven tests). The literal VTU/VTK fixtures
and writer-style numbers (`1e-05`, `.5`, `5.`, `+3`, `1.25E+2`) still parse.

Limits: no meshio runtime was available, so no native run was made and this
change carries no new native qualification; the 17 October native receipt
predates this change and the source digest changed. Run `tools/qualify_meshio.py`
with an isolated meshio 5.3.5 interpreter before registering a fresh receipt.
The tolerance, orientation, size and format limits are unchanged. Parent-directory
symlinks in `source` are not refused; only the final path component is.
