"""Native ParaView capture, save and independent reload of editable state bundles.

Runs only inside pvbatch. ``capture_inputs`` runs after the visit is applied and
before any publication consumes it: each reader file is captured with the shared
bounded ``workflow_resources.capture`` and the reader is rebound to that pinned
copy, so the image and the saved state consume the same bytes. ``save_bundle``
runs after the scene's image. ``reload_bundle`` is the internal entry point of a
separate, freshly started process that loads this run's own relocated bundle.
None of them accepts authored state files or scripts.
"""
import math
import os
from pathlib import Path

from schemaxis import workflow_resources as resources
from schemaxis.core.faults import SchemaxisError
from schemaxis.errors import fail
from schemaxis.artifacts import atomic_json
from . import handback


def _hash(path):
    return handback._hash(path)


def observe(proxy):
    """Dataset summary computed identically in the saving and reloading processes."""
    info = proxy.GetDataInformation()
    bounds = list(info.GetBounds())
    if not all(math.isfinite(v) for v in bounds):
        fail('INVALID_DATA', 'nonfinite dataset bounds')
    fields = {}
    for association, arrays in (('POINTS', proxy.PointData), ('CELLS', proxy.CellData)):
        fields[association] = {}
        for key in arrays.keys():
            values = list(arrays[key].GetRange()) if arrays[key].GetDataType() != 13 else None
            if values is not None and not all(math.isfinite(v) for v in values):
                values = None
            fields[association][key] = {'components': arrays[key].GetNumberOfComponents(), 'range': values}
    return {'dataType': info.GetDataClassName(), 'points': info.GetNumberOfPoints(),
            'cells': info.GetNumberOfCells(), 'bounds': bounds, 'fields': fields}


def identity(proxy, pxm):
    """Stable node identity: the ParaView log name, which keeps the node id.

    Global proxy IDs change between processes, and loading a state with a data
    directory renames relocated readers to their file names in the Pipeline
    Browser, so registration names are recorded but not used as identity.
    """
    return proxy.GetLogName() or pxm.GetProxyName('sources', proxy)


def connections(proxy, pxm):
    """Input connections by stable node identity."""
    result = []
    for name in proxy.ListProperties():
        prop = proxy.GetProperty(name).SMProperty
        if not prop.IsA('vtkSMInputProperty'):
            continue
        for index in range(prop.GetNumberOfProxies()):
            result.append(f'{name}={identity(prop.GetProxy(index), pxm)}:'
                          f'{prop.GetOutputPortForConnection(index)}')
    return sorted(result)


def _file_domain(prop):
    iterator = prop.NewDomainIterator()
    iterator.Begin()
    while not iterator.IsAtEnd():
        if iterator.GetDomain().IsA('vtkSMFileListDomain'):
            return True
        iterator.Next()
    return False


def file_properties(smproxy, prefix='', depth=0):
    """Every property declaring a native file-list domain, including nested proxy properties.

    Discovery uses ParaView's own domain declarations rather than property names;
    input connections are not traversed. A traversal bound refuses the bundle;
    it must never hide a file property by truncating native readback.
    """
    found = {}
    iterator = smproxy.NewPropertyIterator()
    iterator.Begin()
    while not iterator.IsAtEnd():
        name, prop = iterator.GetKey(), iterator.GetProperty()
        if prop.IsA('vtkSMStringVectorProperty') and _file_domain(prop):
            count = prop.GetNumberOfElements()
            if not 0 <= count <= 64:
                fail('UNSUPPORTED_STATE_BUNDLE', 'native file property exceeds the supported value count',
                     prefix + name, limit=64)
            values = [prop.GetElement(i) for i in range(count)]
            found[prefix + name] = [str(v) for v in values if v]
        elif prop.IsA('vtkSMProxyProperty') and not prop.IsA('vtkSMInputProperty'):
            count = prop.GetNumberOfProxies()
            if not 0 <= count <= 16 or (count and depth >= 2):
                fail('UNSUPPORTED_STATE_BUNDLE', 'nested native file-property discovery exceeds its bound',
                     prefix + name, maxProxies=16, maxDepth=2)
            for index in range(count):
                nested = prop.GetProxy(index)
                if nested is not None:
                    found.update(file_properties(nested, f'{prefix}{name}[{index}].', depth + 1))
        iterator.Next()
    return found


