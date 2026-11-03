# Copyright (C) 2026 David L F Gaden
"""Pure helpers for OpenFOAM authoring; no ParaView import."""

def foam_regions(groups):
    selectors = [selector for values in groups.values() for selector in values]
    if any(not s.startswith('//') or not s[2:] or '/' in s[2:] for s in selectors):
        raise ValueError('foamRegions expects //patchName selectors')
    return list(dict.fromkeys(['internalMesh'] + ['patch/' + s[2:] for s in selectors]))


def register(registry):
    selectors = {'type': 'array', 'items': {'type': 'string', 'minLength': 3}, 'minItems': 1}
    registry.register('foamRegions', {'groups': {'type':'object','properties':{
        'tyres': {**selectors,'required':True}, 'body':{**selectors,'required':True}},'required':True}},
        {'type':'array','items':{'type':'string'}},foam_regions)
