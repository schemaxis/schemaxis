#!/usr/bin/env python3
"""Bounded native qualification of the explicitly selected eSpeak NG narration voices (en-us, en-gb, fr-fr, es) with an eSpeak NG 1.52.0 `espeak-ng`.

For each voice the tool queries the exact listing with its own parser, publishes a narration through the adaptor (UTF-8 French and Spanish literals included),
lets the adaptor verify it with a fresh native re-synthesis, and compares every PCM byte with this tool's own `espeak-ng -v<name>` and `-v<file>` runs, read
with its own WAV parser. That control uses the same native program as the adaptor, so it checks the command line and the stage wiring, not the synthesizer.
The three new voices are selected by the fixed identifier of their voice file (`-vgmw/en`, `-vroa/fr`, `-vroa/es`), never by the language name, and a private copy of the
data with extra voices shows why: there the `-v<name>` control is redirected to another file while the adaptor stays PCM-identical to the `-v<identifier>` control (a
`voices/<identifier>` file that would shadow the identifier is refused before any synthesis). It also records how the runtime treats voice names it does not list (a language-like name can fall back silently, which is why the exact listing is checked), refuses a real runtime whose data copy
lacks the selected voice file, forges a different sound and a different voice claim with every ordinary hash refreshed, proves that an absent voice still
produces the legacy record shape, and (with FLAC) runs narration -> lossless FLAC with an independent decode. With --sox and --flac it also runs the named
narration -> SoX conform -> untagged lossless FLAC handoff twice: the exact public examples/schemaxis/espeakng-voice-archive-workflow.json (French) with the raw
executables, and an explicit three-step Spanish workflow through private recording wrappers that keep the process IDs of the native stage processes started inside
workflow run and verify. Each stage is checked independently: fresh eSpeak PCM, the SoX conform summary (16000 Hz mono, expected frame count, source byte binding,
declared 0-0.6 Nyquist projection), and a flac -d decode whose PCM equals the conformed WAV (not the 22050 Hz narration: the resampling is declared lossy).
Evidence is structural and numeric: nothing here is listened to, and no pronunciation, language or accent accuracy, intelligibility or recognition is claimed.
Public output replaces workstation paths.
"""
import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualify_espeakng as q    # noqa: E402  (this tool's sibling: process recorder, WAV reader, forging helpers)
from schemaxis.adaptors.espeakng import adaptor    # noqa: E402
from schemaxis.artifacts import atomic_json    # noqa: E402
from schemaxis.configuration import location_context    # noqa: E402
from schemaxis.core.faults import SchemaxisError    # noqa: E402
from schemaxis import workflow    # noqa: E402

ENGLISH = 'Welcome to the plant tour. Please wear your safety glasses.'
FRENCH = "Bienvenue à la visite de l'usine. Veuillez porter vos lunettes de protection."
SPANISH = '¿Cómo estás? El niño comió mañana, detrás de la línea amarilla.'
TEXTS = {'en-us': ENGLISH, 'en-gb': ENGLISH, 'fr-fr': FRENCH, 'es': SPANISH}
FILES = {'en-us': 'gmw/en-US', 'en-gb': 'gmw/en', 'fr-fr': 'roa/fr', 'es': 'roa/es'}
LISTED = {'en-us': 'English_(America)', 'en-gb': 'English_(Great_Britain)', 'fr-fr': 'French_(France)', 'es': 'Spanish_(Spain)'}
QUERIES = {'en-us': 'en', 'en-gb': 'en-gb', 'fr-fr': 'fr-fr', 'es': 'es'}
RATE = 150
DEFAULT_RATE = 175    # the documented rateWpm default, for documents that omit it (the public workflow example)


def independent_speak(espeak, work, name, text, voice_argument, rate=RATE):
    """This tool's own espeak-ng command line; returns the WAV bytes."""
    source, target = Path(work) / (name + '.txt'), Path(work) / (name + '-control.wav')
    source.write_bytes(text.encode('utf-8'))
    target.unlink(missing_ok=True)
    q.native('control-' + name, [espeak, '-v' + voice_argument, '-s%d' % rate, '-p50', '-a100', '-b1', '-w', str(target), '-f', str(source)], work, timeout=60)
    return target.read_bytes()


def listing_rows(espeak, work, voice):
    """Rows whose first column is exactly the voice, parsed by this tool (not the adaptor's regex)."""
    output = q.native('voices-' + voice, [espeak, '--voices=' + QUERIES[voice]], work, timeout=30).decode('utf-8')
    rows = []
    for line in output.splitlines()[1:]:
        columns = line.split()
        if len(columns) >= 5 and columns[1] == voice:
            rows.append({'language': columns[1], 'name': columns[3], 'file': columns[4]})
    return rows