def _plain(value, depth=0):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    target = getattr(value, 'SMProxy', value)
    if hasattr(target, 'GetXMLName') and hasattr(target, 'GetXMLGroup'):
        return target.GetXMLGroup() + '/' + target.GetXMLName()
    if depth < 2:
        try:
            items = list(value)
        except TypeError:
            return str(value)
        if len(items) > handback.LIMITS['propertyValues']:
            fail('VERIFICATION_FAILED', 'native property readback exceeds its bound')
        return [_plain(item, depth + 1) for item in items]
    return str(value)


def read_properties(proxy, specs):
    """Read back the declared native properties named by ``specs``; paths come from declarations."""
    from .native import property_value, raw_elements
    result = []
    for spec in specs:
        if spec['raw']:
            value = raw_elements(proxy, spec['path'])
            value = value[0] if len(value) == 1 else value
        else:
            value = property_value(proxy, spec['path'])
        result.append({'option': spec['option'], 'path': list(spec['path']), 'raw': spec['raw'],
                       'value': _plain(value)})
    return result


def display(display_proxy):
    colour = list(display_proxy.ColorArrayName)
    return {'colour': colour if colour[1] else list(display_proxy.DiffuseColor),
            'opacity': float(display_proxy.Opacity),
            'representation': display_proxy.SMProxy.GetProperty('Representation').GetElement(0)}


def presentation(pv, display_proxy, view, titled):
    """Scalar lookup-table points, log scale and legend visibility/title of one coloured display."""
    lut = display_proxy.LookupTable
    if lut is None:
        fail('VERIFICATION_FAILED', 'coloured display lacks a lookup table')
    result = {'points': [float(v) for v in lut.RGBPoints], 'logScale': bool(lut.UseLogScale),
              'legendVisible': bool(display_proxy.SMProxy.IsScalarBarVisible(view.SMProxy))}
    # Only an existing legend is read; GetScalarBar would otherwise create one.
    if titled:
        result['legendTitle'] = str(pv.GetScalarBar(lut, view).Title)
    return result


def camera(view):
    return {'position': list(view.CameraPosition), 'focalPoint': list(view.CameraFocalPoint),
            'up': list(view.CameraViewUp), 'parallel': bool(view.CameraParallelProjection),
            'scale': float(view.CameraParallelScale),
            'viewAngle': float(view.GetClientSideObject().GetActiveCamera().GetViewAngle())}


def _source_digest(path, size, node):
    """Bounded recheck of the original input against its captured size and digest."""
    try:
        signature = resources._regular(Path(path))
        if signature[3] != size:
            fail('INPUT_CHANGED', 'reader input changed size after capture', str(path), node=node)
        return resources._read_file(Path(path), signature)
    except SchemaxisError as error:
        if error.fault.code == 'INPUT_CHANGED':
            raise
        fail('INPUT_CHANGED', 'reader input cannot be rechecked after capture: ' + error.fault.message, str(path),
             node=node, cause=error.fault.code)
    except OSError as error:
        fail('INPUT_CHANGED', 'reader input cannot be rechecked after capture: ' + str(error), str(path), node=node)


