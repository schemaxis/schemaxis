# FFV1 whole-frame encoding correction

The real 400×200 diagram handoff exposed a gap in the first native cases:
FFmpeg n9.0.2 accepts forced FFV1 version-3 `slices=1` for tiny inputs but rejects
that layout for this ordinary image size. The failure is retained under
`evidence/adaptor-growth-20261010/diagram-video-1/` and was not counted as success.

New FFV1 encoding explicitly selects version 1 with `bgr0` and no forced slice
option. This preserves one whole-frame encoding path across the bounded dimensions.
FFV1 version 1 lacks version-3 slice CRCs; correctness still requires full native
RGB readback, independent expected pixels and publication/evidence SHA-256 checks.
The [upstream encoder source](https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/ffv1enc.c)
defines the explicit version selection, newer slice-layout restrictions and CRC
version requirement. No version-3 slice-CRC support is claimed for new outputs.
Offline verification continues to accept the exact historical version-3/slices-1
command for retained runs that passed full decoding, while modified slice commands
are rejected.

The actual adaptor and an independently constructed nonuniform RGB fixture passed
all nine dimensions on both `ffmpeg version 6.1.1-3ubuntu5` and Shotcut's
`ffmpeg version n9.0.2-12-gc867e13549`: 2×2, 32×24, 400×200, 1×1, 1×64, 64×1,
3×17, 17×3 and 640×360. Every row, edge and channel was compared byte-for-byte;
offline verification also passed after each original PNG was removed. The original
H.264/FFV1 media requirements, eight-frame sheet, tamper and explained unmet tests
passed again. Targeted host tests: 26 pass, one optional native test skipped without
an explicit runtime. Native kit conformance passes three cases and its timeout,
pre-launch cancellation and corruption probes on both observed runtimes.

Fresh local receipts are
`evidence/adaptor-growth-20261010/ffmpeg-whole-frame-{6.1,shotcut}/qualification.json`
and `ffmpeg-whole-frame-native-{6.1,shotcut}/qualification.json`; the latter retain
source digest `sha256:e4b447b0683d03d9849642e792989fa4b33cc746f1da0602ff3cc6792f222402`.
The extended [acceptance recipe](../tools/qualify_ffmpeg_deliverable.py) reproduces
the shape cases. This remains bounded serial qualification, not exhaustive
dimensions, all FFV1 implementations or a new absorbed upstream-version claim.
