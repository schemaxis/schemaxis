# Generated normalise fixtures

These self-authored, deterministic PCM16 WAV signals contain no recorded voices,
music, third-party audio or hidden acquisition dependency. Each has one 16-byte PCM
`fmt ` chunk and one `data` chunk, written with Python `wave`/`struct`. Values are
rounded half up. `s(f, i, R)` means `sin(2*pi*f*i/R)` for zero-based frame `i`.

| File | Frames | Channels | Rate Hz | Scalar sample construction |
| --- | ---: | ---: | ---: | --- |
| quiet-stereo16k.wav | 4000 | 2 | 16000 | left `3000*s(220)`, frame 100 set to 3000; right `1500*s(330)`, frame 2100 set to -1500 |
| loud-mono8k.wav | 1600 | 1 | 8000 | `30000*s(440)`, frame 37 set to 30000 and frame 801 to -30000 |
| negative-fullscale-mono8k.wav | 1200 | 1 | 8000 | `20000*s(300)`, frame 11 set to 20000 and frame 600 to -32768 |
| silent-mono8k.wav | 800 | 1 | 8000 | every sample zero |

The quiet stereo file has a measured peak of 3000 (left), so `targetPeak` 20000 needs
the exact gain 20/3 and a `maxGain` of at least 7 allows it; the right channel stays
half the left. The loud mono file has peak 30000: `targetPeak` 16384 attenuates by
1024/1875. The negative-full-scale file has peak 32768 only through one -32768 sample
(PCM16 has no +32768), so even `targetPeak` 32767 attenuates by 32767/32768. The
silent file is refused because it has no peak to scale.
