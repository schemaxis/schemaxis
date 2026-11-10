"""Observed native runtime identity against declared compatibility profiles.

Five identities stay separate: the Schemaxis core package version, the adaptor
implementation revision (its conservative source digest), the authored schema
route, the native application's self-reported version/build/platform, and the
adaptor's compatibility profile and qualification. Profiles live in the
adaptor's ``upstream.json`` beside ``absorbedVersion``. They list exact observed
releases only; a profile match never upgrades qualification, and selection
never imports or starts an application.
"""
import copy
import json
import re

from .errors import fail

PROTOCOL = 'schemaxis.compatibility/1'
PROFILE_STATUSES = ('observed', 'unsupported')
PROFILE_KEYS = {'id', 'status', 'versions', 'routes', 'modes', 'evidence', 'scope', 'reason'}
IDENTITY_KEYS = {'application', 'version', 'build', 'platform', 'source', 'fault'}
PLATFORM_KEYS = {'system', 'machine', 'python'}
SUPPLIED = 'supplied'
VERSION_CHECK = ('coversObservedVersion compares release numbers only: it is true when the assessed release '
                 'equals a runtime version recorded in the receipt. It establishes no platform, build or plugin '
                 'equivalence and no coverage of other operations; profile matching never changes this status.')
_RELEASE = re.compile(r'\d+(?:\.\d+){1,3}')
_SLUG = re.compile(r'[a-z0-9][a-z0-9.-]*')


def _invalid(message, location, **observed):
    fail('INVALID_COMPATIBILITY_PROFILE', message, location, **observed)


def _strings(value, location, name):
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
        _invalid(name + ' must be a list of nonempty strings', location)
    if len(set(value)) != len(value):
        _invalid(name + ' must not repeat entries', location)
    return list(value)


def validate(policy, manifest):
    """Return validated profiles, or None when the adaptor declares no profiles.

    Profiles are matched by exact (route, release) pairs. Any pair claimed by two
    profiles is ambiguous and rejected rather than resolved by order.
    """
    section = policy.get('compatibility') if isinstance(policy, dict) else None
    if section is None:
        return None
    location = 'upstream.json/compatibility'
    if not isinstance(section, dict) or set(section) != {'protocol', 'profiles'} or section['protocol'] != PROTOCOL:
        _invalid('compatibility needs exactly protocol ' + PROTOCOL + ' and profiles', location)
    profiles = section['profiles']
    if not isinstance(profiles, list) or not profiles:
        _invalid('profiles must be a nonempty list', location)
    routes = declared_routes(manifest)
    modes = set(manifest.get('executionCapabilities', {}).get('modes', ['serial']))
    claimed, ids, result = {}, set(), []
    for index, profile in enumerate(profiles):
        where = location + '/profiles/' + str(index)
        if not isinstance(profile, dict):
            _invalid('profile must be an object', where)
        unknown = set(profile) - PROFILE_KEYS
        if unknown:
            _invalid('profile has unsupported keys', where, keys=sorted(unknown))
        if not isinstance(profile.get('id'), str) or not _SLUG.fullmatch(profile['id']) or profile['id'] in ids:
            _invalid('profiles need distinct lowercase slug IDs', where)
        ids.add(profile['id'])
        if profile.get('status') not in PROFILE_STATUSES:
            _invalid('status must be one of ' + ', '.join(PROFILE_STATUSES), where)
        versions = _strings(profile.get('versions'), where, 'versions')
        bad = [v for v in versions if not _RELEASE.fullmatch(v)]
        if bad:
            # Ranges and wildcards would claim releases nobody has observed.
            _invalid('versions must be exact numeric releases', where, versions=bad)
        profile_routes = _strings(profile.get('routes'), where, 'routes')
        if set(profile_routes) - routes:
            _invalid('routes must be declared by the adaptor', where, routes=sorted(set(profile_routes) - routes))
        if not isinstance(profile.get('scope'), str) or not profile['scope'].strip():
            _invalid('profile needs a scope statement', where)
        if profile['status'] == 'observed':
            _strings(profile.get('evidence'), where, 'evidence')
            profile_modes = _strings(profile.get('modes'), where, 'modes')
            if set(profile_modes) - modes:
                _invalid('modes must be execution modes the adaptor declares', where,
                         modes=sorted(set(profile_modes) - modes))
            if 'reason' in profile:
                _invalid('reason belongs to unsupported profiles', where)
        else:
            if not isinstance(profile.get('reason'), str) or not profile['reason'].strip():
                _invalid('unsupported profiles need a reason', where)
            if 'modes' in profile:
                _invalid('unsupported profiles cannot declare modes', where)
        for route in profile_routes:
            for version in versions:
                if (route, version) in claimed:
                    fail('AMBIGUOUS_COMPATIBILITY_PROFILE', 'two profiles claim the same route and release', where,
                         route=route, version=version, profiles=[claimed[(route, version)], profile['id']])
                claimed[(route, version)] = profile['id']
    absorbed = policy.get('absorbedVersion')
    if absorbed is not None:
        statuses = {profile['id']: profile['status'] for profile in profiles}
        uncovered = sorted(route for route in routes
                           if statuses.get(claimed.get((route, absorbed))) != 'observed')
        if uncovered:
            _invalid('absorbedVersion must be covered by an observed profile for every route',
                     location, absorbedVersion=absorbed, routes=uncovered)
    return copy.deepcopy(profiles)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def declared_routes(manifest):
    """Routes an adaptor manifest owns; legacy manifests declare only their ``version``."""
    return set(manifest.get('routes', {})) or {manifest.get('version')}