def capture_inputs(active, master, scene, visit, state, bundle):
    """Capture and rebind each reader before any publication consumes this visit.

    Returns the per-node rebinding provenance recorded as ``state['inputRebinding']``.
    The effective settings keep the authored origin; publications consume the copy.
    """
    bundle = Path(bundle).absolute()
    bundle.mkdir()
    (bundle / handback.DATA).mkdir()
    rebinding, total = {}, 0
    for node in scene['selection']['order']:
        filter_id = master.nodes[node]['filter']
        if filter_id not in handback.READERS:
            continue
        effective = state['effective'][node]['files'][0]
        if not os.path.isabs(effective):
            fail('UNSUPPORTED_STATE_BUNDLE', 'bundled reader inputs must be absolute paths', effective, node=node)
        original = Path(os.path.abspath(effective))
        if filter_id in handback.XML_READERS:
            suffix = handback.XML_READERS[filter_id]
            if original.suffix.lower() != suffix:
                fail('UNSUPPORTED_STATE_BUNDLE', 'reader input is not a ' + suffix + ' document', str(original),
                     node=node)
        resource, relative = handback.member_layout(node, original.name)
        remaining = handback.LIMITS['totalBytes'] - total
        if remaining < 0 or len(rebinding) >= handback.LIMITS['files']:
            fail('UNSUPPORTED_STATE_BUNDLE', 'bundled reader inputs exceed limits', str(bundle), limits=handback.LIMITS)
        try:
            # Size limits are enforced from metadata before any byte is read.
            captured = resources.capture(original, bundle / resource, kind='file', max_files=1,
                                         max_bytes=min(handback.LIMITS['fileBytes'], remaining))
        except SchemaxisError as error:
            if error.fault.code in ('INVALID_RESOURCE', 'RESOURCE_LIMIT', 'UNSUPPORTED_RESOURCE'):
                fail('UNSUPPORTED_STATE_BUNDLE', 'reader input cannot be captured into the state bundle: '
                     + error.fault.message, str(original), node=node, cause=error.fault.code)
            if error.fault.code in ('RESOURCE_CHANGED', 'RESOURCE_MISMATCH'):
                fail('INPUT_CHANGED', 'reader input changed while it was captured: ' + error.fault.message,
                     str(original), node=node, cause=error.fault.code)
            raise
        record, = captured['files']
        if filter_id in handback.XML_READERS:
            from .input_closure import document_type, LEAVES
            if document_type(bundle / relative) != LEAVES[handback.XML_READERS[filter_id]]:
                fail('UNSUPPORTED_STATE_BUNDLE', 'captured reader input is not a self-contained document',
                     str(original), node=node)
        total += record['size']
        prop = handback.READERS[filter_id]
        setattr(active.handles[node], prop, [str(bundle / relative)])
        rebinding[node] = {'property': prop, 'origin': str(original), 'captured': str(bundle.resolve() / relative),
                           'sha256': record['sha256'], 'resourceDigest': captured['digest'], 'bytes': record['size'],
                           'resourceSha256': _hash(bundle / resource / handback.RESOURCE)}
    for node in scene['selection']['order']:
        proxy = active.handles[node]
        proxy.UpdatePipeline(visit['time'])
        # The rebound pipeline must reproduce the run's observations before anything is published.
        handback._close(observe(proxy), handback.summary(state['observations'][node]), 'rebound.' + node)
    return rebinding


def verify_captures(bundle, state):
    """Post-consumer checks: each pinned copy is intact and its origin still matches it."""
    bundle = Path(bundle).absolute()
    members = []
    for node, entry in state['inputRebinding'].items():
        resource, relative = handback.member_layout(node, Path(entry['origin']).name)
        try:
            captured = resources.verify(bundle / resource, max_files=1, max_bytes=handback.LIMITS['fileBytes'])
        except SchemaxisError as error:
            fail('VERIFICATION_FAILED', 'captured reader input changed after it was consumed: ' + error.fault.message,
                 str(bundle / resource), node=node, cause=error.fault.code)
        if captured['digest'] != entry['resourceDigest'] or \
                _hash(bundle / resource / handback.RESOURCE) != entry['resourceSha256']:
            fail('VERIFICATION_FAILED', 'captured reader input changed after it was consumed', str(bundle / resource))
        if _source_digest(entry['origin'], entry['bytes'], node) != entry['sha256']:
            fail('INPUT_CHANGED', 'reader input changed after it was captured', entry['origin'], node=node)
        members.append({'node': node, 'path': relative, 'resource': resource, 'sha256': entry['sha256'],
                        'bytes': entry['bytes'], 'origin': entry['origin'], 'property': entry['property'],
                        'resourceDigest': entry['resourceDigest'], 'resourceSha256': entry['resourceSha256'],
                        'proxyId': state['proxyIds'][node]})
    return members


