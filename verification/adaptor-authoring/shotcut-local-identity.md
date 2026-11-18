# Shotcut owner-local identity preview

The `schemaxis.shotcut/1` route declares `assets[].name` as an identity and
`clips[].asset` as an ordered consumer within a timeline. The pure preview
checks the input digest and returns a full candidate with explicit owner and
collection addresses. The producer publication ID belongs to a separate
identity domain.

The host tests in `tests/unit/test_shotcut_local_identity.py` cover repeated
clips, the lowered project XML structure, policy admission, name boundaries,
workflow borrows and graph proof refusal. The inventory tests exercise the
asset target and clip consumer independently. Native Shotcut reopening,
rendering, bundle verification and Studio Apply remain outside this evidence.
