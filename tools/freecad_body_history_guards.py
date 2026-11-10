"""Refreshed whole-source/copy attacks on a qualifier-owned pure Body packet.

The caller must provide a newly generated qualification assembly, never a user
project. Every mutation and publication update is restored in the final block.
"""
import copy
import json
import re
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as E
from zipfile import ZipFile, ZIP_DEFLATED
from schemaxis.adaptors import registry
from schemaxis.adaptors.freecad import assembly
from schemaxis.adaptors.freecad.process import SubprocessRunner
from schemaxis.adaptor_delivery import source_digest
from schemaxis.artifacts import atomic_json, file_digest
from schemaxis.configuration import location_context
from schemaxis.core.faults import SchemaxisError
from schemaxis.publication_metadata import finalise

def qualify_guards(target, out, locations):
    target = Path(target)
    out = Path(out)
    out.mkdir()
    source = target / 'sources/source0.FCStd'
    pin = source_digest('freecad')
    report = {'verified': False, 'sourceDigest': pin, 'recipeSha256': file_digest(Path(__file__)), 'attacks': {}, 'opens': {}}
    log = out / 'native-opens.jsonl'
    files = {p: p.read_bytes() for p in target.iterdir() if p.is_file()}
    files[source] = source.read_bytes()
    original_plan = json.loads(files[target / 'plan.json'])
    authored = json.loads(files[target / 'authored.json'])
    original_sources = json.loads(files[target / 'sources.json'])
    with ZipFile(source) as archive:
        original_members = {n: archive.read(n) for n in archive.namelist()}

    def restore():
        for p, data in files.items():
            p.write_bytes(data)

    def archive(members):
        with ZipFile(source, 'w', ZIP_DEFLATED) as archive:
            for name, data in members.items():
                archive.writestr(name, data)

    def refreshed(p):
        p['parts'][0]['source']['sha256'] = file_digest(source)
        p['parts'][0]['source']['bytes'] = source.stat().st_size
        with ZipFile(source) as checked:
            p['parts'][0]['source']['expandedBytes'] = sum((checked.getinfo(n).file_size for n in checked.namelist()))
        atomic_json(target / 'plan.json', p)
        records = copy.deepcopy(original_sources)
        records['parametered']['sha256'] = p['parts'][0]['source']['sha256']
        atomic_json(target / 'sources.json', records)
        finalise(target)

    def audit(self, code):
        before = 'import FreeCAD as _audit_app,json as _audit_json,os as _audit_os\nfrom pathlib import Path as _audit_Path\n_audit_original=_audit_app.openDocument\ndef _audit_open(*args,**kwargs):\n name=str(args[0] if args else kwargs.get("FileName",""))\n with open(' + repr(str(log)) + ',"a") as stream:stream.write(_audit_json.dumps({"path":name,"pid":_audit_os.getpid()})+"\\n")\n return _audit_original(*args,**kwargs)\n_audit_app.openDocument=_audit_open\n'
        return original_call(self, before + code)

    def count_source_opens():
        values = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [v for v in values if Path(v['path']).parent.name == 'sources' and re.fullmatch('source[0-9]+\\.FCStd', Path(v['path']).name)]

    def verify(label, reject):
        log.unlink(missing_ok=True)
        try:
            result = registry.verify(target)
        except SchemaxisError as error:
            assert reject, (label, error.fault)
            assert error.fault.code == 'VERIFICATION_FAILED', error.fault
            assert 'metadata' not in error.fault.message.lower() and error.fault.code != 'INVALID_SCHEMA_SNAPSHOT', error.fault
            report['attacks'][label] = error.fault.to_dict()
        else:
            assert not reject, label + ' unsafe public acceptance'
            assert result['verified']
        opens = count_source_opens()
        report['opens'][label] = opens
        if reject:
            assert not opens, (label, opens)
        else:
            assert opens, 'Native source-open observation lacked its positive control'
        if log.exists():
            (out / (label + '-opens.jsonl')).write_bytes(log.read_bytes())
        atomic_json(out / 'report.json', report)
    original_call = SubprocessRunner.__call__
    try:
        with location_context(locations), patch.object(SubprocessRunner, '__call__', audit):
            verify('unchanged', False)
            for label in ('payload', 'postfix', 'unused-SID', 'foreign-proxy', 'FileIncluded', 'local-volume', 'extra-member'):
                restore()
                p = copy.deepcopy(original_plan)
                facts = p['parts'][0]['source']
                members = copy.deepcopy(original_members)
                if label == 'local-volume':
                    facts['volume'] += 0.25
                    p = assembly._native_plan(authored, source_facts={'parametered': facts})
                elif label in ('foreign-proxy', 'FileIncluded'):
                    root = E.fromstring(members['Document.xml'])
                    if label == 'foreign-proxy':
                        root.find('./Objects/Object').set('type', 'App::FeaturePython')
                    else:
                        props = root.find('./ObjectData/Object/Properties')
                        props.set('Count', str(int(props.get('Count')) + 1))
                        prop = E.SubElement(props, 'Property', name='SourceAsset', type='App::PropertyFileIncluded', group='Schemaxis', doc='', attr='0', ro='0', hide='0', status='2097152')
                        E.SubElement(prop, 'FileIncluded', file='foreign.stl')
                        members['foreign.stl'] = b'foreign'
                    old = original_members['Document.xml']
                    start = old.index(b'<Document ')
                    members['Document.xml'] = old[:start] + E.tostring(root, encoding='utf-8')
                elif label == 'payload':
                    name = next((n for n in members if n.endswith('.brp')))
                    data = members[name]
                    match = next((m for m in re.finditer(b'-?\\d+\\.\\d+(?:e[+-]?\\d+)?', data) if float(m.group()) != 0))
                    members[name] = data[:match.start()] + b'0.125' + data[match.end():]
                elif label == 'postfix':
                    name = next((n for n in members if n.endswith('.Map.txt')))
                    lines = members[name].split(b'\n')
                    match = re.fullmatch(b'(\\d+) PostfixCount (\\d+)', lines[1])
                    assert match
                    count = int(match[2])
                    lines[1] = match[1] + b' PostfixCount ' + str(count + 1).encode()
                    lines.insert(2 + count, b'bridge_unused')
                    members[name] = b'\n'.join(lines)
                elif label == 'unused-SID':
                    name = next((n for n in members if b'StringTableStart v1 ' in members[n][:100]))
                    data = members[name]
                    match = re.match(b'StringTableStart v1 (\\d+)\\n', data)
                    assert match
                    members[name] = b'StringTableStart v1 ' + str(int(match[1]) + 1).encode() + b'\n' + data[match.end():] + b'-1.0 0:bridge_unused\n'
                elif label == 'extra-member':
                    members['unreferenced.stl'] = b'unreferenced'
                if members != original_members:
                    archive(members)
                refreshed(p)
                (out / (label + '-source.FCStd')).write_bytes(source.read_bytes())
                atomic_json(out / (label + '-plan.json'), p)
                verify(label, True)
            restore()
            verify('restored', False)
            native = target / 'model.FCStd'
            with ZipFile(native) as z:
                copied_members = {n: z.read(n) for n in z.namelist()}
            for label in ('copy-postfix', 'copy-postfix-swap', 'copy-BREP'):
                restore()
                changed = copy.deepcopy(copied_members)
                if label == 'copy-postfix':
                    name = next((n for n in changed if n.endswith('.Map.txt')))
                    lines = changed[name].split(b'\n')
                    m = re.fullmatch(b'(\\d+) PostfixCount (\\d+)', lines[1])
                    assert m
                    count = int(m[2])
                    lines[1] = m[1] + b' PostfixCount ' + str(count + 1).encode()
                    lines.insert(2 + count, b'copied_unused')
                    changed[name] = b'\n'.join(lines)
                elif label == 'copy-postfix-swap':
                    from schemaxis.adaptors.freecad.history_element_maps import archive_maps
                    root = E.fromstring(changed['Document.xml'])
                    expected = archive_maps(changed, root)
                    found = False
                    for name in sorted((n for n in changed if n.endswith('.Map.txt'))):
                        original = changed[name]
                        lines = original.split(b'\n')
                        m = re.fullmatch(b'(\\d+) PostfixCount (\\d+)', lines[1])
                        assert m
                        count = int(m[2])
                        for i in range(min(count, 8)):
                            for j in range(i + 1, min(count, 8)):
                                if lines[2 + i] == lines[2 + j]:
                                    continue
                                mixed = lines[:]
                                mixed[2 + i], mixed[2 + j] = (mixed[2 + j], mixed[2 + i])
                                changed[name] = b'\n'.join(mixed)
                                try:
                                    different = archive_maps(changed, root) != expected
                                except ValueError:
                                    different = False
                                if different:
                                    found = True
                                    break
                            if found:
                                break
                        if found:
                            break
                        changed[name] = original
                    assert found, 'No well-formed semantic postfix swap found'
                else:
                    name = next((n for n in changed if n.endswith('.brp') and changed[n]))
                    data = changed[name]
                    m = next((m for m in re.finditer(b'-?\\d+\\.\\d+(?:e[+-]?\\d+)?', data) if float(m.group()) != 0))
                    changed[name] = data[:m.start()] + b'0.125' + data[m.end():]
                with ZipFile(native, 'w', ZIP_DEFLATED) as z:
                    for n, data in changed.items():
                        z.writestr(n, data)
                receipt = json.loads(files[target / 'verification.json'])
                receipt['artifact']['sha256'] = file_digest(native)
                receipt['artifacts'] = [receipt['artifact']]
                atomic_json(target / 'verification.json', receipt)
                finalise(target)
                log.unlink(missing_ok=True)
                try:
                    registry.verify(target)
                except SchemaxisError as error:
                    assert error.fault.code == 'VERIFICATION_FAILED', error.fault
                    assert 'metadata' not in error.fault.message.lower()
                    report['attacks'][label] = error.fault.to_dict()
                else:
                    raise AssertionError(label + ' accepted')
                opened = [json.loads(line)['path'] for line in log.read_text().splitlines()] if log.exists() else []
                assert str(native) not in opened
                report['opens'][label] = {'submittedAssemblyOpens': 0, 'trustedSourceOpens': len(opened)}
                (out / (label + '-model.FCStd')).write_bytes(native.read_bytes())
                atomic_json(out / (label + '-verification.json'), receipt)
                atomic_json(out / 'report.json', report)
            restore()
            verify('final-restored', False)
        assert source_digest('freecad') == pin
        report['verified'] = True
    finally:
        restore()
        atomic_json(out / 'report.json', report)
    return report
