"""Reviewed adaptor mappings; native inventory is captured separately.

Adding a native option here is an implementation decision, not an automatic
consequence of discovering a property. Verification must cover its semantics.
"""
SLICE_OPTIONS = {
    'crinkle': {
        'pythonName': 'Crinkleslice',
        'argument': {'type': 'boolean', 'default': False,
                     'summary': 'Keep whole intersected cells; exports VTU instead of a planar VTP surface'},
    },
    'triangulate': {
        'pythonName': 'Triangulatetheslice',
        'argument': {'type': 'boolean', 'default': True,
                     'summary': 'Produce triangles for a cut surface; does not apply to crinkle slicing'},
    },
    'pointMergeMethod': {
        'pythonName': 'PointMergeMethod',
        'argument': {'type': 'enum', 'default': 'uniformBinning',
                     'values': ['uniformBinning', 'octreeBinning', 'none'],
                     'summary': 'Method for merging coincident cut-surface points; does not apply to crinkle slicing'},
        'values': {'uniformBinning': 'UniformBinning', 'octreeBinning': 'OctreeBinning',
                   'none': 'NotMergingPoints'},
    },
}

# Every top-level native property has an explicit disposition. This inventory
# prevents properties silently disappearing during adaptor construction.
SLICE_COVERAGE = {
    'Crinkleslice': {'status': 'supported', 'argument': 'crinkle'},
    'Triangulatetheslice': {'status': 'supported', 'argument': 'triangulate'},
    'PointMergeMethod': {'status': 'supported', 'argument': 'pointMergeMethod',
                         'limitation': 'locator sub-properties are not configurable yet'},
    'Input': {'status': 'managed', 'reason': 'the capability supplies a Wavelet or a decomposed OpenFOAM case'},
    'InputBounds': {'status': 'information', 'reason': 'native read-only data-dependent information'},
    'SliceType': {'status': 'restricted', 'reason': 'Plane only; origin and normal are configurable'},
    'SliceOffsetValues': {'status': 'unsupported', 'reason': 'multiple simultaneous offsets need multi-plane verification'},
    'HyperTreeGridSlicer': {'status': 'unsupported', 'reason': 'synthetic input is not a hyper tree grid'},
    'UseDual': {'status': 'unsupported', 'reason': 'requires hyper tree grid input and dedicated verification'},
}