def check_route(provider, route):
    """Reject a route the requested adaptor does not own before assessing its evidence."""
    from .adaptors import registry
    routes = declared_routes(registry.metadata(provider))
    if not isinstance(route, str) or route not in routes:
        fail('UNSUPPORTED_VERSION', 'route is not declared by adaptor ' + provider, '$.route',
             provider=provider, route=route if isinstance(route, str) else repr(route), routes=sorted(routes))


def normalise_identity(identity, provider, probed=None, supplied=False):
    """Classify a native self-report as absent, unavailable, invalid or usable.

    Optional fields may be omitted, but when present they must be well typed;
    a malformed fault is invalid rather than unavailable. ``supplied`` marks a
    hypothetical candidate, which must say so and cannot pass as a native report.
    """
    if identity is None:
        return 'absent', 'no runtime identity was recorded (for example, an earlier receipt)'
    if not isinstance(identity, dict) or set(identity) - IDENTITY_KEYS:
        return 'invalid', 'runtime identity must be an object with known keys'
    if identity.get('application') != provider:
        return 'invalid', 'runtime identity names a different application'
    for key in ('build', 'source', 'fault'):
        if key in identity and not _text(identity[key]):
            return 'invalid', 'runtime identity ' + key + ' must be a nonempty string'
    platform = identity.get('platform')
    if 'platform' in identity and (not isinstance(platform, dict) or set(platform) - PLATFORM_KEYS
                                   or not all(_text(v) for v in platform.values())):
        return 'invalid', 'runtime identity platform must map ' + ', '.join(sorted(PLATFORM_KEYS)) + \
            ' to nonempty strings'
    if (identity.get('source') == SUPPLIED) != supplied:
        return 'invalid', ('a supplied candidate must have source ' + SUPPLIED if supplied else
                           'a native runtime identity cannot claim source ' + SUPPLIED)
    if 'fault' in identity:
        return 'unavailable', 'the native runtime could not report its identity: ' + identity['fault'][:300]
    version = identity.get('version')
    if not isinstance(version, str) or not _RELEASE.fullmatch(version):
        return 'invalid', 'runtime version is not an exact numeric release'
    if probed is not None and probed != version:
        return 'invalid', 'launcher-reported version ' + str(probed) + ' differs from in-process version ' + version
    return None, None


def select(profiles, identity, *, provider, route, mode='serial', probed=None, declared=None, supplied=False):
    """Pure, host-only selection of at most one profile for an observed or supplied identity."""
    def outcome(status, reason, profile=None, capability='unknown'):
        value = {'status': status, 'reason': reason, 'capability': {'mode': mode, 'status': capability}}
        if profile is not None:
            value.update(profile=profile['id'], scope=profile['scope'])
        return value
    if profiles is None:
        return outcome('undeclared', 'this adaptor declares no compatibility profiles')
    status, reason = normalise_identity(identity, provider, probed, supplied)
    if status:
        return outcome(status, reason)
    version = identity['version']
    matches = [p for p in profiles if version in p['versions'] and route in p['routes']]
    if len(matches) > 1:
        # validate() rejects this; keep selection safe if called with raw data.
        fail('AMBIGUOUS_COMPATIBILITY_PROFILE', 'more than one profile matches', route=route, version=version,
             profiles=[p['id'] for p in matches])
    if not matches:
        return outcome('unqualified', 'no profile declares ' + version + ' for route ' + str(route))
    profile = matches[0]
    if profile['status'] == 'unsupported':
        return outcome('unsupported', profile['reason'], profile, 'unsupported')
    capability = ('observed' if mode in profile['modes'] else
                  'undeclared' if declared is not None and mode not in declared else 'unqualified')
    return outcome('observed', 'the supplied hypothetical candidate release is named by an observed baseline '
                   'profile; no runtime was started or observed' if supplied else
                   'the runtime reported a release named by an observed baseline profile', profile, capability)


