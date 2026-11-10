# Generated speech-conform fixtures

These self-authored, deterministic PCM16 WAV signals contain no recorded voices,
music, third-party audio or hidden acquisition dependency. Each has one 16-byte PCM
`fmt ` chunk and one `data` chunk, written with Python `wave`/`struct`. Values are
rounded half up. `s(f, i, R)` means `sin(2*pi*f*i/R)` for zero-based frame `i`.

| File | Frames | Channels | Rate Hz | Scalar sample construction |
| --- | ---: | ---: | ---: | --- |
| stereo44k.wav | 8820 | 2 | 44100 | left `9000*s(220)+3000*s(1130)`; right `7000*s(330)+2500*s(2100)` |
| stereo48k.wav | 9600 | 2 | 48000 | left `12000*s(440)`; right `6000*s(1250)` |
| stereo16k.wav | 4000 | 2 | 16000 | left `(i*733)%60001-30000`, right `(i*491)%50001-25000`; at `i%97==0` left 32767, right -32768; otherwise at `i%101==0` left -32768, right 32767 |
| mono8k.wav | 4000 | 1 | 8000 | `12000*s(440)+3000*s(1500)` |

Each stereo file is 0.2 s of unequal left and right content, so a wrong channel choice
changes every sample. 8820 frames at 44100 Hz and 9600 frames at 48000 Hz both give
3200 output frames; the 16000 Hz file needs no resampling and is verified sample for
sample; the 8 kHz mono file is upsampled to 8000 frames.
