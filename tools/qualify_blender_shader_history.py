"""Discriminate historical receipt compatibility without rewriting old evidence."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from schemaxis.adaptors.blender.adaptor import run, _verify
from schemaxis.artifacts import runtime_archive
from schemaxis.assessments import source_fingerprint
from schemaxis.configuration import location_context
from schemaxis.errors import SchemaxisError


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blender', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--packet', type=Path, action='append', required=True)
    parser.add_argument('--mesh-packet', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.absolute(); out.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(args.manifest.read_text())
    report = {'status':'running', 'providerCommit':subprocess.check_output(
        ['git','rev-parse','HEAD'], text=True).strip(),
        'sourceFingerprint':source_fingerprint('blender'),
        'runtimeArchiveSha256':hashlib.sha256(runtime_archive()).hexdigest(),
        'historicalManifest':str(args.manifest), 'historicalManifestSha256':digest(args.manifest),
        'historicalProviderCommit':manifest['providerCommit'],
        'historicalSourceFingerprint':manifest['sourceFingerprint'],
        'historicalRuntimeArchiveSha256':manifest['runtimeArchiveSha256'], 'checks':[]}
    def write():
        (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    try:
        for packet in args.packet:
            packet = packet.absolute()
            records = [r for r in manifest['records']
                       if r['original'].startswith(str(packet)+'/')]
            assert records, ('packet absent from historical manifest', packet)
            before = {r['original']:digest(Path(r['original'])) for r in records}
            assert all(before[r['original']]==r['sha256'] for r in records), packet
            fault = None
            with location_context({'blender':args.blender}):
                try: _verify(packet)
                except SchemaxisError as exc: fault = exc.fault.to_dict()
            assert before=={path:digest(Path(path)) for path in before}, packet
            report['checks'].append({'packet':str(packet), 'retainedFilesRehashed':len(records),
                'originalBytesUnchanged':True, 'currentVerifierAccepted':fault is None,
                'fault':fault, 'migrationRequired':fault is not None})
            write(); print('historical '+packet.name, flush=True)
        old = json.loads((args.mesh_packet/'reopened.json').read_text())
        expected = [p['meshEditBaselines'] for p in old['production']]
        assert expected and any(expected), 'historical fixture must exercise source baselines'
        current = out/'mesh-baseline-current'
        run(json.loads((args.mesh_packet/'authored.json').read_text()), current,
            executable=args.blender, timeout=240)
        with location_context({'blender':args.blender}): assert _verify(current)['verified']
        actual = json.loads((current/'reopened.json').read_text())
        assert [p['meshEditBaselines'] for p in actual['production']]==expected
        report['meshEditBaseline'] = {'historicalPacket':str(args.mesh_packet),
            'currentPacket':str(current), 'sourceBaselinesExactlyEqual':True,
            'currentPublicVerify':True}
        assert source_fingerprint('blender')==report['sourceFingerprint']
        assert hashlib.sha256(runtime_archive()).hexdigest()==report['runtimeArchiveSha256']
        report['status'] = ('migration-required' if any(c['migrationRequired'] for c in report['checks'])
                            else 'compatible')
    finally:
        if report['status']=='running': report['status']='failed'
        write()


if __name__=='__main__': main()
