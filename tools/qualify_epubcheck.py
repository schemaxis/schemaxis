#!/usr/bin/env python3
"""Bounded native acceptance of the EPUBCheck adaptor with the official EPUBCheck 5.4 distribution.

The launcher given with --epubcheck is wrapped by a logging shell script (PID, argv, CPU affinity, resource limits and the Java-related and locale
environment are recorded before it execs the real launcher, so the PID is the native Java process) and every probe is a real process. The parent
environment is deliberately poisoned with conflicting JAVA_TOOL_OPTIONS, JDK_JAVA_OPTIONS and _JAVA_OPTIONS values, so the logged native environment shows
that only the fixed offline property reaches the checker. Covered: the independently designed valid,
rich, invalid-package, missing-image, warning and remote-image fixtures with their expected message identifiers, real Pandoc-generated transcript
EPUBs when given, forged retained assessments with refreshed hashes, swapped captures, missing launcher, host refusals that must never start native
code, loopback network canaries (remote resource references, and direct unknown-EPUB-2-DTD controls with and without the fixed offline property),
in-flight timeout and cancellation with no surviving process, and a Pandoc -> EPUBCheck workflow (index 3) when a
Pandoc executable is given. Hardware and the qualifier's own CPU affinity are recorded separately from the affinity cap observed in native processes.
It never registers a qualification receipt and is not a reading-system, accessibility or legal check.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests/unit'))
import epubcheck_fixture as fixture  # noqa: E402
from epubcheck_loopback import Loopback  # noqa: E402
from schemaxis import workflow  # noqa: E402
from schemaxis.adaptor_conformance import qualify  # noqa: E402
from schemaxis.adaptors.epubcheck import adaptor  # noqa: E402
from schemaxis.artifacts import atomic_json  # noqa: E402
from schemaxis.configuration import location_context  # noqa: E402
from schemaxis.core.faults import SchemaxisError  # noqa: E402
from schemaxis.dispatch import allocation  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROCESSES = []
POISON = {'JAVA_TOOL_OPTIONS': '-Depubcheck.offline=false', 'JDK_JAVA_OPTIONS': '-Depubcheck.offline=false', '_JAVA_OPTIONS': '-Depubcheck.offline=false'}
NATIVE_PLAIN = {'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
NOTICE = 'Picked up JAVA_TOOL_OPTIONS: -Depubcheck.offline=true\n'


def code_of(action):
    try:
        action()
    except SchemaxisError as error:
        return error.fault
    raise AssertionError('expected a fault')


def wrapper(path, real, log, sleep=0):
    """Logging launcher: record this (soon native) PID, arguments, CPUs, limits and environment, optionally sleep, then exec the real launcher."""
    path.write_text('#!/bin/sh\n{ echo "pid=$$"; echo "argv=$*"; grep Cpus_allowed_list /proc/$$/status; grep -iE "^Max (cpu time|file size|open files)" /proc/$$/limits;\n'
                    '  env | grep -E "^(JAVA_TOOL_OPTIONS|JDK_JAVA_OPTIONS|_JAVA_OPTIONS|LANG|LC_ALL)=" | sed "s/^/env:/"; echo "envnames=$(env | cut -d= -f1 | sort | tr "\\n" " ")"; echo "---"; } >> %s\n'
                    '%sexec %s "$@"\n' % (log, 'sleep %s\n' % sleep if sleep else '', real))
    path.chmod(0o755)
    return str(path)


def launches(log):
    """Parsed wrapper log: one dict per native launch with the recorded pid, argv, affinity, limits and environment."""
    entries = []
    for block in log.read_text().split('---\n'):
        if 'pid=' not in block:
            continue
        entry = {'limits': [], 'env': {}}
        for line in block.splitlines():
            if line.startswith('pid='):
                entry['pid'] = int(line[4:])
            elif line.startswith('argv='):
                entry['argv'] = line[5:]
            elif line.startswith('Cpus_allowed_list'):
                entry['cpus'] = line.split(':', 1)[1].strip()
            elif line.startswith('Max '):
                entry['limits'].append(' '.join(line.split()))
            elif line.startswith('env:'):
                key, _, value = line[4:].partition('=')
                entry['env'][key] = value
            elif line.startswith('envnames='):
                entry['envnames'] = line[9:].split()
        entries.append(entry)
    return entries


def affinity_text(cpus):
    """Compact CPU list (for example 0-19) of an affinity set."""
    cpus, runs = sorted(cpus), []
    for cpu in cpus:
        if runs and cpu == runs[-1][1] + 1:
            runs[-1][1] = cpu
        else:
            runs.append([cpu, cpu])
    return ','.join(str(a) if a == b else '%d-%d' % (a, b) for a, b in runs)


def probe(label, argv, expect, timeout=60):
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=NATIVE_PLAIN)
    out, err = process.communicate(timeout=timeout)
    PROCESSES.append({'label': label, 'pid': process.pid, 'argv': [os.path.basename(argv[0]), *[os.path.basename(a) for a in argv[1:]]], 'timeoutSeconds': timeout, 'exitCode': process.returncode})
    assert process.returncode == expect, (label, process.returncode, err[-200:])
    return out


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def refresh(directory):
    receipt = json.loads((directory / 'verification.json').read_text())
    receipt['artifacts'] = adaptor.publications(directory)
    receipt['evidence'] = {name: adaptor.digest(directory, name) for name in receipt['evidence']}
    (directory / 'verification.json').write_text(json.dumps(receipt))


def document(path):
    return {'version': adaptor.VERSION, 'operation': 'validate', 'source': str(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--epubcheck', type=Path, required=True, help='absolute trusted EPUBCheck 5.4 launcher')
    parser.add_argument('--pandoc', type=Path, help='absolute Pandoc 3.12 executable for the workflow smoke (reported unavailable when absent)')
    parser.add_argument('--pandoc-epub', type=Path, action='append', default=[], help='retained Pandoc-generated EPUB to check (repeatable, read only)')
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    real = str(args.epubcheck.absolute())
    log = out / 'native-launches.log'
    launcher = wrapper(out / 'logging-launcher', real, log)
    locations = {'epubcheck': launcher}
    report = {'verified': False, 'acceptancePid': os.getpid(), 'skipped': [],
              'hardware': {'cpuCount': os.cpu_count(), 'qualifierAffinity': affinity_text(os.sched_getaffinity(0)), 'adaptorAffinityCap': adaptor.MAX_CPUS,
                           'note': 'cpuCount and qualifierAffinity describe this machine and process; the cap the adaptor applied to native processes is reported separately under nativeEnvironment'}}
    parent = {key: os.environ.get(key) for key in POISON}
    os.environ.update(POISON)          # conflicting parent values the fixed native environment must not inherit
    try:
        report['runtime'] = probe('version', [real, '--version'], 0).decode().strip()
        work = out / 'work'
        work.mkdir()
        fixtures = {}
        for name, make in {'valid': fixture.valid, 'rich': fixture.rich, 'missing_title': fixture.missing_title, 'missing_image': fixture.missing_image,
                           'bad_date': fixture.bad_date, 'remote_image': fixture.remote_image}.items():
            path = work / (name + '.epub')
            path.write_bytes(make())
            fixtures[name] = path
        # Direct native probes: exit codes of the checker itself, independent of the adaptor.
        direct = {}
        for name, path in fixtures.items():
            output = work / (name + '-direct.json')
            probe('direct-' + name, [real, path.name, '--json', output.name, '--failonwarnings', '--quiet', '--locale', 'en'] if False else
                  [real, str(path), '--json', str(output), '--failonwarnings', '--quiet', '--locale', 'en'], 0 if name in ('valid', 'rich') else 1)
            direct[name] = sorted(m['ID'] for m in json.loads(output.read_text())['messages'])
            expected = fixture.EXPECTED.get(name, {'ids': []})
            assert direct[name] == sorted(expected['ids']), (name, direct[name])
        report['directProbeMessageIds'] = direct
        with location_context(locations):
            receipt = qualify(adaptor.VERSION, out / 'kit', native=True, root=ROOT, locations=locations, timeout=120, wall_timeout=600)
        report['native'] = {'verified': receipt['verified'], 'cases': [c['id'] for c in receipt['cases']], 'runtimes': [c['runtime'] for c in receipt['cases']], 'lifecycle': receipt['lifecycle']}
        with location_context(locations):
            runs = {}
            for name in ('valid', 'rich'):
                directory = out / ('run-' + name)
                result = adaptor.run(document(fixtures[name]), directory, executable=launcher, timeout=120)
                assert result['verified'] and adaptor.verify(directory)['verified']
                runs[name] = {'members': result['source']['members'], 'counts': result['checker']['counts']}
            report['accepted'] = runs
            rejected = {}
            for name in ('missing_title', 'missing_image', 'bad_date', 'remote_image'):
                directory = out / ('reject-' + name)
                fault = code_of(lambda: adaptor.run(document(fixtures[name]), directory, executable=launcher, timeout=120))
                assert fault.code == 'EPUBCHECK_REJECTED'
                found = json.loads((directory / 'rejected-assessment.json').read_text())
                assert sorted(m['ID'] for m in found['messages']) == sorted(fixture.EXPECTED[name]['ids'])
                assert not (directory / 'assessment.json').exists() and not (directory / 'verification.json').exists()
                rejected[name] = {'ids': sorted(m['ID'] for m in found['messages']), 'counts': fault.observed['findings']['counts']}
            report['rejected'] = rejected
            retained = []
            for path in args.pandoc_epub:
                directory = out / ('pandoc-' + str(len(retained)))
                result = adaptor.run(document(path), directory, executable=launcher, timeout=120)
                assert result['verified'] and adaptor.verify(directory)['verified']
                retained.append({'source': path.name, 'sha256': result['source']['sha256'], 'members': result['source']['members'], 'counts': result['checker']['counts']})
            report['pandocEpubs'] = retained or 'unavailable: no --pandoc-epub given'
            # Forged retained evidence with every receipt hash refreshed.
            forged = {}
            for name, change in {
                    'title': lambda r: r['publication'].__setitem__('title', 'Forged'),
                    'counter-and-message': lambda r: (r['messages'].append({'ID': 'RSC-005', 'severity': 'ERROR', 'message': 'x', 'additionalLocations': 0, 'suggestion': None, 'locations': []}),
                                                      r['checker'].__setitem__('nError', 1))[1],
                    'item': lambda r: r['items'][0].__setitem__('checkSum', 'ff'),
                    'bool-count': lambda r: r['checker'].__setitem__('nWarning', False)}.items():
                directory = out / ('forge-' + name)
                adaptor.run(document(fixtures['valid']), directory, executable=launcher, timeout=120)
                value = json.loads((directory / 'assessment.json').read_text())
                change(value)
                (directory / 'assessment.json').write_text(json.dumps(value, indent=2))
                refresh(directory)
                forged[name] = code_of(lambda: adaptor.verify(directory, executable=launcher)).code
                assert forged[name] == 'VERIFICATION_FAILED'
            directory = out / 'forge-capture'
            adaptor.run(document(fixtures['valid']), directory, executable=launcher, timeout=120)
            data = fixture.missing_image()
            (directory / 'captured.epub').write_bytes(data)
            captures = json.loads((directory / 'captures.json').read_text())
            captures.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            (directory / 'captures.json').write_text(json.dumps(captures))
            refresh(directory)
            fault = code_of(lambda: adaptor.verify(directory, executable=launcher))
            assert fault.code == 'VERIFICATION_FAILED' and fault.observed['findings']['counts']['fatal'] == 1
            forged['swapped-capture'] = fault.code
            report['forgeries'] = forged
            # Missing launcher is a fault; stored configuration restores verification; host refusals never start native code.
            empty = out / 'empty-config.json'
            atomic_json(empty, {'version': 1, 'locations': {}})
            clean = {k: v for k, v in os.environ.items() if k not in ('SCHEMAXIS_CONFIG', 'SCHEMAXIS_EPUBCHECK')}
            cli = [sys.executable, '-m', 'schemaxis', 'verify', str(out / 'run-valid')]
            missing = subprocess.run(cli, env={**clean, 'SCHEMAXIS_CONFIG': str(empty), 'PYTHONPATH': str(ROOT / 'src')}, capture_output=True, text=True, timeout=120)
            PROCESSES.append({'label': 'cli-verify-without-launcher', 'exitCode': missing.returncode})
            assert missing.returncode != 0 and 'INTERPRETER_NOT_FOUND' in missing.stdout + missing.stderr, missing.stdout[-300:] + missing.stderr[-300:]
            present = subprocess.run(cli, env={**clean, 'SCHEMAXIS_CONFIG': str(empty), 'SCHEMAXIS_EPUBCHECK': launcher, 'PYTHONPATH': str(ROOT / 'src')}, capture_output=True, text=True, timeout=240)
            PROCESSES.append({'label': 'cli-verify-with-SCHEMAXIS_EPUBCHECK', 'exitCode': present.returncode})
            assert present.returncode == 0 and '"verified": true' in present.stdout.replace('":true', '": true'), present.stdout[-300:] + present.stderr[-300:]
            report['cliVerify'] = {'withoutLauncher': 'INTERPRETER_NOT_FOUND (non-zero exit)', 'withSchemaxisEpubcheck': 'verified'}
            before = log.read_text().count('pid=')
            refusals = {}
            for name, data in {'not-zip': b'hello', 'traversal': fixture.raw_zip([(b'../x', b'x', 0, 0o100644 << 16, 3)]), 'symlink': fixture.raw_zip([(b'l', b'x', 0, 0o120777 << 16, 3)]),
                               'encrypted': fixture.raw_zip([(b'e', b'x', 1, 0o100644 << 16, 3)]), 'entity': fixture.with_member(fixture.valid(), 'EPUB/e.xhtml', '<!DOCTYPE html [<!ENTITY a "b">]><html/>'),
                               'bomb': fixture.with_member(fixture.valid(), 'EPUB/z.bin', bytes(4 * 1024 * 1024)),
                               'utf32': fixture.with_member(fixture.valid(), 'EPUB/u.xhtml', '<html/>'.encode('utf-32')),
                               'utf16-without-mark': fixture.with_member(fixture.valid(), 'EPUB/u.xhtml', '<html/>'.encode('utf-16-le')),
                               'declared-latin1': fixture.with_member(fixture.valid(), 'EPUB/u.xhtml', '<?xml version="1.0" encoding="ISO-8859-1"?><html/>'),
                               'dtd-outside-catalogue': fixture.with_member(fixture.valid(), 'EPUB/u.xhtml', '<!DOCTYPE html SYSTEM "http://www.w3.org/TR/html4/loose.dtd"><html/>'),
                               'file-dtd': fixture.with_member(fixture.valid(), 'EPUB/u.xhtml', '<!DOCTYPE html SYSTEM "file:///etc/hostname"><html/>'),
                               'mime-txt-file-dtd': fixture.epub2('<!DOCTYPE html SYSTEM "file:///etc/hostname">', content='c.txt'),
                               'mime-bin-jar-http-loopback-dtd': fixture.epub2('<!DOCTYPE html SYSTEM "jar:http://127.0.0.1:9/x.jar!/x.dtd">', content='c.bin'),
                               'mime-bin-ftp-loopback-dtd': fixture.epub2('<!DOCTYPE html SYSTEM "ftp://127.0.0.1:9/x.dtd">', content='c.bin'),
                               'mime-txt-utf32': fixture.replace_member(fixture.epub2('', content='c.txt'), 'OEBPS/c.txt', '<?xml version="1.0"?><html/>'.encode('utf-32')),
                               'mime-txt-utf16-entity': fixture.replace_member(fixture.epub2('', content='c.txt'), 'OEBPS/c.txt', '<!DOCTYPE html [<!ENTITY a "b">]><html/>'.encode('utf-16')),
                               'marker-in-binary-utf16-doctype': fixture.with_member(fixture.valid(), 'EPUB/m.bin', b'\x00\x01' + '<!DOCTYPE html SYSTEM "file:///etc/hostname">'.encode('utf-16-le')),
                               'unlisted-cp037-signature': fixture.with_member(fixture.valid(), 'EPUB/m.bin', ('<?xml version="1.0"?><!DOCTYPE html SYSTEM "file:///etc/hostname"><html/>').encode('cp037')),
                               'unlisted-ibm037-declared': fixture.with_member(fixture.valid(), 'EPUB/m.bin', b'<?xml version="1.0" encoding="IBM037"?>' + '<!DOCTYPE html SYSTEM "file:///etc/hostname"><html/>'.encode('cp037')),
                               'unlisted-ucs4-2143': fixture.with_member(fixture.valid(), 'EPUB/m.bin', b''.join(b'\x00\x00' + c.encode() + b'\x00' for c in '<?xml version="1.0"?><html/>')),
                               'unlisted-utf8-bom-latin1': fixture.with_member(fixture.valid(), 'EPUB/m.bin', b'\xef\xbb\xbf<?xml version="1.0" encoding="ISO-8859-1"?><html/>'),
                               'manifest-backslash-href': fixture.replace_member(fixture.epub2('', content='c.txt'), 'OEBPS/content.opf', zipfile.ZipFile(io.BytesIO(fixture.epub2('', content='c.txt'))).read('OEBPS/content.opf').replace(b'href="c.txt"', b'href="sub\\c.txt"')),
                               'manifest-tab-href': fixture.replace_member(fixture.epub2('', content='c.txt'), 'OEBPS/content.opf', zipfile.ZipFile(io.BytesIO(fixture.epub2('', content='c.txt'))).read('OEBPS/content.opf').replace(b'href="c.txt"', b'href="c&#9;.txt"')),
                               'zip-nul-name': fixture.raw_zip([(b'EPUB/c\x00.xhtml', b'<html/>', 0, 0o100644 << 16, 3)]),
                               'non-ascii-name-without-utf8-flag': fixture.raw_zip([('caf\u00e9.xhtml'.encode('utf-8'), b'<html/>', 0, 0o100644 << 16, 3)]),
                               'loopback-dtd': fixture.epub2('<!DOCTYPE html PUBLIC "-//SCHEMAXIS//DTD CANARY 1.0//EN" "http://127.0.0.1:9/canary.dtd">')}.items():
                path = work / ('refuse-%s.epub' % name)
                path.write_bytes(data)
                refusals[name] = code_of(lambda: adaptor.run(document(path), out / ('refuse-' + name), executable=launcher, timeout=60)).code
            assert log.read_text().count('pid=') == before, 'a host refusal started native code'
            report['hostRefusals'] = refusals
            report['hostRefusalsStartedNative'] = False
            # Network canary.
            listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(8); listener.settimeout(0.2)
            hits, stop = [], threading.Event()

            def serve():
                while not stop.is_set():
                    try:
                        connection, _ = listener.accept(); hits.append(1); connection.close()
                    except OSError:
                        pass
            thread = threading.Thread(target=serve); thread.start()
            url = 'http://127.0.0.1:%d/' % listener.getsockname()[1]
            canary = work / 'canary.epub'
            canary.write_bytes(fixture.epub(chapter_text=fixture.chapter('<p><img src="%sx.png" alt="x"/></p><audio src="%sa.mp3"/><script src="%ss.js"></script><link rel="stylesheet" href="%ss.css"/>' % ((url,) * 4))))
            try:
                code_of(lambda: adaptor.run(document(canary), out / 'canary', executable=launcher, timeout=120))
            finally:
                stop.set(); thread.join(); listener.close()
            report['networkCanary'] = {'loopbackConnections': len(hits)}
            assert not hits
            # External DTD canary: direct controls through the official checker, then the fixed stage launchers. The host refuses these
            # publications, so they never enter adaptor.run; this is a probe of the checker, not a claim that the platform admits a loopback DTD.
            server = Loopback()
            try:
                unknown = '<!DOCTYPE html PUBLIC "-//SCHEMAXIS//DTD CANARY 1.0//EN" "http://127.0.0.1:%d/canary.dtd">' % server.port
                catalogue = '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">'
                dtd_data = fixture.epub2(unknown)
                host_code = code_of(lambda: adaptor.preflight(dtd_data)).code
                assert host_code == 'UNSUPPORTED_EPUB_FEATURE'
                controls = {}

                def direct(label, payload, environment):
                    path = work / (label + '.epub')
                    path.write_bytes(payload)
                    output = work / (label + '.json')
                    before = len(server.requests)
                    argv = [real, str(path), '--json', str(output), '--failonwarnings', '--quiet', '--locale', 'en']
                    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, cwd=work)
                    out_text, err_text = process.communicate(timeout=120)
                    PROCESSES.append({'label': 'dtd-' + label, 'pid': process.pid, 'argv': [os.path.basename(argv[0]), *[os.path.basename(a) for a in argv[1:]]],
                                      'timeoutSeconds': 120, 'exitCode': process.returncode})
                    time.sleep(0.3)
                    ids = sorted(m['ID'] for m in json.loads(output.read_text())['messages']) if output.exists() else None
                    controls[label] = {'pid': process.pid, 'exitCode': process.returncode, 'javaToolOptions': environment.get('JAVA_TOOL_OPTIONS'),
                                       'loopbackRequests': server.requests[before:], 'messageIds': ids, 'stderr': err_text.decode()[-200:]}
                direct('epub2-unknown-no-property', dtd_data, NATIVE_PLAIN)
                direct('epub2-unknown-offline-property', dtd_data, {**NATIVE_PLAIN, 'JAVA_TOOL_OPTIONS': '-Depubcheck.offline=true'})
                direct('epub3-unknown-no-property', fixture.epub2(unknown, 3), NATIVE_PLAIN)
                direct('epub2-catalogue-no-property', fixture.epub2(catalogue), NATIVE_PLAIN)
                scratch = work / 'dtd-fixed'
                scratch.mkdir()
                (scratch / 'captured.epub').write_bytes(dtd_data)
                before, logged = len(server.requests), len(launches(log))
                identity, code = adaptor.run_check(scratch, launcher, (0, 1))      # the fixed stage launchers (poisoned parent environment), bypassing the host preflight
                fresh = launches(log)[logged:]
                controls['fixed-stage-launchers'] = {'identity': identity, 'exitCode': code, 'loopbackRequests': server.requests[before:], 'nativePids': [e['pid'] for e in fresh],
                                                     'versionStderrExact': (scratch / 'version.stderr').read_text() == NOTICE,
                                                     'checkStderrStartsWithNotice': (scratch / 'check.stderr').read_text().startswith(NOTICE),
                                                     'messageIds': sorted(m['ID'] for m in json.loads((scratch / 'assessment.json').read_text())['messages'])}
            finally:
                server.close()
            fetched = controls['epub2-unknown-no-property']['loopbackRequests']
            assert controls['epub2-unknown-offline-property']['loopbackRequests'] == []
            assert controls['fixed-stage-launchers']['loopbackRequests'] == [] and controls['fixed-stage-launchers']['versionStderrExact']
            assert controls['epub3-unknown-no-property']['loopbackRequests'] == [] and controls['epub2-catalogue-no-property']['loopbackRequests'] == []
            assert controls['epub2-catalogue-no-property']['exitCode'] == 0 and controls['epub2-unknown-no-property']['messageIds'] == controls['fixed-stage-launchers']['messageIds']
            assert not fetched or fetched == ['GET /canary.dtd HTTP/1.1'], fetched
            report['dtdCanary'] = {'hostRefusal': host_code, 'positiveControlFetched': bool(fetched),
                                   'positiveControl': 'the checker fetched the loopback DTD without the property' if fetched else
                                   'no request observed without the property on this Java; no fetch is claimed and the fixed property is still applied',
                                   'scope': 'EPUBCheck 5.4.0 on this Java, one unknown EPUB 2 external DTD named by a DOCTYPE SYSTEM identifier; not other releases, other resolver paths or OS-level isolation',
                                   'controls': controls}
            # Local file DTD observation under the fixed property (no network): documents that the property does not make file: identifiers safe.
            local = work / 'local-marker.dtd'
            local.write_text('<!ELEMENT html ANY>\n<!SCHEMAXISMARKER_TOKEN broken\n')
            observed = {}
            for label, system in (('file-url-existing', 'file://%s' % local), ('file-url-missing', 'file://%s/absent.dtd' % work), ('absolute-path', str(local)), ('relative-name', 'local-marker.dtd')):
                payload = fixture.epub2('<!DOCTYPE html PUBLIC "-//SCHEMAXIS//DTD FILE 1.0//EN" "%s">' % system)
                assert code_of(lambda: adaptor.preflight(payload)).code == 'UNSUPPORTED_EPUB_FEATURE'
                path = work / (label + '.epub')
                path.write_bytes(payload)
                output = work / (label + '.json')
                argv = [real, str(path), '--json', str(output), '--failonwarnings', '--quiet', '--locale', 'en']
                process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**NATIVE_PLAIN, 'JAVA_TOOL_OPTIONS': '-Depubcheck.offline=true'}, cwd=work)
                process.communicate(timeout=120)
                PROCESSES.append({'label': 'filedtd-' + label, 'pid': process.pid, 'argv': [os.path.basename(argv[0]), *[os.path.basename(a) for a in argv[1:]]],
                                  'timeoutSeconds': 120, 'exitCode': process.returncode})
                observed[label] = sorted(m['ID'] + ':' + m['severity'] for m in json.loads(output.read_text())['messages'])
            report['fileDtdObservation'] = {'hostRefusedAll': True, 'checkerUnderFixedProperty': observed, 'asserted': False,
                                            'meaning': 'recorded, not asserted: RSC-016 for the existing file: DTD against PKG-008 for the missing one indicates the checker read the local file even with the offline property'}
            # Lifecycle: in-flight timeout and cancellation leave no native worker.
            slow_log = out / 'slow-launches.log'
            slow = wrapper(out / 'slow-launcher', real, slow_log, sleep=60)
            code = code_of(lambda: adaptor.run(document(fixtures['valid']), out / 'timeout', executable=slow, timeout=4)).code
            pid = int(slow_log.read_text().split('pid=')[1].split()[0]); time.sleep(0.5)
            report['timeout'] = {'fault': code, 'pid': pid, 'survived': alive(pid)}
            assert code == 'RUNNER_TIMED_OUT' and not alive(pid)
            cancel = threading.Event(); threading.Timer(3.0, cancel.set).start()
            slow_log.unlink()
            with allocation({'threads': 2}, cancel):
                code = code_of(lambda: adaptor.run(document(fixtures['valid']), out / 'cancel', executable=slow, timeout=60)).code
            pid = int(slow_log.read_text().split('pid=')[1].split()[0]); time.sleep(0.5)
            report['cancellation'] = {'fault': code, 'pid': pid, 'survived': alive(pid)}
            assert code == 'RUNNER_CANCELLED' and not alive(pid)
            # Workflow: Pandoc report EPUB (artifact index 3) -> EPUBCheck.
            if args.pandoc:
                spec = json.loads((ROOT / 'examples/schemaxis/epubcheck-workflow.json').read_text())
                both = {'pandoc': str(args.pandoc.absolute()), 'epubcheck': launcher}
                first = workflow.execute(spec, out / 'workflow', locations=both, timeout=300)
                assert first['status'] == 'succeeded'
                with location_context(both):
                    assert workflow.verify(out / 'workflow')['verified']
                again = workflow.execute(spec, out / 'workflow', locations=both, timeout=300, resume=True)
                assert all(job['reused'] for job in again['jobs'])
                summaries = list((out / 'workflow').rglob('epubcheck-summary.json'))
                assert len(summaries) == 1
                report['workflow'] = {'status': first['status'], 'reusedOnResume': True, 'checkedMembers': json.loads(summaries[0].read_text())['source']['members']}
            else:
                report['workflow'] = 'unavailable: no --pandoc executable given; the Pandoc -> EPUBCheck workflow was not run'
        entries = launches(log)
        java_vars = ('JDK_JAVA_OPTIONS', '_JAVA_OPTIONS')
        report['nativeEnvironment'] = {
            'launches': len(entries), 'allHaveFixedOfflineProperty': all(e['env'].get('JAVA_TOOL_OPTIONS') == '-Depubcheck.offline=true' for e in entries),
            'parentPoison': POISON, 'launchesThatInheritedJdkOrUnderscoreOptions': sum(1 for e in entries if any(k in e['env'] for k in java_vars)),
            'environmentNamesSeen': sorted({n for e in entries for n in e.get('envnames', [])}),
            'affinityObservedInNativeProcesses': sorted({e.get('cpus') for e in entries if e.get('cpus')}),
            'limitsObservedInNativeProcesses': sorted({line for e in entries for line in e['limits']}),
            'limitsLinesPerLaunch': sorted({len(e['limits']) for e in entries}),
            'capsStatement': 'affinity and limits are read from /proc in the wrapper process, which then execs Java with the same PID; a lines-per-launch of 0 means the read was inconclusive and no cap is claimed'}
        assert entries and report['nativeEnvironment']['allHaveFixedOfflineProperty'] and not report['nativeEnvironment']['launchesThatInheritedJdkOrUnderscoreOptions']
        report['nativeLaunchLog'] = [{'pid': e['pid'], 'argv': e.get('argv'), 'cpus': e.get('cpus')} for e in entries]
        report['skipped'] += ['MPI (unsupported)', 'Windows/macOS launchers', 'other EPUBCheck releases', 'expanded EPUB folders and non-EPUB modes', 'non-default profiles']
        report['verified'] = True
    finally:
        for key, value in parent.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        report['probeProcesses'] = PROCESSES
        report['launchLogEntries'] = log.read_text().count('pid=') if log.exists() else 0
        atomic_json(out / 'acceptance.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
