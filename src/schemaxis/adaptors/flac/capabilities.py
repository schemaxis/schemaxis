"""Curated intent-level lossless FLAC archive and PCM16 decode discovery without native imports."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'FLAC', 'purpose': 'Archive one PCM16 WAV recording as native lossless FLAC, optionally labelled with a title, artist and description, or decode one native FLAC into the canonical PCM16 WAV that speech preparation accepts, with every PCM byte proven by a fresh native decode.',
                            'keywords': ['FLAC', 'lossless audio', 'Free Lossless Audio Codec', 'libFLAC', 'flac', 'PCM16 WAV', 'audio archive', 'FLAC tags', 'Vorbis comment', 'recording labels']},
            'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
            'requirements': ['encodeLossless: an absolute captured local PCM16 mono or stereo WAV, 8000-192000 Hz, at most 600 seconds and a 32 MiB file. decodePCM16: an absolute local native FLAC (starting with fLaC) of the same audio class with a known sample count and a nonzero STREAMINFO MD5.',
                             'A configured FLAC 1.5 flac executable (--flac, schemaxis configure flac or SCHEMAXIS_FLAC); verification needs the same trusted flac because no host FLAC decoder exists.',
                             'Optional encodeLossless metadata: a closed object of title, artist and description (nonempty visible plain UTF-8, at most 200, 200 and 1000 code points), stored as native Vorbis comments and read back from the published file; they are author-declared labels, not identity or rights provenance, and decodePCM16 drops them.',
                             'No Ogg FLAC, 24-bit, float, lossy, multichannel, streaming or network input; no authored encoder flags, tag names, pictures or tags read from files.'],
            'references': ['docs/flac.md', 'src/schemaxis/adaptors/flac/readiness.json'],
            'operations': {
                'encodeLossless': {
                    'purpose': 'Archive a bounded PCM16 WAV recording as a lossless FLAC file and prove that a fresh native decode returns exactly the original PCM samples.',
                    'keywords': ['lossless audio archive', 'FLAC', 'lossless', 'archive recording', 'compress WAV losslessly', 'WAV to FLAC', 'lossless audio', 'encode FLAC', 'flac', 'libFLAC', 'PCM16', 'recording archive', 'FLAC tags', 'tag FLAC archive', 'Vorbis comment', 'recording title artist description', 'label audio archive', 'label audio archive title artist'],
                    'semantics': ['The host parses the WAV itself and hands native flac only raw signed 16-bit PCM; the encoder is fixed (-8, verified, no padding, no seek table) and no flag is authored. Optional metadata title, artist and description become fixed-name Vorbis comments (TITLE, ARTIST, DESCRIPTION), one argument per value, stored exactly as authored and parsed back from the published file.',
                                  'Every PCM byte of a fresh native decode equals the captured WAV samples, and the STREAMINFO sample count and MD5 match; LIST and JUNK chunks are dropped and listed. Labels are declared text, not an identity, rights or provenance certificate. Verification needs the trusted flac: there is no host FLAC decoder.'],
                    'examples': [{'reference': 'examples/schemaxis/flac-baseline.json', 'purpose': 'Archive a 48 kHz stereo recording with asymmetric full-scale extrema across two FLAC blocks.'},
                                 {'reference': 'examples/schemaxis/flac-variant.json', 'purpose': 'Archive an 8 kHz mono recording whose WAV carries a LIST chunk that is dropped.'},
                                 {'reference': 'examples/schemaxis/flac-tag-archive.json', 'purpose': 'Archive a recording with title, artist and description labels.'},
                                 {'reference': 'examples/schemaxis/flac-tag-unicode.json', 'purpose': 'Archive a recording with non-ASCII labels preserved as exact UTF-8.'}]},
                'decodePCM16': {
                    'purpose': 'Decode one native FLAC recording into a canonical PCM16 WAV for speech preparation, checking the decoded samples against the FLAC sample count and MD5.',
                    'keywords': ['decode FLAC to WAV', 'FLAC', 'decode FLAC', 'FLAC to WAV', 'lossless recording', 'PCM16 WAV', 'prepare audio for transcription', 'speech recognition input', 'flac', 'libFLAC', 'extract PCM', 'archive recording'],
                    'semantics': ['Only native FLAC with 16-bit mono or stereo audio, a known length and an MD5 is accepted; STREAMINFO, metadata framing and the first frame header are checked before native decoding, and damaged frames are refused, never concealed.',
                                  'The published WAV is the exact decoded PCM in a canonical 44-byte WAV that the SoX conform operation accepts. The MD5 check is internal consistency of the file; it does not show that the recording is authentic. Tags (including archive labels), pictures and seek tables are dropped and listed.'],
                    'examples': [{'reference': 'examples/schemaxis/flac-decode.json', 'purpose': 'Decode a 16 kHz stereo FLAC to PCM16 WAV.'},
                                 {'reference': 'examples/schemaxis/flac-decode-tagged.json', 'purpose': 'Decode a FLAC that carries tags, a seek table and padding, which are dropped.'}]}}}
