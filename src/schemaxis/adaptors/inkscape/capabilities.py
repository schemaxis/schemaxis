"""Domain intent and measured acceptability for declared technical diagrams."""
def catalogue():
    return {'groups': {'diagram': {'label': 'Technical diagrams', 'purpose': 'Produce a measured, editable technical block diagram.', 'domain': 'visualisation'}},
            'requirements': ['Coordinates, padding, clearance and font size are mm; native text must fit its declared box.', 'Connections require left-to-right clearance and must avoid unrelated boxes.', 'Stable Inkscape 1.4.x query-all and PNG export CLI; fonts affect measured label extents.'],
            'references': ['docs/inkscape.md', 'src/schemaxis/adaptors/inkscape/readiness.json'],
            'operations': {'flowDiagram': {'purpose': 'Turn named steps and directed dependencies into a deterministic DAG diagram that must satisfy page, clearance and native label-fit budgets.',
                'groups': ['diagram'], 'keywords': ['dependency', 'DAG', 'automatic layout', 'rank', 'lane'],
                'semantics': ['Longest-path ranks place each dependency to the right; lexical names provide deterministic lanes independent of authored array order.', 'Required page dimensions and native text fit are explicit acceptance requirements; cycles, page overflow and colliding deterministic routes fail with distinct recovery.', 'No arbitrary routing optimisation or font-size search; blockDiagram remains available for explicit card placement.'],
                'related': ['blockDiagram'],
                'examples': [{'reference': 'examples/schemaxis/inkscape-flow.json', 'purpose': 'Branch one input into two parallel steps and merge their results without manual coordinates.'}, {'reference': 'examples/schemaxis/inkscape-flow-variant.json', 'purpose': 'Add a validation dependency rank within a larger page budget.'}]},
            'blockDiagram': {'purpose': 'Publish labelled boxes and directed connectors only when native geometry and declared layout requirements agree.',
                'groups': ['diagram'], 'keywords': ['block diagram', 'SVG', 'label fit', 'clearance'],
                'semantics': ['Editable SVG retains named vector/text objects; PNG is flattened.', 'Authored geometry is checked before launch, actual font-dependent label bounds after native readback.', 'Native queried bounds and decoded PNG probes are independently checked; file existence alone is insufficient.'],
                'examples': [{'reference': 'examples/schemaxis/inkscape-diagram.json', 'purpose': 'Two labelled blocks with measured clearance and an arrow.'}, {'reference': 'examples/schemaxis/inkscape-diagram-variant.json', 'purpose': 'Reposition the output block and measure its dogleg connector.'}]}}}
