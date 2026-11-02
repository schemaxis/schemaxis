#!/usr/bin/env python3
"""Scan tracked files, directories and packages for material that must not be released.

Usage:
    python3 tools/release_gate.py                      # scan `git ls-files`
    python3 tools/release_gate.py --path dist/x.whl    # also scan a package
    python3 tools/release_gate.py --no-git --path DIR  # scan only a directory

Built-in patterns are project-neutral (workstation paths, internal wiki hosts,
credential shapes). Private terms are supplied from outside the repository with
--patterns FILE or SCHEMAXIS_RELEASE_PATTERNS.

Every hit is printed as `file:line: pattern`; line 0 means the file name itself
matched. The exit status is 1 when any hit is not covered by the allowlist
(`tools/release_gate_allow.json`), 2 for usage or input errors, and 0 otherwise.
"""
import argparse
import base64
import fnmatch
import gzip
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOW = ROOT / 'tools' / 'release_gate_allow.json'
BINARY_PROBE = 8192
# Packaged Studio help stores large page bodies gzip-compressed and base64-encoded
# (tools/generate_studio_help.py). Base64 is scanned as the text it encodes, not
# as the encoding: random letter runs in it match short patterns by chance, and
# the actual content would otherwise be invisible.
GZIP_FIELD = re.compile(r'"bodyGzip":"([A-Za-z0-9+/=]+)"')

# Built-in, project-neutral checks. Organisation- or person-specific terms do
# not belong in this public file: keep them in a private patterns file and pass
# it with --patterns or the SCHEMAXIS_RELEASE_PATTERNS environment variable.
SUBSTRINGS = (
    '/home/',
    '/Users/',
    'atlassian.net',
    'PRIVATE KEY-----',
)
REGEXES = (
    ('aws-access-key-id', r'\bAKIA[0-9A-Z]{16}\b'),
    ('github-token', r'\bgh[pousr]_[A-Za-z0-9]{36,}\b'),
)


def compile_patterns(substrings=(), words=(), regexes=()):
    """Return (name, expression) pairs.

    Substrings match case-insensitively; words match case-sensitively as whole
    words; regexes are (name, expression) pairs used as written.
    """
    result = [(text, re.compile(re.escape(text), re.IGNORECASE)) for text in substrings]
    result += [(word, re.compile(r'\b' + re.escape(word) + r'\b')) for word in words]
    result += [(name, re.compile(expression)) for name, expression in regexes]
    return tuple(result)


def load_patterns(path):
    """Load a private patterns file: {"substrings": [], "words": [], "regex": [{"name", "pattern"}]}."""
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    lists = {key: data.get(key, []) for key in ('substrings', 'words')}
    for key, values in lists.items():
        if not (isinstance(values, list) and all(isinstance(v, str) and v for v in values)):
            raise ValueError(f'{key} must be a list of non-empty strings: {path}')
    regexes = []
    for entry in data.get('regex', []):
        if not (isinstance(entry, dict) and isinstance(entry.get('name'), str)
                and isinstance(entry.get('pattern'), str)):
            raise ValueError(f'regex entries need a name and a pattern: {path}')
        regexes.append((entry['name'], entry['pattern']))
    return compile_patterns(lists['substrings'], lists['words'], regexes)


BUILTIN = compile_patterns(SUBSTRINGS, (), REGEXES)
PATTERNS = BUILTIN


def configure(pattern_files=()):
    """Activate the built-in patterns plus any private pattern files."""
    global PATTERNS
    extra = ()
    for path in pattern_files:
        extra += load_patterns(path)
    PATTERNS = BUILTIN + extra
    return PATTERNS


def match_line(line):
    """Return the names of every active pattern found in one line of text."""
    return [name for name, expression in PATTERNS if expression.search(line)]


def expand_gzip_fields(text):
    """Return (text, bodies): the text with each decodable gzip field replaced by
    a placeholder, and the decompressed body of each in order. A field that is
    not valid base64 gzip is left in place and scanned as written."""
    bodies = []

    def replace(match):
        try:
            data = gzip.decompress(base64.b64decode(match.group(1), validate=True))
        except (ValueError, OSError, EOFError, zlib.error):
            return match.group(0)
        bodies.append(data.decode('utf-8', errors='replace'))
        return f'"bodyGzip":"<decoded body {len(bodies)}>"'

    return GZIP_FIELD.sub(replace, text), bodies


def scan_lines(name, text):
    return [(name, number, pattern) for number, line in enumerate(text.splitlines(), 1)
            for pattern in match_line(line)]


def scan_text(name, text):
    """Return (name, line, pattern) hits for a file name and its text content.

    Hits inside a decoded gzip field are labelled `name!bodyGzip`, with line
    numbers counted within the decompressed body.
    """
    hits = [(name, 0, pattern) for pattern in match_line(name)]
    if text is not None:
        text, bodies = expand_gzip_fields(text)
        hits.extend(scan_lines(name, text))
        for body in bodies:
            hits.extend(scan_lines(f'{name}!bodyGzip', body))
    return hits


def decode(data):
    """Return text for scannable content, or None for binary data."""
    if b'\0' in data[:BINARY_PROBE]:
        return None
    return data.decode('utf-8', errors='replace')


def scan_bytes(name, data):
    return scan_text(name, decode(data))


def is_archive(path):
    lower = path.name.lower()
    return lower.endswith(('.whl', '.zip', '.tar', '.tar.gz', '.tgz'))