def save_bundle(backend, renderer, active, master, scene, visit, state, image, bundle, runtime):
    pv = backend.pv
    pxm = backend.sm.ProxyManager()
    bundle = Path(bundle).absolute()
    order = scene['selection']['order']
    members = verify_captures(bundle, state)
    for node in order:
        unbound = {name: values for name, values in file_properties(active.handles[node].SMProxy).items()
                   if values and not (node in state['inputRebinding']
                                      and name == state['inputRebinding'][node]['property'])}
        if unbound:
            fail('UNSUPPORTED_STATE_BUNDLE', 'pipeline object has file-bearing properties outside the bundle', node,
                 properties=sorted(unbound))
    view = renderer.view
    layout = pv.CreateLayout('Schemaxis state bundle')
    pv.AssignViewToLayout(view=view, layout=layout, hint=0)
    layout.SetSize(*image['dimensions'][:2])
    view.ViewSize = image['dimensions'][:2]
    pv.Render(view)
    handback._close(camera(view), image['camera'], 'saved.camera')
    appearance = {node: display(renderer.displays[node]) for node in scene['visible']}
    handback._close(appearance, handback.normal(image['appearance']), 'saved.appearance')
    effective = image['effectiveAppearance']
    colours = {node: presentation(pv, renderer.displays[node], view,
                                  bool(effective[node].get('legend')) or 'legendTitle' in effective[node])
               for node in scene['visible'] if effective[node].get('field')}
    state_path = bundle / handback.STATE
    try:
        pv.SaveState(str(state_path))
    finally:
        pv.RemoveLayout(layout)
    pipeline = {}
    for node in order:
        proxy = active.handles[node]
        if identity(proxy.SMProxy, pxm) != node:
            fail('VERIFICATION_FAILED', 'saved pipeline object lacks its stable node identity', node,
                 observed=identity(proxy.SMProxy, pxm))
        pipeline[node] = {'proxyId': state['proxyIds'][node], 'xmlName': proxy.SMProxy.GetXMLName(),
                          'inputs': connections(proxy, pxm), 'filter': master.nodes[node]['filter'],
                          'properties': read_properties(proxy, handback.property_specs(master, node))}
    observations = {node: observe(active.handles[node]) for node in order}
    manifest = {'version': handback.VERSION, 'state': handback.STATE, 'stateSha256': _hash(state_path),
                'savedBundle': str(bundle.resolve()), 'scene': scene['id'], 'time': visit['time'],
                'viewTime': float(view.ViewTime), 'members': members, 'pipeline': pipeline,
                'observations': observations, 'appearance': appearance, 'presentation': colours,
                'camera': image['camera'], 'viewSize': image['dimensions'][:2], 'runtimeIdentity': runtime,
                'processId': os.getpid(),
                'pathStrategy': 'reader paths are absolute paths inside the saved bundle; load with ParaView '
                                'data-directory search rooted at the bundle data/ folder',
                'openInParaView': handback.GUI_STEPS, 'units': 'unknown', 'frame': 'unknown',
                'losses': handback.LOSSES, 'scope': handback.SCOPE, 'proofScope': handback.PROOF_SCOPE}
    atomic_json(bundle / handback.MANIFEST, manifest)
    handback.check_bundle(bundle)
    for member in members:
        if _source_digest(member['origin'], member['bytes'], member['node']) != member['sha256']:
            fail('INPUT_CHANGED', 'reader input changed after it was bundled', member['origin'])
    captured = [{key: member[key] for key in ('node', 'resource', 'resourceSha256', 'resourceDigest', 'path',
                                              'sha256', 'bytes')} for member in members]
    return {'kind': 'state-bundle', 'file': str(state_path), 'sha256': manifest['stateSha256'], 'verified': True,
            'manifestSha256': _hash(bundle / handback.MANIFEST),
            # Captured trees are pinned by the manifest, not listed here, so no
            # publication companion is ever written inside a captured resource.
            'files': [{'path': handback.MANIFEST, 'file': str(bundle / handback.MANIFEST),
                       'sha256': _hash(bundle / handback.MANIFEST)}],
            'capturedInputs': captured,
            'verificationScope': 'captured reader inputs verified before and after the image, saved state paths, '
                                 'pipeline membership and declared property readback; success also requires '
                                 'independent relocated reload evidence (' + bundle.name + '.reload.json): '
                                 + handback.PROOF_SCOPE,
            'units': 'unknown', 'frame': 'unknown', 'losses': handback.LOSSES, 'openInParaView': handback.GUI_STEPS}


