# Copyright (C) 2026 David L F Gaden
"""Small purpose map over declared bindings, independent of native inventory help."""


def catalogue():
    sliced = {'version': 'schemaxis/1', 'nodes': [
        {'id': 'source', 'filter': 'wavelet'},
        {'id': 'section', 'filter': 'slice', 'inputs': {'input': 'source'}, 'options': {'normal': 'z+'}}],
        'scenes': [{'id': 'result', 'geometry': ['section']}]}
    result = {
        'groups': {
            'sources': {'label': 'Scientific data sources', 'purpose': 'Read CFD data or create analytic test data.', 'domain': 'data-analysis'},
            'sampling': {'label': 'Sampling and sections', 'purpose': 'Extract sections and sample scientific fields.', 'domain': 'data-analysis'},
            'reductions': {'label': 'Field reductions', 'purpose': 'Integrate fields over datasets.', 'domain': 'data-analysis'}},
        'requirements': [
            'Native field and dataset compatibility needs resource inspection or execution; unknown traits do not imply unsupported input.',
            'Scenes select active nodes and publications. Unreferenced nodes need not execute.',
            'Coordinate and field units come from the input dataset; no automatic unit conversion is implied.',
            'Execution modes and native qualification depend on the operation and whole document. Serial declaration metadata is not MPI qualification.'],
        'references': ['docs/paraview-catalogue.md', 'docs/generated/paraview-operations.md'],
        'operations': {
            'wavelet': {'purpose': 'Create analytic image data with the RTData field for scientific test cases.',
                        'groups': ['sources'], 'keywords': ['synthetic', 'test'], 'related': ['slice', 'contour'],
                        'examples': [{'purpose': 'Extract a plane through an analytic wavelet.', 'document': sliced}]},
            'foam': {'purpose': 'Read an OpenFOAM case with selected mesh regions and cell arrays.',
                     'groups': ['sources'], 'keywords': ['reader', 'simulation'], 'related': ['slice', 'integrate'],
                     'examples': [{'document': {'version': 'schemaxis/1', 'nodes': [{'id': 'case', 'filter': 'foam', 'options': {'file': '/replace-with-your-case/case.foam'}}], 'times': [0], 'scenes': [{'id': 'mesh', 'geometry': ['case']}]}, 'purpose': 'Plan one explicit time; execution requires a real CFD case. Inspect available times before choosing them.'}]},
            'slice': {'purpose': 'Extract a planar cross-section of a dataset.', 'groups': ['sampling'],
                      'keywords': ['plane', 'cross-section', 'cut'], 'related': ['wavelet', 'foam', 'contour'],
                      'semantics': ['The plane normal must resolve to a nonzero direction.'],
                      'examples': [{'purpose': 'Extract a plane through an analytic wavelet.', 'document': sliced}]},
            'contour': {'purpose': 'Extract isosurfaces at selected values of a selected field.',
                        'groups': ['sampling'], 'keywords': ['iso', 'level'], 'related': ['wavelet', 'slice']},
            'probeLine': {'purpose': 'Sample dataset fields along a line.', 'groups': ['sampling'],
                          'keywords': ['1D', 'profile', 'plot'], 'related': ['foam', 'slice']},
            'integrate': {'purpose': 'Integrate fields over dataset cells, optionally dividing by volume.',
                          'groups': ['reductions'], 'keywords': ['integral', 'total', 'reduction'], 'related': ['foam'],
                          'examples': [{'reference': 'examples/schemaxis/filter-coverage.json',
                                        'purpose': 'Integration and declared measurement publications.'}]}}}

    from importlib.resources import files
    import json
    from .filters import catalogue as declarations
    declared = declarations()
    records = json.loads(files(__package__).joinpath('native-context.json').read_text())['operations']
    by_native = {d['native']: records[d['nativeIdentity']] for d in declared.values()
                 if d.get('nativeIdentity') in records}
    for name, declaration in declared.items():
        if name in result['operations']:
            continue
        record = records.get(declaration.get('nativeIdentity')) or by_native.get(declaration['native'])
        if record is None:
            raise ValueError('Missing native selection context for ' + name)
        semantics = [record['basis'] + '; declaration presence does not establish native qualification.',
                     'Inspect exact input domains, omitted native defaults and output traits before use. No implicit format or unit conversion.']
        if record.get('description'):
            semantics.append(record['description'])
        result['operations'][name] = {'purpose': record['selection'], 'semantics': semantics}
    result['references'].append('src/schemaxis/adaptors/paraview/native-context.json')
    return result