def load(provider):
    """Read and validate the adaptor's upstream metadata without importing its runtime."""
    from .adaptors import registry
    manifest = registry.metadata(provider)
    path = registry.adaptor_files(provider).joinpath('upstream.json')
    policy = {}
    if path.is_file():
        try:
            policy = json.loads(path.read_text())
        except ValueError as error:
            _invalid('upstream.json is not valid JSON: ' + str(error)[:200], 'upstream.json')
        if not isinstance(policy, dict):
            _invalid('upstream.json must be an object', 'upstream.json')
    return policy, manifest, validate(policy, manifest)


def _core_version():
    try:
        from .__main__ import project_version
        return project_version()
    except ValueError:
        return None


def _recorded_versions(receipt):
    """Structured ``runtime.version`` strings only; legacy free-text runtimes are never parsed."""
    cases = receipt.get('cases') if isinstance(receipt, dict) else None
    runtimes = (case.get('runtime') for case in cases if isinstance(case, dict)) if isinstance(cases, list) else ()
    return {runtime['version'] for runtime in runtimes if isinstance(runtime, dict) and _text(runtime.get('version'))}


def _qualification(route, version):
    from .adaptor_delivery import qualification_status
    from .core.faults import SchemaxisError
    try:
        status = qualification_status(route)
    except SchemaxisError as error:
        return {'status': 'unknown', 'reason': error.fault.message, 'coversObservedVersion': None,
                'versionCheck': VERSION_CHECK}
    receipt = status.get('receipt') or {}
    recorded = sorted(_recorded_versions(receipt))
    # Status, reason and receipt scope pass through unchanged from qualification_status.
    report = {key: status[key] for key in ('status', 'reason', 'scope') if key in status}
    report.update(runtimeVersions=recorded, versionCheck=VERSION_CHECK,
                  coversObservedVersion=(version in recorded) if version and recorded else None)
    return report


def assess(provider, identity, *, route, mode='serial', probed=None, qualification=True, supplied=False):
    """Report every identity layer and the selected profile for one observation.

    With ``supplied`` the identity is a hypothetical candidate (for example
    ``--app-version``): it is reported as ``candidate``, ``observed`` stays None
    and ``identitySource`` says no runtime was observed.
    """
    from .adaptor_delivery import source_digest
    check_route(provider, route)
    policy, manifest, profiles = load(provider)
    declared = manifest.get('executionCapabilities', {}).get('modes', ['serial'])
    selection = select(profiles, identity, provider=provider, route=route, mode=mode, probed=probed,
                       declared=declared, supplied=supplied)
    usable = selection['status'] in ('unqualified', 'unsupported', 'observed')
    report = {
        'protocol': PROTOCOL,
        'core': {'package': _core_version()},
        'adaptor': {'id': provider, 'revision': source_digest(provider),
                    'runtimeFamily': manifest.get('runtimeFamily'), 'absorbedVersion': policy.get('absorbedVersion')},
        'route': route,
        'identitySource': None if identity is None else SUPPLIED if supplied else 'native-self-report',
        'observed': None if supplied else copy.deepcopy(identity) if isinstance(identity, dict) else identity,
        'profile': selection,
        'scope': 'A profile match records that this release was observed in cited evidence; it does not '
                 'qualify current source, untested operations or other modes. ' +
                 ('The candidate was supplied as a hypothesis; no runtime was started or observed.' if supplied
                  else 'Identity is self-reported by the native runtime.'),
    }
    if supplied:
        report['candidate'] = copy.deepcopy(identity)
    if probed is not None:
        report['launcherVersion'] = probed
    if qualification:
        report['qualification'] = _qualification(route, identity['version'] if usable else None)
    return report
