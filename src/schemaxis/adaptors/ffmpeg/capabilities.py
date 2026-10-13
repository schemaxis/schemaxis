"""Selection and loss guidance for the bounded video publication contract."""


def catalogue():
    return {
        'groups': {'video': {'label': 'Video publication', 'purpose': 'Encode explicit PNG frames or a sprite sheet.', 'domain': 'media'}},
        'requirements': ['Requires FFmpeg and matching FFprobe; input paths must be absolute.',
                         'Alpha composites onto black; constant frame rate and no audio.',
                         'FFV1 must decode losslessly; H.264 has a bounded per-frame RGB error check.'],
        'references': ['docs/media-workflows.md#ffmpeg-publication',
                       'src/schemaxis/adaptors/ffmpeg/readiness.json'],
        'operations': {
            'encodeFrames': {'purpose': 'Encode an explicitly ordered list of PNG files as video.', 'groups': ['video'],
                             'semantics': ['There is no implicit filename sorting; repeating a file repeats the frame.',
                                           'Frames need equal dimensions; H.264 width and height must be even.']},
            'encodeSheet': {'purpose': 'Encode a sprite sheet using declared frame rectangles and durations.', 'groups': ['video'],
                            'semantics': ['Metadata must use schemaxis.aseprite.sheet/1; frame durations must be representable at the selected fps.',
                                          'Metadata order determines playback; tags do not select or reorder frames.']}}}
