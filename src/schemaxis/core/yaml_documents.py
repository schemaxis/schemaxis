"""Optional YAML 1.2 authoring, restricted to finite JSON-compatible values."""
import io
import math
from .faults import SchemaxisError, Fault


def fault(code, message, mark=None):
    observed = {} if mark is None else {'line': mark.line + 1, 'column': mark.column + 1, 'offset': mark.index}
    raise SchemaxisError(Fault(code, message, '$', 'input', observed=observed,
        recovery='Use one YAML 1.2 document with string keys, finite values and no tags, anchors or aliases.'))


def parser():
    try:
        from ruamel.yaml import YAML
    except ImportError:
        fault('YAML_UNAVAILABLE', 'YAML support requires the optional extra: pip install "schemaxis[yaml]"')
    yaml = YAML(typ='rt')
    yaml.version = (1, 2)
    yaml.preserve_quotes = True
    yaml.allow_duplicate_keys = False
    # ruamel also resolves timestamps by default; YAML 1.2 core keeps them strings.
    resolvers = yaml.resolver.versioned_resolver
    for key in list(resolvers):
        resolvers[key] = [(tag, pattern) for tag, pattern in resolvers[key]
                          if tag != 'tag:yaml.org,2002:timestamp']
    return yaml


def tree(text):
    yaml = parser()
    try:
        from ruamel.yaml.tokens import AliasToken, AnchorToken, TagToken, DirectiveToken
        for token in yaml.scan(text):
            if isinstance(token, DirectiveToken) and (token.name != 'YAML' or token.value != (1, 2)):
                fault('UNSUPPORTED_YAML', 'Only the YAML 1.2 version directive is supported', token.start_mark)
            if isinstance(token, (AliasToken, AnchorToken, TagToken)):
                fault('UNSUPPORTED_YAML', 'Tags, anchors and aliases are not supported', token.start_mark)
        def check_keys(node, depth=0):
            if depth > 128: fault('DOCUMENT_LIMIT', 'YAML exceeds its depth limit', node.start_mark)
            if node.id == 'mapping':
                for key, child in node.value:
                    if key.value == '<<': fault('UNSUPPORTED_YAML', 'YAML merge keys are not supported', key.start_mark)
                    check_keys(child, depth+1)
            elif node.id == 'sequence':
                for child in node.value: check_keys(child, depth+1)
        root = yaml.compose(text)
        if root is not None: check_keys(root)
        value = yaml.load(text)
        plain(value)
        return value
    except SchemaxisError:
        raise
    except Exception as error:
        fault('INVALID_YAML', str(error), getattr(error, 'problem_mark', None))


def plain(value, depth=0, budget=None):
    budget = [100000] if budget is None else budget
    budget[0] -= 1
    if depth > 128 or budget[0] < 0:
        fault('DOCUMENT_LIMIT', 'YAML exceeds its size or depth limit')
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                fault('INVALID_YAML', 'YAML mapping keys must be strings')
            if key == '<<':
                fault('UNSUPPORTED_YAML', 'YAML merge keys are not supported')
            result[str(key)] = plain(item, depth+1, budget)
        return result
    if isinstance(value, list):
        return [plain(item, depth+1, budget) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        if value is None or isinstance(value, bool): return value
        if isinstance(value, str): return str(value)
        return int(value)
    if isinstance(value, float) and math.isfinite(value):
        return float(value)
    fault('INVALID_YAML', 'YAML values must be finite JSON-compatible data (quote dates and timestamps)')


def load(text):
    return plain(tree(text))


def dump(value):
    plain(value)
    stream = io.StringIO()
    yaml = parser()
    yaml.version = None
    yaml.dump(value, stream)
    return stream.getvalue()


def reconcile(source, value):
    """Retain comments/quotes on unchanged and replaced nodes during structured edits."""
    original = tree(source)
    def update(old, new):
        if isinstance(old, dict) and isinstance(new, dict):
            for key in list(old):
                if key not in new:
                    del old[key]
            for key, item in new.items():
                old[key] = update(old[key], item) if key in old else item
            return old
        if isinstance(old, list) and isinstance(new, list):
            # Match moved identifiable objects to preserve their comments during canvas edits.
            keyed = {item['id']: item for item in old if isinstance(item, dict) and isinstance(item.get('id'), str)}
            items = [update(keyed.get(item.get('id'), old[index] if index < len(old) else None), item)
                     if isinstance(item, dict) else update(old[index] if index < len(old) else None, item)
                     for index, item in enumerate(new)]
            old[:] = items
            return old
        return old if plain(old) == new else new
    return dump(update(original, value))


def ranges(source):
    yaml = parser()
    tree(source)  # profile validation precedes source mapping
    root = yaml.compose(source)
    found = {}
    def visit(node, pointer):
        found[pointer] = (node.start_mark.index, node.end_mark.index)
        if node.id == 'mapping':
            for key, value in node.value:
                visit(value, pointer + '/' + key.value.replace('~', '~0').replace('/', '~1'))
        elif node.id == 'sequence':
            for index, value in enumerate(node.value):
                visit(value, pointer + '/' + str(index))
    if root is not None:
        visit(root, '')
    return found
