# Copyright (C) 2026 David L F Gaden
"""Selection and loss guidance for bounded media preparation."""
import json
from importlib.resources import files


def catalogue():
    return {
        'application': {'label': 'FFmpeg', 'purpose': 'Prepare silent video from images, sprite sheets or a bounded existing clip, and mux a verified video, speech WAV and SRT captions into one review movie.',
                        'keywords': ['media preparation', 'video conversion', 'animation publication', 'FFmpeg', 'review movie', 'captions', 'subtitles', 'SRT', 'narration']},
        'groups': {'video': {'label': 'Video publication', 'purpose': 'Encode images, trim and retime an existing silent video, or mux audio and captions into a review movie.', 'domain': 'media'}},
        'requirements': ['Requires FFmpeg and matching FFprobe; input paths must be absolute.',
                         'Constant output frame rate; encodeFrames/encodeSheet/encodeVideo write silent video, muxReview adds PCM16 audio and SubRip captions, and extractAudio decodes AAC-LC to PCM16 WAV, and encodeAudio publishes a prepared PCM16 WAV as compressed AAC-LC audio under declared budgets; image alpha composites onto black.',
                         'FFV1 must decode losslessly; H.264 has a bounded per-frame RGB error check.'],
        'references': ['docs/ffmpeg.md', 'docs/media-workflows.md#ffmpeg-publication',
                       'src/schemaxis/adaptors/ffmpeg/readiness.json'],
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'operations': {
            'encodeFrames': {'purpose': 'Encode an explicitly ordered list of PNG files as video.', 'groups': ['video'],
                'keywords': ['PNG sequence', 'image sequence', 'ordered frames', 'rendered animation'],
                'semantics': ['There is no implicit filename sorting; repeating a file repeats the frame.',
                              'Frames need equal dimensions; H.264 width and height must be even.']},
            'encodeSheet': {'purpose': 'Encode a sprite sheet using declared frame rectangles and durations.', 'groups': ['video'],
                'keywords': ['sprite sheet', 'Aseprite timing', 'frame rectangles', 'sprite animation'],
                'semantics': ['Metadata must use schemaxis.aseprite.sheet/1; frame durations must be representable at the selected fps.',
                              'Metadata order determines playback; tags do not select or reorder frames.']},
            'encodeVideo': {'purpose': 'Trim video presentation frames and retime an existing clip into a verified silent publication.', 'groups': ['video'],
                'keywords': ['trim video', 'existing clip', 'frame range', 'retime clip', 'transcode video', 'MP4', 'Matroska', 'H264', 'FFV1'],
                'semantics': ['Zero-based startFrame inclusive, endFrame exclusive; output fps retimes every selected presentation frame.',
                              'Single silent progressive MP4/H264 yuv420p or MKV/FFV1 bgr0; complete source bounded to 600 frames and 192 MiB RGB.',
                              'Native MP4 edit-list presentation is honoured; no arbitrary filters or multi-clip timeline.']},
            'muxReview': {'purpose': 'Combine a silent FFV1 video, a PCM16 speech WAV and an SRT caption file into one verified Matroska review movie with soft captions.', 'groups': ['video'],
                'keywords': ['review movie', 'captions', 'subtitles', 'SRT', 'SubRip', 'soft subtitles', 'subtitle track', 'add audio to video', 'narration', 'speech track', 'mux', 'Matroska', 'PCM'],
                'semantics': ['Stream-copies FFV1 video and PCM16 audio and stores SubRip text; no re-encoding, burn-in, trimming, padding or resampling.',
                              'Audio and video durations must agree within one video frame period; every caption must end inside the video.',
                              'Captions are a machine draft unless declared otherwise; accuracy and human review are never certified.']},
            'encodeAudio': {'purpose': 'Publish one prepared PCM16 WAV as a verified compressed AAC-LC audio file under a declared byte budget and a declared mean waveform error budget.', 'groups': ['video'],
                'keywords': ['encode audio', 'compress audio', 'shareable audio', 'publish audio', 'archive audio', 'narration', 'voice recording', 'speech file', 'lossy audio', 'audio file size', 'shareable audio file', 'error budget', 'audio error budget', 'AAC encoder'],
                'semantics': ['Canonical PCM16 input, mono or stereo at 16000, 22050, 44100 or 48000 Hz, at most 600 s and 32 MiB; explicit bitrateKbps 64/96/128/192 and required maxBytes and maxMeanPCMError; no resampling, mixing, normalising, trimming or padding.',
                              'The published file is decoded again natively at the source rate and channels; the frame count must be exact on a zero-origin timeline and every sample is compared; mean absolute error is judged exactly as a rational against the authored budget.',
                              'AAC is lossy, never lossless or high quality; the error budget is a waveform number, not a listening, audibility, recognition or identity measure.']},
            'extractAudio': {'purpose': 'Decode the AAC audio of one MP4/M4A recording into a verified canonical PCM16 WAV and an audio summary.', 'groups': ['video'],
                'keywords': ['extract audio', 'audio from video', 'M4A', 'AAC', 'MP4 audio', 'voice memo', 'phone recording', 'camera audio', 'speech recording', 'AAC to WAV', 'M4A to WAV', 'decode AAC', 'transcription input', 'PCM16', 'WAV'],
                'semantics': ['One AAC-LC audio stream chosen by global streamIndex; mono or stereo, 8-96 kHz, at most 600 s; native rate and channels, no resampling, mixing, trimming or padding.',
                              'The frame count comes from decoded audio frames, not packets or container duration; extra audio, subtitle, data and cover-art streams, chapters and fragmented or external MP4 are refused; probe output over 4 MiB (large metadata tags) or over 17600 packets is RESOURCE_LIMIT.',
                              'AAC is lossy: the WAV is a machine-draft decode, with no equality to the original recording and no recognition accuracy or human review certified.']}}}
