"""Bounded structural reader for canonical Godot saved scenes; executes nothing.

A whole-file lexical scan separates tags from strings and resource values. Node
headers and transforms are interpreted; resource values and script bindings are
not semantically verified. Multiline resources are allowed; node properties must
be complete single-line saver values.
"""
import re
import io
from .errors import fault

CHUNK_CHARS = 64 * 1024
MAX_TAG_CHARS = 16 * 1024
MAX_DEPTH = 64
MAX_NODES = 129
ATTRIBUTE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*("(?:[^"\\]|\\.)*"|[^\s\]]+)')
NODE = re.compile(r'\[\s*node(?=\s)')
TRANSFORM = re.compile(r'transform\s*=\s*Transform3D\(([^)]*)\)\s*$')
ASSIGNMENT = re.compile(r'([A-Za-z_][A-Za-z0-9_/]*)\s*=\s*(.+)')
SCALAR = re.compile(r'[A-Za-z_][A-Za-z0-9_]*|[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
COMPOUND = re.compile(r'(?:[A-Za-z_][A-Za-z0-9_]*(?:\[[A-Za-z0-9_, ]+\])?\(|[\[{])')
FOREIGN = ('instance', 'instance_placeholder', 'owner', 'groups', 'index', 'node_paths')
IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]


def malformed(message, line):
    fault('SCENE_MALFORMED', 'Saved scene is not a readable Godot text scene: '+message, 'scene.tscn:'+str(line),
          'Reopen the original verified directory, or rerun the adaptor in a fresh directory; do not hand-edit scene.tscn '
          'and keep the verification receipt.')


class Value:
    """Linear-time lexical state for one saver value, across resource lines."""
    def __init__(self, text, line):
        self.stack, self.quote, self.escape, self.done = [], False, False, False
        if SCALAR.fullmatch(text):
            self.done = True
            return
        string = re.match(r'[&^]?"', text)
        compound = COMPOUND.match(text)
        if string:
            self.quote = True
            start = string.end()
        elif compound:
            self.stack.append(text[compound.end()-1])
            start = compound.end()
        else:
            malformed('property must contain exactly one saved value', line)
        self.feed(text[start:], line)

    def feed(self, text, line):
        if self.done:
            if text.strip(): malformed('trailing text after property or tag', line)
            return
        cursor = 0
        for match in re.finditer(r'["\\()\[\]{};]', text):
            offset, char = match.start(), match[0]
            if self.escape and offset > cursor:
                self.escape = False  # the escaped ordinary character was skipped
            if self.escape:
                self.escape = False
            elif char == '\\' and self.quote:
                self.escape = True
            elif char == '"':
                self.quote = not self.quote
                if not self.quote and not self.stack: self.done = True
            elif not self.quote:
                if char == ';': malformed('inline comments inside saver values are unsupported', line)
                if char in '([{':
                    self.stack.append(char)
                    if len(self.stack) > MAX_DEPTH:
                        fault('RESOURCE_LIMIT', 'Saved resource nesting exceeds 64 levels.', 'scene.tscn:'+str(line),
                              'Keep canonical saver-generated resources; do not add nested hand-authored values.')
                elif char in ')]}':
                    if not self.stack or self.stack.pop() != {')':'(', ']':'[', '}':'{'}[char]:
                        malformed('unbalanced property or tag', line)
                    if not self.stack: self.done = True
            cursor = match.end()
            if self.done:
                if text[cursor:].strip(): malformed('trailing text after property or tag', line)
                return
        if self.escape and cursor < len(text): self.escape = False


def attributes(body, number):
    result, end = {}, 0
    while end < len(body):
        while end < len(body) and body[end].isspace():
            end += 1
        if end == len(body):
            break
        # Anchored consumption avoids quadratic searching on malformed long keys.
        match = ATTRIBUTE.match(body, end)
        if match is None or match[1] in result:
            malformed('unreadable or duplicate node attribute', number)
        result[match[1]] = match[2]
        end = match.end()
    for name in ('name', 'type', 'parent'):
        if name in result and not (result[name].startswith('"') and result[name].endswith('"')):
            malformed('node name, type and parent must be quoted saver strings', number)
    return result


