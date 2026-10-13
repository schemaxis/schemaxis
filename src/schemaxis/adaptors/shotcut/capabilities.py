"""Selection guidance for bounded native timeline editing."""
def catalogue():
    return {'groups': {'editing': {'label': 'Timeline editing', 'purpose': 'Trim and arrange named video source ranges.', 'domain': 'media'}},
            'requirements': ['Shotcut-bundled melt, ffmpeg and ffprobe beside one another.',
                             'Silent progressive square-pixel sources at the declared constant integer fps and pixel dimensions.',
                             'Project.mlt requires captured asset companions; retain the complete run directory.'],
            'references': ['docs/shotcut.md', 'src/schemaxis/adaptors/shotcut/readiness.json'],
            'operations': {'editTimeline': {'purpose': 'Trim, reorder or repeat named video frame ranges into an editable Shotcut project and verified FFV1 render.',
                'groups': ['editing'], 'semantics': ['Clips use zero-based startFrame and positive frameCount; timeline order is explicit.',
                    'Every rendered frame is compared with selected source RGB; native MLT reload must reproduce the same timeline and pixels.',
                    'No audio, gaps, transitions, resizing or rate conversion are supported.']}}}
