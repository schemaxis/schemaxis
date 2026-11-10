"""Scientific EXR planes require a fresh trusted native reconstruction.

The reference argument is internal verifier output, never a submitted receipt or
an authored pathname. Public verification must create it afresh on every check.
Ordinary colour images retain their separate source-bound rendering contract.
"""
import hashlib
import json

from schemaxis.errors import fail
from .exr_output import inspect
from .render_bundle_layout import channels, definitions


def requires_reference(definition):
    return definition['format'] == 'exr' and any(slot['scientific'] for slot in definition['slots'])


def validate_context(spec, render):
    """Additional device profiles need their own actual determinism evidence."""
    if any(requires_reference(item) for item in definitions(spec)):
        if render['renderer']['kind'] != 'cycles' or render['device'] != 'CPU':
            fail('UNSUPPORTED_RENDER_DATA_BASELINE',
                 'scientific plane reconstruction currently requires the qualified Cycles CPU baseline',
                 'renderBundles', renderer=render['renderer']['kind'], device=render['device'])


def _shape(definition, facts, size):
    expected = channels(definition)
    actual = {channel['name']: channel for channel in facts['channels']}
    if facts['size'] != list(size) or facts['dataWindow'] != [0, 0, size[0] - 1, size[1] - 1] or set(actual) != set(expected):
        fail('VERIFICATION_FAILED', 'render bundle dimensions or channel membership differ', definition['output'])
    precision = definition['encoding']['precision']
    if facts['compression'] != definition['encoding']['compression'] or any(c['pixelType'] != precision for c in actual.values()):
        fail('VERIFICATION_FAILED', 'render bundle component precision or codec differs', definition['output'])
    return expected, actual


def layout(definition,path,size):
    """Host format gate; scientific authority still requires verify()."""
    if definition['format']=='exr':
        facts=inspect(path);_shape(definition,facts,size);return facts
    from .png_output import inspect as png_inspect
    facts=png_inspect(path);encoding=definition['encoding']
    if (facts['size']!=list(size) or facts['depth']!=encoding['depth']
            or facts['channels']!=encoding['channels']):
        fail('VERIFICATION_FAILED','render bundle PNG dimensions/precision/components differ',definition['output'])
    return facts


def verify(definition, path, size, *, fresh_reference=None):
    if definition['format'] != 'exr':
        fail('INVALID_RENDER_BUNDLE', 'scientific plane inspection requires an EXR definition')
    facts = inspect(path)
    expected, actual = _shape(definition, facts, size)
    scientific = sorted(name for name, meaning in expected.items() if meaning['scientific'])
    signature = None
    if scientific:
        if fresh_reference is None:
            fail('VERIFICATION_RUNTIME_REQUIRED',
                 'scientific bundle verification requires a newly rendered trusted reference', definition['output'])
        reference = inspect(fresh_reference)
        _, original = _shape(definition, reference, size)
        differences = [name for name in scientific if actual[name] != original[name]]
        if differences:
            fail('VERIFICATION_FAILED',
                 'scientific render planes differ from fresh trusted source reconstruction',
                 definition['output'], channels=differences)
        # Date and render duration are observations, not data semantics. Keep
        # source-identifying matte metadata, working primaries and frame stamps.
        names = {'chromaticities', 'whiteLuminance', 'adoptedNeutral',
                 'Frame', 'framesPerSecond', 'timeCode'}
        semantic = lambda value: {name: record for name, record in value['attributes'].items() if name in names}
        if (facts['pixelAspect'] != reference['pixelAspect']
                or facts['cryptomatte'] != reference['cryptomatte']
                or semantic(facts) != semantic(reference)):
            fail('VERIFICATION_FAILED',
                 'scientific render metadata differs from fresh trusted source reconstruction', definition['output'])
        witness = {'planes': {name: original[name] for name in scientific},
                   'cryptomatte': reference['cryptomatte'], 'metadata': semantic(reference),
                   'pixelAspect': reference['pixelAspect']}
        signature = 'sha256:' + hashlib.sha256(json.dumps(witness, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {**facts, 'scientificPlanes': scientific, 'freshDataSignature': signature,
            'verification': 'freshScientificPlanes' if scientific else 'sourceBoundColour'}