def reload_bundle(relocated, original, proof_path, manifest_digest=None):
    """Internal fresh-process check of this run's relocated bundle; never authored input.

    ``manifest_digest`` is the host's pinned receipt digest; the copy must match
    it before ParaView is imported or the state is loaded.
    """
    relocated, original = Path(relocated), Path(original)
    proof = {'version': handback.RELOAD_VERSION, 'status': 'incomplete', 'verified': False,
             'relocatedBundle': str(relocated), 'processId': os.getpid(),
             'withheld': {'path': str(original), 'absentDuringReload': not os.path.lexists(original)}}
    atomic_json(proof_path, proof)
    try:
        if not proof['withheld']['absentDuringReload']:
            fail('VERIFICATION_FAILED', 'the original bundle must be withheld during reload', str(original))
        digest = handback._string(manifest_digest, 'manifestSha256', handback._HEX)
        manifest = handback.check_bundle(relocated, digest)
        proof.update(manifestSha256=digest, stateSha256=_hash(relocated / handback.STATE))
        from paraview import simple, servermanager
        from .native_run import runtime_identity
        proof['runtimeIdentity'] = runtime_identity()
        # Like the GUI, keep the saved camera; pvbatch otherwise resets it on first render.
        simple._DisableFirstRenderCameraReset()
        data = relocated / handback.DATA
        simple.LoadState(str(relocated / handback.STATE), data_directory=str(data),
                         restrict_to_data_directory=True)
        proof['loadOptions'] = {'dataDirectory': str(data), 'restrictToDataDirectory': True}
        pxm = servermanager.ProxyManager()
        sources = {}
        for (registration, _), proxy in simple.GetSources().items():
            node = identity(proxy.SMProxy, pxm)
            if node in sources:
                fail('VERIFICATION_FAILED', 'reloaded state has duplicate node identities', node)
            sources[node] = proxy
        pipeline, observations = {}, {}
        for name, proxy in sources.items():
            saved = manifest['pipeline'].get(name)
            pipeline[name] = {'xmlName': proxy.SMProxy.GetXMLName(), 'inputs': connections(proxy, pxm),
                              'fileProperties': file_properties(proxy.SMProxy),
                              'properties': read_properties(proxy, saved['properties']) if saved else None,
                              'registrationName': pxm.GetProxyName('sources', proxy.SMProxy)}
        for name in manifest['pipeline']:
            if name in sources:
                sources[name].UpdatePipeline(manifest['time'])
                observations[name] = observe(sources[name])
        views = simple.GetRenderViews()
        if len(views) != 1:
            fail('VERIFICATION_FAILED', 'reloaded state must contain exactly one render view', views=len(views))
        view = views[0]
        appearance, colours = {}, {}
        for name in manifest['appearance']:
            representation = servermanager.GetRepresentation(sources[name], view) if name in sources else None
            if representation is None or not representation.Visibility:
                fail('VERIFICATION_FAILED', 'reloaded scene lacks a visible display', name)
            appearance[name] = display(representation)
            if name in manifest['presentation']:
                colours[name] = presentation(simple, representation, view,
                                             'legendTitle' in manifest['presentation'][name])
        simple.Render(view)
        proof.update(pipeline=pipeline, observations=observations, appearance=appearance, presentation=colours,
                     camera=camera(view), viewSize=[int(v) for v in view.ViewSize], viewTime=float(view.ViewTime))
        if Path(manifest['savedBundle']) != original:
            fail('VERIFICATION_FAILED', 'withheld bundle is not the saved bundle', str(original))
        handback.verify_reload({**proof, 'status': 'succeeded', 'verified': True}, manifest, digest)
        proof.update(status='succeeded', verified=True)
    except Exception as error:
        proof.update(status='failed', verified=False,
                     fault=error.fault.to_dict() if isinstance(error, SchemaxisError)
                     else {'code': 'NATIVE_EXECUTION_FAILED', 'message': f'{type(error).__name__}: {error}'})
        raise
    finally:
        atomic_json(proof_path, proof)