def inspect(data):
    try:
        return _inspect(io.StringIO(data.decode('utf-8'), newline=None))
    except UnicodeDecodeError:
        malformed('not UTF-8 text', 1)


def inspect_file(path):
    try:
        with path.open('r', encoding='utf-8', newline=None) as stream:
            return _inspect(stream)
    except UnicodeDecodeError:
        malformed('not UTF-8 text', 1)


def chunks(stream):
    number = 1
    while True:
        raw = stream.readline(CHUNK_CHARS)
        if not raw: return
        yield number, raw, raw.endswith('\n') or len(raw) < CHUNK_CHARS
        number += raw.count('\n')


def _inspect(stream):
    """Stream resource values; bound canonical tag/node statements independently."""
    nodes, current, root, pending = {}, None, None, None
    seen_header, number = False, 1
    for number, raw, line_end in chunks(stream):
        if pending is not None:
            pending.feed(raw, number)
            if pending.done and line_end:
                pending = None
            continue
        line = raw.strip()
        if not line or line.startswith(';'):
            if not line_end:
                fault('RESOURCE_LIMIT', 'Comment or blank scene line exceeds the canonical 65536-character limit.', 'scene.tscn:'+str(number),
                      'Keep original saver-generated lines; do not pad or hand-edit the scene.')
            continue
        if not seen_header:
            if not re.match(r'^\[\s*gd_scene\b', line): malformed('missing [gd_scene] header', number)
            seen_header = True
        if line.startswith('['):
            if not line_end or len(line) > MAX_TAG_CHARS:
                fault('RESOURCE_LIMIT', 'Saved scene tag exceeds the canonical 16384-character limit.', 'scene.tscn:'+str(number),
                      'Keep original saver-generated tags; do not pad or hand-edit node headers.')
            tag = Value(line, number)
            if not tag.done:
                malformed('tag must be complete on one line', number)
            if not re.match(r'^\[\s*node\b', line):
                current = None
                continue
            header = NODE.match(line)
            if header is None:
                malformed('unreadable [node] header', number)
            fields = attributes(line[header.end():-1], number)
            if 'name' not in fields or 'type' not in fields:
                malformed('node needs name and type', number)
            name, kind = fields['name'][1:-1], fields['type'][1:-1]
            parent = fields['parent'][1:-1] if 'parent' in fields else None
            if parent is None:
                if root is not None:
                    malformed('more than one root node', number)
                root = name
            if name in nodes or len(nodes) >= MAX_NODES:
                malformed('repeated node name or too many nodes', number)
            current = {'type':kind, 'parent':parent, 'transform':IDENTITY,
                       'foreign':sorted(set(fields)&set(FOREIGN)), 'line':number}
            nodes[name] = current
            continue
        if current is not None and not line_end:
            fault('RESOURCE_LIMIT', 'Node property exceeds the canonical 65536-character limit.', 'scene.tscn:'+str(number),
                  'Keep original saver-generated node properties; resource data is streamed separately.')
        assignment = ASSIGNMENT.fullmatch(line)
        if assignment is None:
            malformed('property must be an assignment', number)
        key, value = assignment.groups()
        lexical = Value(value, number)
        if current is None:
            if not lexical.done or not line_end:
                pending = lexical
            continue
        if not lexical.done:
            malformed('node property must be complete on one line', number)
        if key.startswith('global_') or key in ('position','rotation','rotation_degrees','scale','quaternion','basis','top_level'):
            malformed('non-canonical node placement property', number)
        if key != 'transform':
            continue
        transform = TRANSFORM.fullmatch(line)
        if transform is None:
            malformed('unreadable transform', number)
        try:
            values = [float(v) for v in transform[1].split(',')]
        except ValueError:
            malformed('unreadable transform', number)
        if len(values) != 12 or not all(abs(v) < 1e30 for v in values):
            malformed('transform needs twelve finite values', number)
        current['transform'] = values
    if pending is not None and not pending.done:
        malformed('incomplete resource value', number)
    if root is None:
        malformed('no root node', number)
    return root, nodes
