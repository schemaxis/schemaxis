# SoX mix fixtures

Four tiny generated canonical PCM16 WAV files for the `mix` operation. Frame `i`
(per channel `c`, with `c` 0 for the first channel) holds:

| File | Rate | Channels | Frames | Sample value |
| --- | --- | --- | --- | --- |
| `narration-mono8k.wav` | 8000 | 1 | 800 | `(i*97) % 24001 - 12000` |
| `background-mono8k.wav` | 8000 | 1 | 1200 | `(i*53) % 12001 - 6000` |
| `narration-stereo16k.wav` | 16000 | 2 | 600 | `(i*89 + c*7001) % 24001 - 12000` |
| `background-stereo16k.wav` | 16000 | 2 | 900 | `(i*41 + c*3001) % 12001 - 6000` |

They are synthetic sawtooth signals, not speech or music; they exist so that every mixed
sample, offset, silence pad and rounding case can be recomputed. The narration peaks at
12000 and the background at 6000, so the example gains below never clip.
