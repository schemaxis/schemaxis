# Copyright (C) 2026 David L F Gaden
"""Selection and loss guidance for bounded media preparation."""
import json
from importlib.resources import files


def catalogue():
    return {
        'application': {'label': 'FFmpeg', 'purpose': 'Prepare silent video from images, sprite sheets or a bounded existing clip.',
                        'keywords': ['media preparation', 'video conversion', 'animation publication', 'FFmpeg']},
        'groups': {'video': {'label': 'Video publication', 'purpose': 'Encode images or trim and retime an existing silent video.', 'domain': 'media'}},
        'requirements': ['Requires FFmpeg and matching FFprobe; input paths must be absolute.',
                         'Constant output frame rate and no audio; image alpha composites onto black.',
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
                              'Native MP4 edit-list presentation is honoured; no arbitrary filters or multi-clip timeline.']}}}
