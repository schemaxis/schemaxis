"""HOST-ONLY stand-in for the EPUBCheck launcher; it is not a native check and proves nothing about the real checker.

It reads the ZIP named by its first argument, builds an EPUBCheck-shaped JSON report from the container listing, and
takes its scripted behaviour from an optional ``FAKE.json`` member (for example extra messages, a malformed report, an
exit status, a delay or a recorded process id). The native boundary tests run the real official checker instead.
"""
import json
import os
import signal
import sys
import time
import zipfile


def report(names, sizes, script, name):
    messages = script.get('messages', [])
    counts = {s: sum(1 for m in messages if m['severity'] == s) for s in ('FATAL', 'ERROR', 'WARNING', 'USAGE')}
    items = [{'id': 'item%d' % i, 'fileName': n, 'media_type': None, 'compressedSize': sizes[n][0], 'uncompressedSize': sizes[n][1],
              'compressionMethod': sizes[n][2], 'checkSum': 'abc', 'isSpineItem': n.endswith('chapter.xhtml'), 'spineIndex': 0 if n.endswith('chapter.xhtml') else None,
              'isLinear': n.endswith('chapter.xhtml'), 'isFixedFormat': None, 'isScripted': False, 'renditionLayout': None, 'renditionOrientation': None,
              'renditionSpread': None, 'referencedItems': []} for i, n in enumerate(sorted(names))]
    publication = {'publisher': None, 'title': 'Tiny', 'creator': [], 'date': None, 'subject': [], 'description': None, 'rights': None, 'identifier': 'urn:x',
                   'language': 'en', 'nSpines': sum(1 for i in items if i['isSpineItem']), 'checkSum': 0, 'renditionLayout': 'reflowable', 'renditionOrientation': 'auto',
                   'renditionSpread': 'auto', 'ePubVersion': '3.4', 'isScripted': False, 'hasFixedFormat': False, 'isBackwardCompatible': True, 'hasAudio': False,
                   'hasVideo': False, 'charsCount': 5, 'embeddedFonts': [], 'refFonts': [], 'hasEncryption': False, 'hasSignatures': False, 'contributors': []}
    return {'messages': messages, 'customMessageFileName': None,
            'checker': {'path': './' + name, 'filename': name, 'checkerVersion': script.get('version', '5.4.0'), 'checkDate': '10-25-2026 00:00:%02d' % (time.time() % 60),
                        'elapsedTime': int(time.time() * 1000) % 5000, 'nFatal': counts['FATAL'], 'nError': counts['ERROR'], 'nWarning': counts['WARNING'], 'nUsage': counts['USAGE']},
            'publication': publication, 'items': items}


def announce_java_options():
    """Imitate the JVM's own stderr line when JAVA_TOOL_OPTIONS is set (the real notice comes from HotSpot, not the checker)."""
    if 'JAVA_TOOL_OPTIONS' in os.environ:
        sys.stderr.write('Picked up JAVA_TOOL_OPTIONS: %s\n' % os.environ['JAVA_TOOL_OPTIONS'])


def main():
    arguments = sys.argv[1:]
    announce_java_options()
    if arguments == ['--version']:
        print('EPUBCheck v5.4.0')
        return 0
    name = arguments[0]
    output = arguments[arguments.index('--json') + 1]
    with zipfile.ZipFile(name) as archive:
        names = [i.filename for i in archive.infolist() if not i.is_dir()]
        sizes = {i.filename: (i.compress_size, i.file_size, 'Stored' if i.compress_type == 0 else 'Deflated') for i in archive.infolist()}
        script = json.loads(archive.read('FAKE.json')) if 'FAKE.json' in archive.namelist() else {}
    if 'pid-file' in script:
        open(script['pid-file'], 'w').write(str(os.getpid()))
    if 'env-file' in script:
        open(script['env-file'], 'w').write(json.dumps(dict(os.environ)))
    if script.get('sleep'):
        time.sleep(script['sleep'])
    if script.get('stderr'):
        sys.stderr.write(script['stderr'])
    data = report(names, sizes, script, name)
    for edit in script.get('edits', []):                          # [path, value]: mutate the report before writing
        target = data
        for part in edit[0][:-1]:
            target = target[part]
        target[edit[0][-1]] = edit[1]
    text = script.get('raw') or json.dumps(data, indent=2)
    if script.get('ignore-xfsz'):                                  # like HotSpot: SIGXFSZ is ignored, so an over-cap write is a short write plus an error
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    if not script.get('no-report'):
        try:
            with open(output, 'w') as stream:
                stream.write(text)
        except OSError as error:
            sys.stderr.write('java.io.IOException: %s\n' % error.strerror)
    messages = data['messages']
    return script.get('exit', 1 if any(m['severity'] in ('FATAL', 'ERROR', 'WARNING') for m in messages) else 0)


if __name__ == '__main__':
    sys.exit(main())
