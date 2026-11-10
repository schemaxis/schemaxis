"""Load explicit operator configuration for isolated local MCP execution.

There are no default image permissions. Configuration is outside authored tool
arguments, and every profile requires an immutable image and qualification ID.
"""
from dataclasses import fields
import os
from pathlib import Path
import stat

from .container_executor import ContainerExecutor, ImageResolver, IsolationLimits, IsolationProfile
from .execution_inputs import CapturePolicy
from .mcp_admission import FileAdmission
from .mcp_inputs import LocalInputs, _regular, normalise_digest
from .storage import load


def configured_executor(filename):
    path = Path(filename).expanduser().absolute()
    fd, info = _regular(path)
    with os.fdopen(fd, 'rb') as stream:
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022 or info.st_size > 1024*1024:
            raise ValueError('Isolation configuration must be owned, bounded and not group/world writable')
        config = load(stream.read(1024*1024+1).decode())
    if (type(config) is not dict or set(config) != {'version', 'profiles', 'captures', 'inputs'}
            or type(config['version']) is not int or config['version'] != 1
            or type(config['profiles']) is not list or not 1 <= len(config['profiles']) <= 64
            or type(config['inputs']) is not list or len(config['inputs']) > 64):
        raise ValueError('Invalid operator isolation configuration')
    capture = config['captures']
    if type(capture) is not dict or set(capture) != {'root', 'namespace', 'max_bytes', 'max_files'}:
        raise ValueError('Explicit private capture policy required')
    policy = CapturePolicy(Path(capture['root']), capture['namespace'], capture['max_bytes'], capture['max_files'])
    profiles = []
    for item in config['profiles']:
        required = {'image', 'providers', 'routes', 'limits', 'qualification_id', 'capabilities'}
        if (type(item) is not dict or set(item) != required
                or type(item['providers']) is not list or type(item['routes']) is not list
                or type(item['capabilities']) is not list or type(item['limits']) is not dict
                or set(item['limits']) != {field.name for field in fields(IsolationLimits)}
                or not item['qualification_id'] or item['qualification_id'] in ('unqualified', 'fixture-only')):
            raise ValueError('Each image needs explicit qualified routes and complete resource limits')
        profiles.append(IsolationProfile(item['image'], tuple(item['providers']), tuple(item['routes']),
            IsolationLimits(**item['limits']), item['qualification_id'], tuple(item['capabilities'])))
    # Reject ambiguous profile sets before constructing the service.
    keys = [(tuple(sorted(p.providers)), tuple(sorted(p.routes))) for p in profiles]
    if len(keys) != len(set(keys)):
        raise ValueError('More than one image claims the same provider/route set')
    inputs = LocalInputs(policy)
    for item in config['inputs']:
        if (type(item) is not dict or set(item) != {'id', 'source', 'label', 'sha256'}
                or type(item['source']) is not str or type(item['sha256']) is not str):
            raise ValueError('Operator input requires an identity, source, label and digest')
        expected_digest = normalise_digest(item['sha256'])
        if item['id'] in inputs.index['items']:
            retained = inputs.index['items'][item['id']]
            if retained['sha256'] != expected_digest or retained['label'] != item['label']:
                raise ValueError('Retained input differs from startup configuration; select a fresh ID')
        else:
            inputs.import_source(Path(item['source']), identity=item['id'], label=item['label'], expected_digest=expected_digest)
    executor = ContainerExecutor(ImageResolver(profiles), admission=FileAdmission(), capture_policy=policy)
    return executor, inputs