def scan_archive(path, label):
    """Scan every regular member of a wheel, zip or tar archive in memory."""
    hits = scan_text(label, None)
    lower = path.name.lower()
    if lower.endswith(('.whl', '.zip')):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if not info.is_dir():
                    hits.extend(scan_bytes(f'{label}!{info.filename}', archive.read(info)))
    else:
        with tarfile.open(path, 'r:*') as archive:
            for member in archive:
                name = f'{label}!{member.name}'
                if member.isfile():
                    hits.extend(scan_bytes(name, archive.extractfile(member).read()))
                else:
                    hits.extend(scan_text(name, None))
    return hits


def scan_paths(root, names):
    """Scan files named relative to root; archives are opened and their members scanned."""
    hits = []
    for name in names:
        path = Path(root) / name
        if path.is_symlink() or not path.is_file():
            hits.extend(scan_text(name, None))
        elif is_archive(path):
            hits.extend(scan_archive(path, name))
        else:
            hits.extend(scan_bytes(name, path.read_bytes()))
    return hits


def scan_location(location):
    """Scan one --path argument: a directory tree, an archive or a single file."""
    path = Path(location)
    if path.is_dir():
        names = sorted(str(item.relative_to(path)) for item in path.rglob('*')
                       if item.is_file() and not item.is_symlink())
        return [(f'{path.as_posix().rstrip("/")}/{name}', line, pattern)
                for name, line, pattern in scan_paths(path, names)]
    if path.is_file():
        label = path.as_posix()
        return [(label + name[len(path.name):], line, pattern)
                for name, line, pattern in scan_paths(path.parent, [path.name])]
    raise FileNotFoundError(f'no such file or directory: {location}')


def tracked_files(repo):
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=repo, check=True,
                            stdout=subprocess.PIPE)
    return [name for name in result.stdout.decode('utf-8').split('\0') if name]


def load_allow(path):
    """Load allowlist entries: {"allow": [{"glob", "reason", "patterns"?}]}."""
    if path is None:
        return []
    with open(path, encoding='utf-8') as handle:
        entries = json.load(handle).get('allow', [])
    for entry in entries:
        if not isinstance(entry.get('glob'), str) or not str(entry.get('reason', '')).strip():
            raise ValueError(f'allowlist entry needs a glob and a reason: {entry!r}')
        patterns = entry.get('patterns')
        if patterns is not None and not (isinstance(patterns, list)
                                         and all(isinstance(item, str) for item in patterns)):
            raise ValueError(f'allowlist patterns must be a list of strings: {entry!r}')
    return entries


def allowed(hit, entries):
    """Return whether a hit is covered; archive members match by full label or member path."""
    name, _, pattern = hit
    candidates = [name]
    if '!' in name:
        candidates.append(name.split('!', 1)[1])
    for entry in entries:
        patterns = entry.get('patterns')
        if patterns is not None and pattern not in patterns:
            continue
        if any(fnmatch.fnmatchcase(candidate, entry['glob']) for candidate in candidates):
            return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--repo', default=None,
                        help='repository whose tracked files are scanned (default: this checkout)')
    parser.add_argument('--path', action='append', default=[],
                        help='also scan a directory, file, wheel, zip or tar archive; repeatable')
    parser.add_argument('--no-git', action='store_true', help='do not scan tracked files')
    parser.add_argument('--allow', default=None, help='allowlist JSON file')
    parser.add_argument('--no-allow', action='store_true', help='report every hit')
    parser.add_argument('--patterns', action='append', default=[],
                        help='private patterns JSON file; repeatable. '
                             'SCHEMAXIS_RELEASE_PATTERNS may also list files, separated by '
                             + repr(os.pathsep))
    args = parser.parse_args(argv)

    pattern_files = list(args.patterns)
    pattern_files += [item for item in os.environ.get('SCHEMAXIS_RELEASE_PATTERNS', '').split(os.pathsep)
                      if item]
    try:
        configure(pattern_files)
    except (OSError, ValueError, re.error) as error:
        print(f'release gate: cannot read patterns: {error}', file=sys.stderr)
        return 2

    repo = Path(args.repo) if args.repo else ROOT
    try:
        entries = [] if args.no_allow else load_allow(args.allow or (
            repo / 'tools' / 'release_gate_allow.json' if args.repo else DEFAULT_ALLOW))
    except (OSError, ValueError) as error:
        print(f'release gate: cannot read allowlist: {error}', file=sys.stderr)
        return 2

    hits = []
    try:
        if not args.no_git:
            hits.extend(scan_paths(repo, tracked_files(repo)))
        for location in args.path:
            hits.extend(scan_location(location))
    except (OSError, subprocess.CalledProcessError, zipfile.BadZipFile, tarfile.TarError) as error:
        print(f'release gate: {error}', file=sys.stderr)
        return 2

    reported = sorted(set(hit for hit in hits if not allowed(hit, entries)))
    for name, line, pattern in reported:
        print(f'{name}:{line}: {pattern}')
    suppressed = len(set(hits)) - len(reported)
    files = len({name.split('!', 1)[0] for name, _, _ in reported})
    print(f'release gate: {len(reported)} hit(s) in {files} file(s); '
          f'{suppressed} allowlisted; {len(PATTERNS)} pattern(s), '
          f'{len(PATTERNS) - len(BUILTIN)} private', file=sys.stderr)
    return 1 if reported else 0


if __name__ == '__main__':
    sys.exit(main())
