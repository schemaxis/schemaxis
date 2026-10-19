"""Curated PCM audio assembly discovery without native imports."""
import json
from importlib.resources import files


def catalogue():
    return {'application':{'label':'SoX','purpose':'Assemble PCM WAV audio excerpts using sample-frame cuts, linear amplitude gains and fades, then concatenate in order.','keywords':['PCM WAV','audio assembly','sample frame','trim','linear fade','concatenate','Sound eXchange']},
        'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':['Use absolute canonical PCM16 WAV paths, identical mono/stereo channel counts and sample rates.','Declare integer frame cuts and nonoverlapping fades; pre-fade gain must not clip.','Bounded serial file processing only; no authored scripts, arbitrary effects, resampling, mixing or playback.'],
        'references':['docs/sox.md','src/schemaxis/adaptors/sox/readiness.json'],
        'operations':{'assemble':{'purpose':'Assemble PCM WAV audio excerpts with frame-accurate trim, gain and linear fade envelopes, concatenating processed clips into a verified recording.',
            'keywords':['audio assembly','PCM WAV','sample frame','trim','gain','linear fade','concatenate','Sound eXchange','SoX','edit decision list','join recordings'],
            'semantics':['Integer sample frames give exact half-open source selections; linear amplitude gain precedes nonoverlapping fades.','Independent PCM reopening checks each processed sample and exact concatenation; source hashes invalidate stale reuse.'],
            'examples':[{'reference':'examples/schemaxis/sox-assembly.json','purpose':'Join two mono recording excerpts with gains and fades.'},{'reference':'examples/schemaxis/sox-stereo.json','purpose':'Assemble two stereo takes with explicit frame envelopes.'}]}}}
