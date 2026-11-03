# Copyright (C) 2026 David L F Gaden
"""Application-specific console policy; session persistence stays in the framework."""
import copy
from schemaxis.errors import fail
from .adaptor import plan


def live_location(session):
    """Choose the GUI launcher without replacing the configured batch executable."""
    import os
    from pathlib import Path
    from schemaxis.configuration import locations
    configured = locations().get('freecad_gui')
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            fail('INTERPRETER_NOT_FOUND', 'configured FreeCAD GUI launcher is not executable', 'freecad_gui')
        return str(candidate.resolve())
    executable = Path(session.executable)
    if 'cmd' in executable.name.lower():
        for name in ('freecad', 'FreeCAD'):
            candidate = executable.with_name(name)
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.absolute())
        fail('INTERPRETER_NOT_FOUND', 'configure freecad_gui for live Preview, or use Run for batch execution',
             'freecad_gui')
    return session.executable


def validate(document, draft=True):
    return plan(document, allow_profile=True)


def add(document, identity, operation, renderable):
    document['output'] = identity


def show(document, identity, renderable):
    document['output'] = identity


def live_save(session, target, applied, geometry, document):
    import hashlib
    import zipfile
    from xml.etree import ElementTree
    session._live_call('save', path=str(target / 'model.FCStd'))
    path = target / 'model.FCStd'
    if not path.is_file() or path.is_symlink(): fail('NO_NATIVE_DOCUMENT', 'live save produced no native document')
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo('Document.xml')
            if info.file_size > 32 * 1024 * 1024 or archive.namelist().count('Document.xml') != 1:
                fail('VERIFICATION_FAILED', 'FCStd Document.xml exceeds limits or is duplicated')
            root = ElementTree.fromstring(archive.read(info))
            if root.tag != 'Document': fail('VERIFICATION_FAILED', 'FCStd Document.xml has an unexpected root')
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        fail('VERIFICATION_FAILED', 'live FCStd container is invalid', detail=str(error))
    artifacts = [{'file': str(path), 'kind': 'cadScene', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
    native_save = {'file': str(path), 'sha256': artifacts[0]['sha256'],
        'verificationScope': 'nativeLiveSnapshot', 'independentReopen': False,
        'checks': ['owned client save', 'ZIP Document.xml CRC and XML structure', 'retained artifact digest'],
        'limitations': 'Container checks do not independently verify saved native geometry or reopening.'}
    from schemaxis.publication_metadata import publish_artifacts
    publish_artifacts(path.parent, artifacts)
    return artifacts, native_save


def model(session, operation, *args):
    session._graph_required()
    identity, *values = args
    if operation == 'extrude':
        profile, length = values
        return session.add(identity, 'extrude', {'length': session._number(length)}, {'profile': profile})
    fields = {'box': ('length', 'width', 'height'), 'rectangle': ('width', 'height'), 'circle': ('radius',)}
    return session.add(identity, operation, dict(zip(fields[operation], map(session._number, values))))


def command(session, command, args, line):
    import re
    import uuid
    if command == 'box' and len(args) == 4: return model(session, 'box', *args)
    if command in ('rectangle', 'rect') and len(args) == 3: return model(session, 'rectangle', *args)
    if command == 'circle' and len(args) == 2: return model(session, 'circle', *args)
    if command == 'extrude':
        if args and args[-1] == 'mm': args.pop()
        if len(args) == 2: return model(session, 'extrude', args[0], session.selected, args[1])
        if len(args) == 3: return model(session, 'extrude', *args)
    match = re.fullmatch(r'(?:draw|create|make) (?:a )?rectangle (\d+(?:\.\d+)?) (?:x|by) (\d+(?:\.\d+)?) mm(?: centred on the origin)?', line.strip(), re.I)
    if match: return model(session, 'rectangle', 'sketch' + uuid.uuid4().hex[:8], *match.groups())
