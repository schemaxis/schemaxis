# Generated PCM fixtures

These self-authored, deterministic PCM16 WAV signals contain no recorded voices,
music, third-party audio or hidden acquisition dependency. All use canonical
16-byte PCM `fmt ` and `data` chunks written with Python `wave`/`struct`.

| File | Frames | Channels | Rate Hz | Scalar sample construction (zero-based frame i) |
| --- | ---: | ---: | ---: | --- |
| endpoint.wav | 8 | 1 | 8000 | alternating 12000, -12000 |
| ramp.wav | 4096 | 1 | 16000 | `(i*977)%24001 - 12000` |
| stereo.wav | 8192 | 2 | 48000 | left `(i*733)%20001 - 10000`; right zero except i divisible by 113, then 9000 for odd i or -9000 for even i |
| variant.wav | 8192 | 2 | 48000 | left `(i*379)%16001 - 8000`; right `(i*101)%12001 - 6000` |
| extrema.wav | 8192 | 2 | 11025 | at i divisible by 16, left 32767/right -32768; otherwise left `(i*977)%48001 - 24000`, right 31000 for i divisible by 113, else zero |

The native verifier reads the original scalar samples and independently computes
half-open frame selection, linear amplitude gain and each fade envelope. It does
not ask SoX to generate expected audio. Qualification also checks literal endpoint
samples and the touching stereo fade frame 2000 `[32767,-32768]`.