def pcm_facts(pcm):
    values = struct.unpack('<%dh' % (len(pcm) // 2), pcm)
    return {'frames': len(values), 'seconds': round(len(values) / 22050, 3), 'nonZeroSamples': sum(1 for v in values if v), 'peak': max(abs(v) for v in values), 'sha256': hashlib.sha256(pcm).hexdigest()}


def one_voice(espeak, work, voice):
    run = work / ('voice-' + (voice or 'absent'))
    text = TEXTS[voice or 'en-us']
    document = {'version': adaptor.VERSION, 'operation': 'narrate', 'text': text, 'rateWpm': RATE, **({'voice': voice} if voice else {})}
    result = adaptor.run(document, run, executable=espeak, timeout=120)
    verified = adaptor.verify(run, executable=espeak)    # a fresh native re-synthesis of every PCM byte
    assert verified['verified'] and verified['pcmSha256'] == result['pcmSha256']
    fmt, pcm = q.wav_parts((run / 'narration.wav').read_bytes())
    assert (fmt[1], fmt[2], fmt[5]) == (1, 22050, 16), fmt
    effective = voice or 'en-us'
    by_name = q.wav_parts(independent_speak(espeak, work, 'name-' + effective, text, effective))[1]
    by_file = q.wav_parts(independent_speak(espeak, work, 'file-' + effective, text, FILES[effective]))[1]
    assert pcm == by_name == by_file, 'adaptor PCM differs from the direct espeak-ng control'
    facts = pcm_facts(pcm)
    assert facts['nonZeroSamples'] > 0 and facts['peak'] > 0 and 0.5 < facts['seconds'] < 30, facts
    assert (run / 'captured.txt').read_bytes() == text.encode('utf-8')
    summary = adaptor.read_json(run, 'espeakng-summary.json')
    assert summary['voice']['requested'] == effective and summary['voice']['listing'] == {'language': effective, 'name': LISTED[effective], 'file': FILES[effective]}
    rows = listing_rows(espeak, work, effective)
    assert rows == [summary['voice']['listing']], rows
    if voice is None:    # an absent voice keeps the legacy record shape and wording
        assert 'voice' not in result and 'voice' not in adaptor.read_json(run, 'verification.json') and 'voice' not in adaptor.read_json(run, 'captures.json')
        assert summary['review'] == adaptor.REVIEW
    else:
        assert result['voice'] == voice and adaptor.read_json(run, 'verification.json')['voice'] == voice and adaptor.read_json(run, 'captures.json')['voice'] == voice
        assert summary['review'] == adaptor.REVIEW_VOICE % (voice, LISTED[voice], FILES[voice])
    return {'voice': voice, 'textUtf8Bytes': len(text.encode('utf-8')), 'textHasNonAscii': any(ord(c) > 127 for c in text), 'listing': rows[0], 'pcm': facts,
            'adaptorEqualsDirectNameAndFileControls': True, 'freshVerification': True, 'dataFingerprint': summary['runtime']['dataFingerprint'],
            'resultVoice': result.get('voice'), 'legacyShape': voice is None}, pcm


def voices(espeak, work):
    report, pcms = {}, {}
    for voice in (None, 'en-us', 'en-gb', 'fr-fr', 'es'):
        report[voice or 'absent'], pcms[voice or 'absent'] = one_voice(espeak, work, voice)
    assert pcms['absent'] == pcms['en-us'] and report['absent']['dataFingerprint'] == report['en-us']['dataFingerprint']    # explicit en-us is the legacy sound
    distinct = {name: hashlib.sha256(pcm).hexdigest() for name, pcm in pcms.items()}
    assert len({distinct['en-us'], distinct['fr-fr'], distinct['es']}) == 3
    fingerprints = {v: report[v]['dataFingerprint'] for v in ('en-us', 'en-gb', 'fr-fr', 'es')}
    assert len(set(fingerprints.values())) == 4
    # Same English text in every voice: recorded as a matrix, asserting only what the fixed profiles guarantee (different files are fingerprinted).
    same_text = {}
    for voice in ('en-us', 'en-gb', 'fr-fr', 'es'):
        run = work / ('same-' + voice)
        same_text[voice] = adaptor.run({'version': adaptor.VERSION, 'operation': 'narrate', 'text': ENGLISH, 'voice': voice, 'rateWpm': RATE}, run, executable=espeak, timeout=120)['pcmSha256']
    report['sameEnglishTextPcmSha256'] = same_text
    report['sameEnglishTextPcmDistinct'] = len(set(same_text.values()))
    assert same_text['en-us'] != same_text['fr-fr'] != same_text['es']
    return report


def probe_speak(espeak, work, name, text, voice_argument):
    """Like independent_speak, but records the exit status instead of asserting success; returns (exit code, WAV bytes or None)."""
    source, target = Path(work) / (name + '.txt'), Path(work) / (name + '-probe.wav')
    source.write_bytes(text.encode('utf-8'))
    target.unlink(missing_ok=True)
    command = [espeak, '-v' + voice_argument, '-s%d' % RATE, '-p50', '-a100', '-b1', '-w', str(target), '-f', str(source)]
    process = subprocess.Popen(command, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.communicate(timeout=60)
    q.PROCESSES.append({'name': 'probe-' + name, 'pid': process.pid, 'timeoutSeconds': 60, 'command': [Path(espeak).name, *command[1:3]], 'exitCode': process.returncode})
    return process.returncode, (target.read_bytes() if target.exists() and target.stat().st_size else None)


def unknown_voice_control(espeak, work):
    """Two unknown voice names: a language-like one makes eSpeak NG exit 0 with different audio (silent fallback), a non-language one exits non-zero.

    Only the first kind needs the exact listing check; both are recorded because the behaviour is the runtime's, not this adaptor's.
    """
    us = q.wav_parts(independent_speak(espeak, work, 'unknown-us-reference', ENGLISH, 'en-us'))[1]
    report = {}
    for name in ('de-xx', 'zz-nonexistent'):
        code, wav = probe_speak(espeak, work, 'unknown-' + name, ENGLISH, name)
        pcm = q.wav_parts(wav)[1] if wav else b''
        report[name] = {'exitCode': code, 'audioBytes': len(pcm), 'equalsEnUsPcm': pcm == us if pcm else None, 'listedByQuery': listing_rows_for(espeak, work, name)}
        assert report[name]['listedByQuery'] == []
    return report


def listing_rows_for(espeak, work, name):
    output = q.native('voices-' + name, [espeak, '--voices=' + name], work, timeout=30).decode('utf-8')
    return [line for line in output.splitlines()[1:] if len(line.split()) > 1 and line.split()[1] == name]


def missing_voice_file(espeak, work):
    """A private data copy lacking roa/fr, reached through a trusted wrapper that sets ESPEAK_DATA_PATH: the adaptor refuses fr-fr there, still serves es."""
    data = Path(subprocess.run([espeak, '--version'], capture_output=True, text=True, check=True).stdout.split('Data at: ')[1].strip())
    root = work / 'trimmed-data'
    shutil.copytree(data, root / 'espeak-ng-data')
    (root / 'espeak-ng-data/lang/roa/fr').unlink()
    wrapped = q.wrapper(work / 'trimmed-espeak', espeak, {'ESPEAK_DATA_PATH': str(root)})
    seen = q.native('trimmed-version', [wrapped, '--version'], work, timeout=30).decode()
    assert str(root / 'espeak-ng-data') in seen, seen
    native_listing = listing_rows_for(wrapped, work, 'fr-fr')
    direct_code, direct = probe_speak(wrapped, work, 'trimmed-fr', FRENCH, 'fr-fr')
    fixed_code, fixed = probe_speak(wrapped, work, 'trimmed-fr-file', FRENCH, FILES['fr-fr'])
    fault = q.refused(lambda: adaptor.run({'version': adaptor.VERSION, 'operation': 'narrate', 'text': FRENCH, 'voice': 'fr-fr'}, work / 'trimmed-fr-run', executable=wrapped, timeout=60),
                      'UNSUPPORTED_RUNTIME')
    failed = adaptor.read_json(work / 'trimmed-fr-run', 'result.json')
    assert failed['status'] == 'failed' and not (work / 'trimmed-fr-run/narration.wav').exists() and not (work / 'trimmed-fr-run/verification.json').exists()
    served = adaptor.run({'version': adaptor.VERSION, 'operation': 'narrate', 'text': SPANISH, 'voice': 'es'}, work / 'trimmed-es-run', executable=wrapped, timeout=60)
    return {'trimmedRuntimeListsFrFr': bool(native_listing), 'nativeDirectFrFrExitCode': direct_code, 'nativeDirectFrFrProducedAudio': bool(direct and len(q.wav_parts(direct)[1]) > 0),
            'nativeDirectFixedIdentifierExitCode': fixed_code, 'nativeDirectFixedIdentifierProducedAudio': bool(fixed and len(q.wav_parts(fixed)[1]) > 0), 'adaptorFault': fault.code,
            'adaptorFaultMessage': fault.message[:200], 'failedRunKeepsNoPublication': True, 'unaffectedVoiceEsSucceeded': served['verified'],
            'boundary': 'a trimmed copy of the data directory used only through a private wrapper; the original installation is never modified'}


def lookup_redirects(espeak, work):
    """A private data copy (reached through a trusted wrapper that only sets ESPEAK_DATA_PATH) with extra voices: the old ``-v<name>`` command is redirected, the fixed identifier is not.

    Normal copy for the three new voices, then top-level ``lang/<name>`` for all three, a higher-scored Other Languages voice for fr-fr and en-gb, a
    ``lang/fr-fr/voices/fr-fr`` tree, and a ``voices/roa/fr`` shadow of the fixed identifier itself (refused by the adaptor before any synthesis). Each case compares PCM bytes;
    exit codes alone prove nothing. The original installation is never modified.
    """
    data = Path(subprocess.run([espeak, '--version'], capture_output=True, text=True, check=True).stdout.split('Data at: ')[1].strip())
    root = work / 'lookup-data'
    shutil.copytree(data, root / 'espeak-ng-data')
    private = root / 'espeak-ng-data'
    wrapped = q.wrapper(work / 'lookup-espeak', espeak, {'ESPEAK_DATA_PATH': str(root)})
    assert str(private) in q.native('lookup-version', [wrapped, '--version'], work, timeout=30).decode()
    new = ('en-gb', 'fr-fr', 'es')

    def pcm_of(name, text, argument):
        code, wav = probe_speak(wrapped, work, name, text, argument)
        return code, (q.wav_parts(wav)[1] if wav else None)

    def adapted(voice, label):
        run = work / ('lookup-' + label + '-' + voice)
        result = adaptor.run({'version': adaptor.VERSION, 'operation': 'narrate', 'text': TEXTS[voice], 'voice': voice, 'rateWpm': RATE}, run, executable=wrapped, timeout=120)
        assert adaptor.verify(run, executable=wrapped)['verified']
        return q.wav_parts((run / 'narration.wav').read_bytes())[1], result

    def digest(pcm):
        return hashlib.sha256(pcm).hexdigest() if pcm else None
    report = {'boundary': 'a private copy of the data directory used only through a private wrapper; the original installation is never modified; filesystem race protection and the closure of every native dependency are not claimed'}
    mapped = {}
    for voice in new:
        code_file, by_file = pcm_of('lookup-0-file-' + voice, TEXTS[voice], FILES[voice])
        code_name, by_name = pcm_of('lookup-0-name-' + voice, TEXTS[voice], voice)
        assert code_file == code_name == 0 and by_file == by_name and by_file
        pcm, result = adapted(voice, 'normal')
        assert pcm == by_file and result['voice'] == voice
        mapped[voice] = by_file
        report.setdefault('normalCopy', {})[voice] = {'argument': '-v' + FILES[voice], 'adaptorEqualsFixedIdentifierAndNameControls': True, 'pcmSha256': digest(by_file)}
    cases = [('top-level-lang-name', {v: ('lang/' + v, b'name x\nlanguage de\n') for v in new}),
             ('higher-scored-other-language', {'fr-fr': ('lang/roa/fr-x', b'name zz\nlanguage de\nlanguage fr-fr 1\n'), 'en-gb': ('lang/gmw/en-x', b'name zz\nlanguage de\nlanguage en-gb 1\n')})]
    for label, voices_map in cases:
        for voice, (relative, body) in voices_map.items():
            path = private / relative
            path.write_bytes(body)
            try:
                code_name, by_name = pcm_of('lookup-%s-name-%s' % (label, voice), TEXTS[voice], voice)
                code_file, by_file = pcm_of('lookup-%s-file-%s' % (label, voice), TEXTS[voice], FILES[voice])
                pcm, result = adapted(voice, label)
            finally:
                path.unlink()
            assert by_name != mapped[voice], 'the old language-name control must be redirected by this extra voice'
            assert code_file == 0 and by_file == mapped[voice] and pcm == mapped[voice] and result['voice'] == voice
            report.setdefault(label, {})[voice] = {'oldNameControlExitCode': code_name, 'oldNameControlPcmSha256': digest(by_name), 'oldNameControlRedirected': True,
                                                   'fixedIdentifierControlEqualsGenuine': True, 'adaptorEqualsGenuine': True, 'pcmSha256': digest(pcm)}
    (private / 'lang/fr-fr/voices').mkdir(parents=True)
    (private / 'lang/fr-fr/voices/fr-fr').write_bytes(b'name x\nlanguage de\n')
    try:
        code_name, by_name = pcm_of('lookup-nested-name-fr-fr', TEXTS['fr-fr'], 'fr-fr')
        pcm, _ = adapted('fr-fr', 'nested')
    finally:
        shutil.rmtree(private / 'lang/fr-fr')
    assert pcm == mapped['fr-fr'] and by_name != mapped['fr-fr']
    report['nestedLangFrFrVoicesFrFr'] = {'oldNameControlExitCode': code_name, 'oldNameControlProducedAudio': bool(by_name), 'adaptorEqualsGenuine': True}
    (private / 'voices/roa').mkdir()
    (private / 'voices/roa/fr').write_bytes(b'name x\nlanguage de\n')
    try:
        code_shadow, shadowed = pcm_of('lookup-shadow-file-fr-fr', TEXTS['fr-fr'], 'roa/fr')
        fault = q.refused(lambda: adaptor.run({'version': adaptor.VERSION, 'operation': 'narrate', 'text': TEXTS['fr-fr'], 'voice': 'fr-fr'}, work / 'lookup-shadow-run', executable=wrapped, timeout=60),
                          'UNSUPPORTED_RUNTIME')
    finally:
        shutil.rmtree(private / 'voices/roa')
    assert shadowed != mapped['fr-fr'] and not (work / 'lookup-shadow-run/narration.wav').exists()
    report['voicesShadowOfFixedIdentifier'] = {'nativeFixedIdentifierControlReadsShadow': True, 'nativeExitCode': code_shadow, 'adaptorFault': fault.code, 'adaptorFaultMessage': fault.message[:200], 'noNarrationPublished': True}
    return report


def forgeries(espeak, work):
    run = work / 'voice-fr-fr'
    saved = q.snapshot(run)
    report = {}
    es_pcm = q.wav_parts((work / 'voice-es/narration.wav').read_bytes())[1]
    wav = q.wav_of(es_pcm)
    (run / 'narration.wav').write_bytes(wav)
    (run / 'native.wav').write_bytes(wav)
    q.refresh(run, espeak, rewrite_summary=False)
    report['spanishSoundUnderFrenchClaim'] = q.verify_fault(run, espeak).message[:160]
    assert 'fresh native re-synthesis' in report['spanishSoundUnderFrenchClaim'] or 'differ' in report['spanishSoundUnderFrenchClaim'], report
    q.restore(saved)
    authored = adaptor.read_json(run, 'authored.json')
    authored['voice'] = 'es'
    prepared = adaptor.plan(authored)
    atomic_json(run / 'authored.json', authored)
    atomic_json(run / 'plan.json', prepared)
    atomic_json(run / 'captures.json', adaptor.capture_record(prepared, FRENCH.encode('utf-8')))
    atomic_json(run / 'verification.json', {**adaptor.read_json(run, 'verification.json'), 'voice': 'es'})
    q.refresh(run, espeak, rewrite_summary=False)
    report['frenchSoundUnderSpanishClaimAllVoiceRecordsRewritten'] = q.verify_fault(run, espeak).message[:160]
    assert 'does not equal fresh native re-synthesis' in report['frenchSoundUnderSpanishClaimAllVoiceRecordsRewritten'], report
    q.restore(saved)
    assert adaptor.verify(run, executable=espeak)['verified']
    report['restoredGenuinePublicationVerifies'] = True
    return report


def flac_handoff(espeak, flac, work):
    run = work / 'archive-workflow'
    graph = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'narration', 'document': {'version': adaptor.VERSION, 'operation': 'narrate', 'voice': 'fr-fr', 'text': FRENCH, 'rateWpm': RATE}},
        {'id': 'archive', 'document': {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': {'$artifact': 'narration', 'index': 0}}}]}
    locations = {'espeakng': espeak, 'flac': flac}
    result = workflow.execute(graph, run, locations=locations, timeout=240)
    assert result['status'] == 'succeeded'
    with location_context(locations):
        assert workflow.verify(run)['verified']
    archive, narrated = list(run.rglob('audio.flac')), list(run.rglob('narration.wav'))
    assert len(archive) == len(narrated) == 1
    decoded = work / 'archive-decoded.wav'
    q.native('flac-independent-decode', [flac, '-d', '-s', '-w', '--no-preserve-modtime', '-o', str(decoded), str(archive[0])], work, timeout=60)
    pcm = q.wav_parts(narrated[0].read_bytes())[1]
    assert q.wav_parts(decoded.read_bytes())[1] == pcm
    summary = adaptor.read_json(narrated[0].parent, 'espeakng-summary.json')
    assert summary['voice']['requested'] == 'fr-fr'
    return {'status': result['status'], 'narrationVoice': 'fr-fr', 'workflowVerified': True, 'independentFlacDecodeEqualsEveryNarrationPcmByte': True, 'pcm': pcm_facts(pcm),
            'flacVersion': q.native('flac-version', [flac, '--version'], work, timeout=20).decode().strip(), 'taggedArchive': False,
            'scope': 'direct narration -> FLAC only (no SoX step); the narration -> SoX conform -> FLAC handoff is the soxConformWorkflows section'}


# ---------------------------------------------------------------- narration -> SoX conform -> untagged FLAC
RECORDER = """#!%(python)s
import json, os, signal, subprocess, sys, time
REAL, LOG = %(real)r, %(log)r
started = time.time()
child = subprocess.Popen(sys.argv, executable=REAL)    # argv[0] stays the configured path (SoX names it in --version); stdio, working directory and environment are inherited
signal.signal(signal.SIGTERM, lambda *_: (child.kill(), os._exit(143)))
try:
    observed = os.readlink('/proc/%%d/exe' %% child.pid)
except OSError:
    observed = None
code = child.wait()
with open(LOG, 'a') as stream:
    stream.write(json.dumps({'wrapperPid': os.getpid(), 'wrapperInitialArgv': [os.path.basename(a) for a in sys.argv], 'nativePid': child.pid, 'observedNativeExecutable': observed,
                             'nativeArgv': [os.path.basename(REAL), *[os.path.basename(a) if a.startswith('/') else a for a in sys.argv[1:]]], 'exitCode': code,
                             'seconds': round(time.time() - started, 3)}) + '\\n')
sys.exit(code if code >= 0 else 128 - code)
"""


def recording_wrapper(path, real, log):
    """A private launcher that runs the real executable as a child and logs both PIDs, the executable it observed and the exit status.

    The wrapper PID is not the native PID (the native program is its child); the observed executable is read from /proc after the child exists.
    The real program receives the wrapper's path as argv[0], as it would from a launcher that execs it, because SoX prints argv[0] in --version and the adaptor
    requires it to name the configured executable; the program that runs, and its version output, are the real ones.
    Only processes started through the wrapper are recorded: this does not claim to track every descendant."""
    Path(path).write_text(RECORDER % {'python': sys.executable, 'real': str(real), 'log': str(log)})
    Path(path).chmod(0o700)
    return str(path)


def read_log(log, start=0):
    lines = Path(log).read_text().splitlines() if Path(log).exists() else []
    return [json.loads(line) for line in lines[start:]], len(lines)


def flac_stream_info(data):
    """This tool's own FLAC metadata walk: block types, STREAMINFO (rate, channels, bits, samples, MD5) and the VORBIS_COMMENT vendor and user-comment count."""
    assert data[:4] == b'fLaC'
    offset, kinds, info, comments = 4, [], None, None
    while True:
        header = data[offset]
        kind, size = header & 0x7F, int.from_bytes(data[offset + 1:offset + 4], 'big')
        kinds.append(kind)
        if kind == 0:
            word = int.from_bytes(data[offset + 4 + 10:offset + 4 + 18], 'big')
            info = {'rate': word >> 44, 'channels': ((word >> 41) & 7) + 1, 'bits': ((word >> 36) & 31) + 1, 'samples': word & ((1 << 36) - 1),
                    'md5': data[offset + 4 + 18:offset + 4 + 34].hex()}
        if kind == 4:
            body = data[offset + 4:offset + 4 + size]
            length = struct.unpack_from('<I', body)[0]
            comments = {'vendor': body[4:4 + length].decode('ascii'), 'userComments': struct.unpack_from('<I', body, 4 + length)[0], 'bytes': size}
            assert size == 8 + length, 'VORBIS_COMMENT carries more than a vendor string'
        offset += 4 + size
        if header & 0x80:
            return kinds, info, comments


def stage_file(run, stage, name):
    found = [p for p in Path(run).rglob(name) if p.relative_to(run).parts[0] == stage]
    assert len(found) == 1, (stage, name, found)
    return found[0]


def conform_handoff(espeak, sox, flac, work, label, graph, wrap):
    """Run one narration -> conform -> encodeLossless graph, verify it freshly, and check every stage independently."""
    run = work / label
    log = work / (label + '-stage-processes.jsonl')
    if wrap:
        locations = {name: recording_wrapper(work / (label + '-' + name), real, log) for name, real in (('espeakng', espeak), ('sox', sox), ('flac', flac))}
    else:
        locations = {'espeakng': espeak, 'sox': sox, 'flac': flac}
    ids = [o['id'] for o in graph['operations']]
    assert [o['document']['version'] for o in graph['operations']] == ['schemaxis.espeakng/1', 'schemaxis.sox/1', 'schemaxis.flac/1'] and ids == ['narration', 'speech', 'archive']
    assert graph['operations'][1]['document']['channelPolicy'] in ('average', 'left')    # the policies a mono source accepts
    phases, mark = {}, 0
    result = workflow.execute(graph, run, locations=locations, timeout=240)
    assert result['status'] == 'succeeded' and [j['id'] for j in result['jobs']] == ['narration/0', 'speech/0', 'archive/0'] and not any(j['reused'] for j in result['jobs']), result
    phases['workflow.execute'], mark = read_log(log, mark)
    with location_context(locations):
        verified = workflow.verify(run)
    assert verified['verified']
    phases['workflow.verify'], mark = read_log(log, mark)

    # --- stage 1: fresh eSpeak PCM, compared with this tool's own native command
    document = graph['operations'][0]['document']
    narration = stage_file(run, 'narration', 'narration.wav')
    fmt, pcm = q.wav_parts(narration.read_bytes())
    assert (fmt[1], fmt[2], fmt[5]) == (1, 22050, 16), fmt
    control = q.wav_parts(independent_speak(espeak, work, label + '-narration', document['text'], document['voice'], document.get('rateWpm', DEFAULT_RATE)))[1]
    assert pcm == control, 'narration PCM differs from the direct espeak-ng control'
    narration_facts = pcm_facts(pcm)
    assert narration_facts['nonZeroSamples'] > 0 and narration_facts['peak'] > 0
    assert adaptor.read_json(narration.parent, 'espeakng-summary.json')['voice']['requested'] == document['voice']

    # --- stage 2: SoX conform
    speech = stage_file(run, 'speech', 'audio.wav')
    conformed = speech.read_bytes()
    sfmt, spcm = q.wav_parts(conformed)
    expected_frames = int(Fraction(narration_facts['frames'] * 16000, 22050) + Fraction(1, 2))    # round-half-up, this tool's own arithmetic
    assert (sfmt[0], sfmt[1], sfmt[2], sfmt[3], sfmt[4], sfmt[5]) == (1, 1, 16000, 32000, 2, 16), sfmt
    assert len(spcm) == 2 * expected_frames and len(conformed) == 44 + len(spcm), (len(spcm), expected_frames)
    summary = json.loads(stage_file(run, 'speech', 'audio-summary.json').read_text())
    assert summary['channelPolicy'] == graph['operations'][1]['document']['channelPolicy'] and summary['rate'] == 16000 and summary['channels'] == 1
    assert summary['frames'] == expected_frames
    assert summary['source']['sha256'] == hashlib.sha256(narration.read_bytes()).hexdigest() and summary['source']['bytes'] == narration.stat().st_size
    assert (summary['source']['rate'], summary['source']['channels'], summary['source']['frames']) == (22050, 1, narration_facts['frames'])
    assert summary['conversion']['resampled'] is True and summary['fidelity']['method'] == 'independent-band-limited-projection'
    assert summary['fidelity']['comparedPositions'] > 0 and not summary['fidelity']['samplesRecomputedExactly']
    assert not [w for w in summary['warnings'] if w['code'] in ('SILENT_OUTPUT', 'FIDELITY_NOT_SAMPLED')], summary['warnings']
    out_values = struct.unpack('<%dh' % expected_frames, spcm)
    in_values = struct.unpack('<%dh' % narration_facts['frames'], pcm)
    rms = lambda values: (sum(v * v for v in values) / len(values)) ** 0.5
    level = rms(out_values) / rms(in_values)
    assert 0.7 < level < 1.1, level    # a coarse level sanity check of this tool, not a fidelity proof; the declared projection is the adaptor's own check
    conform_job = json.loads((speech.parent / 'job.json').read_text())
    assert conform_job['handoffs'][0]['sha256'] == hashlib.sha256(narration.read_bytes()).hexdigest()

    # --- stage 3: untagged FLAC; independent decode equals the CONFORMED pcm (not the 22050 Hz narration)
    archive = stage_file(run, 'archive', 'audio.flac')
    flac_bytes = archive.read_bytes()
    kinds, info, comments = flac_stream_info(flac_bytes)
    assert kinds == [0, 4] and comments['userComments'] == 0, (kinds, comments)    # STREAMINFO plus libFLAC's empty VORBIS_COMMENT (vendor only): no tags, PICTURE, padding, seek table or cue sheet
    assert (info['rate'], info['channels'], info['bits'], info['samples']) == (16000, 1, 16, expected_frames), info
    assert info['md5'] == hashlib.md5(spcm).hexdigest()
    decoded = work / (label + '-decoded.wav')
    q.native(label + '-flac-independent-decode', [flac, '-d', '-s', '-w', '--no-preserve-modtime', '-o', str(decoded), str(archive)], work, timeout=60)
    dfmt, dpcm = q.wav_parts(decoded.read_bytes())
    assert (dfmt[1], dfmt[2], dfmt[5]) == (1, 16000, 16) and dpcm == spcm, 'decoded FLAC PCM differs from the conformed WAV'
    assert dpcm != pcm
    archive_job = json.loads((archive.parent / 'job.json').read_text())
    assert archive_job['handoffs'][0]['sha256'] == hashlib.sha256(conformed).hexdigest()

    # --- reuse and a tamper control
    again = workflow.execute(graph, run, locations=locations, timeout=240, resume=True)
    assert all(j['reused'] for j in again['jobs']), again
    phases['workflow.resume'], mark = read_log(log, mark)
    saved = speech.read_bytes()
    flipped = bytearray(saved)
    flipped[-3] ^= 0x10
    speech.write_bytes(bytes(flipped))
    try:
        with location_context(locations):
            workflow.verify(run)
        raise AssertionError('a changed conformed WAV verified')
    except SchemaxisError as error:
        tamper = {'code': error.fault.code, 'message': error.fault.message[:160]}
    finally:
        speech.write_bytes(saved)
    with location_context(locations):
        assert workflow.verify(run)['verified']
    phases['workflow.verify.afterTamperRestore'], mark = read_log(log, mark)

    processes = None
    if wrap:
        everything = [row for rows in phases.values() for row in rows]
        natives = {row['nativePid'] for row in everything}
        wrappers = {row['wrapperPid'] for row in everything}
        assert len(natives) == len(wrappers) == len(everything) and not natives & wrappers, 'a process ID repeats in the stage log'
        assert all(Path(row['observedNativeExecutable'] or '/').name in ('espeak-ng', 'sox', 'flac') for row in everything), everything
        assert not any(Path('/proc/%d' % pid).exists() for pid in natives | wrappers), 'a recorded stage process still exists'
        processes = {'method': 'private wrapper per executable (a child process of the wrapper is the native program); recorded inside workflow.execute, workflow.verify, resume and the post-restore verify',
                     'wrapperIsNotTheNativeProcess': True, 'uniqueNativePids': len(natives), 'uniqueWrapperPids': len(wrappers), 'invocations': len(everything),
                     'perPhase': {name: len(rows) for name, rows in phases.items()}, 'nonZeroExits': [r for r in everything if r['exitCode']],
                     'allRecordedProcessesExited': True, 'workflowTimeoutSeconds': 240, 'records': phases,
                     'notClaimed': 'processes not started through the wrappers (for example the host Python) are not recorded, and the count is not a claim that every descendant was tracked'}
    return {'status': result['status'], 'jobs': [j['id'] for j in result['jobs']], 'wrapped': wrap, 'voice': document['voice'], 'channelPolicy': summary['channelPolicy'],
            'workflowVerifiedFresh': True, 'reuseOnResume': True, 'changedConformedWavRefused': tamper, 'restoredVerifies': True,
            'narration': {'wavBytes': narration.stat().st_size, 'wavSha256': hashlib.sha256(narration.read_bytes()).hexdigest(), 'pcm': narration_facts, 'equalsDirectEspeakControl': True},
            'conform': {'wavBytes': len(conformed), 'wavSha256': hashlib.sha256(conformed).hexdigest(), 'pcmSha256': hashlib.sha256(spcm).hexdigest(), 'rate': 16000, 'channels': 1,
                        'frames': expected_frames, 'expectedFramesRoundHalfUp': expected_frames, 'sourceSha256BoundToNarrationWav': True, 'conversion': summary['conversion'],
                        'fidelity': summary['fidelity'], 'warnings': summary['warnings'], 'saturatedSamples': summary['saturatedSamples'], 'peakPCM16': summary['peakPCM16'],
                        'levelRatioOutputToInputRms': round(level, 4)},
            'flac': {'bytes': len(flac_bytes), 'sha256': hashlib.sha256(flac_bytes).hexdigest(), 'metadataBlockTypes': kinds, 'streamInfo': info, 'vorbisComment': comments, 'tagged': False,
                     'handoffSha256BoundToConformedWav': True, 'independentFlacDecodeEqualsEveryConformedPcmByte': True, 'streamInfoMd5EqualsConformedPcmMd5': True,
                     'flacVersion': q.native(label + '-flac-version', [flac, '--version'], work, timeout=20).decode().strip()},
            'lossLimits': ['22050 Hz -> 16000 Hz resampling is lossy: SoX output is verified only in the declared projection band and level limits (see fidelity), not sample-by-sample and not above that band',
                           'FLAC is lossless relative to the conformed WAV only; the conformed PCM does not equal the 22050 Hz narration PCM',
                           'no listening, ASR, intelligibility, language, accent, speaker identity or accessibility claim'],
            'stageProcesses': processes}


def sox_conform_workflows(espeak, sox, flac, work):
    version = q.native('sox-version', [sox, '--version'], work, timeout=20).decode().strip()
    assert 'SoX v14.4.2' in version, version
    example = q.ROOT / 'examples/schemaxis/espeakng-voice-archive-workflow.json'
    published = json.loads(example.read_text())
    spanish = {'version': 'schemaxis.workflow/1', 'operations': [
        {'id': 'narration', 'document': {'version': adaptor.VERSION, 'operation': 'narrate', 'voice': 'es', 'text': SPANISH, 'rateWpm': RATE}},
        {'id': 'speech', 'document': {'version': 'schemaxis.sox/1', 'operation': 'conform', 'source': {'$artifact': 'narration', 'index': 0}, 'channelPolicy': 'average'}},
        {'id': 'archive', 'document': {'version': 'schemaxis.flac/1', 'operation': 'encodeLossless', 'source': {'$artifact': 'speech', 'index': 0}}}]}
    return {'soxRuntime': version,
            'publicExample': {'file': 'examples/schemaxis/' + example.name, 'fileSha256': hashlib.sha256(example.read_bytes()).hexdigest(),
                              'note': 'the exact public workflow file, run unmodified with the raw trusted executables (no wrapper)',
                              **conform_handoff(espeak, sox, flac, work, 'public-example-fr-fr', published, wrap=False)},
            'explicitSpanish': {'note': 'an explicit three-step es workflow semantically identical in shape to the public example, run through recording wrappers',
                                **conform_handoff(espeak, sox, flac, work, 'explicit-es', spanish, wrap=True)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--espeakng', type=Path, required=True, help='absolute eSpeak NG 1.52.0 espeak-ng')
    parser.add_argument('--flac', type=Path, help='absolute FLAC 1.5 flac for the narration -> lossless archive handoff (reported not run when absent)')
    parser.add_argument('--sox', type=Path, help='absolute SoX 14.4.2 sox for the narration -> conform -> FLAC handoff (needs --flac; reported not run when absent)')
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    espeak = os.path.abspath(args.espeakng)
    locations = {'espeakng': espeak}
    report = {'verified': False, 'qualifierPid': os.getpid(), 'argv': [Path(sys.argv[0]).name, *[Path(a).name if a.startswith('/') else a for a in sys.argv[1:]]]}
    try:
        version = q.native('espeak-ng-version', [espeak, '--version'], directory, timeout=20).decode().strip()
        assert version.startswith('eSpeak NG text-to-speech: 1.52.0'), version
        report['runtime'] = {'identity': version.split('  Data at:')[0]}
        work = directory / 'work'
        work.mkdir()
        with location_context(locations):
            report['voices'] = voices(espeak, work)
            report['unknownVoiceControl'] = unknown_voice_control(espeak, work)
            report['missingVoiceFile'] = missing_voice_file(espeak, work)
            report['lookupRedirects'] = lookup_redirects(espeak, work)
            report['forgeries'] = forgeries(espeak, work)
            report['flacHandoff'] = flac_handoff(espeak, os.path.abspath(args.flac), work) if args.flac else 'not run: no --flac executable given'
            if args.sox and args.flac:
                report['soxConformWorkflows'] = sox_conform_workflows(espeak, os.path.abspath(args.sox), os.path.abspath(args.flac), work)
            else:
                report['soxConformWorkflows'] = 'not run: ' + ('no --sox executable given' if not args.sox else 'no --flac executable given')
        report['verified'] = True
    finally:
        report['probeProcesses'] = q.PROCESSES
        atomic_json(directory / 'acceptance.json', report)
        try:
            atomic_json(directory / 'acceptance-public.json', q.public(report, espeak, directory))
        except Exception as error:    # a failed run still keeps the private record
            print('public report not written:', error, file=sys.stderr)
    print(json.dumps(q.public(report, espeak, directory), indent=2))


if __name__ == '__main__':
    main()
