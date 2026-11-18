# Copyright (C) 2026 David L. F. Gaden.
"""Scope-aware entry renaming using checked expression bindings, never text matching."""
import copy
import re
from . import expressions
from .expr import syntax
from .errors import fail
from .spatial_actions import Draft


def rename(request):
    draft = Draft(request)
    section, old, new = (request.get(key) for key in ('section', 'name', 'newName'))
    member = draft.selected
    if section not in expressions.SECTIONS or old not in member.scope.sections.get(section, {}):
        fail('UNKNOWN_ENTRY', 'Choose an existing named value')
    if not isinstance(new, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', new):
        fail('INVALID_NAME', 'Use a letter, then letters, digits, _ or -')
    if new == old:
        return {'input': copy.deepcopy(draft.input)}
    if new in member.scope.sections[section]:
        fail('DUPLICATE_NAME', 'That name already exists in this group')
    result = copy.deepcopy(draft.input)
    old_pointer = expressions.pointer('/' + section, old)
    new_pointer = expressions.pointer('/' + section, new)
    edits = []

    def walk(value, owner, path=''):
        if isinstance(value, list):
            return [walk(item, owner, expressions.pointer(path, i)) for i, item in enumerate(value)]
        if not isinstance(value, dict):
            return value
        result = {key: walk(item, owner, expressions.pointer(path, key)) for key, item in value.items()}
        if isinstance(value.get('$expr'), str):
            text = value['$expr']
            try:
                checked = owner.scope.check(text, expressions.pointer(path, '$expr'))
            except expressions.expr.ExprFault as error:
                fail('RENAME_UNRESOLVED_REFERENCE', 'Repair this expression before renaming so its references can be identified: ' + str(error), owner.location(path))
            pending, replacements = [checked.tree], []
            while pending:
                node = pending.pop()
                binding = getattr(node.info, 'binding', None)
                if (isinstance(binding, expressions.EntryBinding) and binding.scope is member.scope
                        and binding.section == section and binding.key == old):
                    replacements.append((node.position, node.length, f'{section}.`{new}`'
                                         if owner is member else f'workflow.{section}.`{new}`'))
                    continue
                pending.extend(syntax.children(node))
            for position, length, replacement in sorted(replacements, reverse=True):
                text = text[:position] + replacement + text[position + length:]
            result['$expr'] = text
        if isinstance(value.get('$document'), str):
            target_owner = (draft.envelope if value.get('scope') == 'workflow' else
                            next((m for m in draft.operations if m.operation == value.get('operation')), None)
                            if value.get('operation') else owner)
            target = value['$document']
            if not target.startswith('/'):
                parts = path.split('/')[1:-1]
                for part in target.split('/'):
                    if part == '..':
                        if not parts: fail('INVALID_REFERENCE', 'Relative reference escapes its document')
                        parts.pop()
                    elif part != '.': parts.append(part)
                target = '/' + '/'.join(parts)
            if target_owner is member and (target == old_pointer or target.startswith(old_pointer + '/')):
                result['$document'] = new_pointer + target[len(old_pointer):]
        return result

    for owner in ([draft.envelope] if draft.envelope else []) + (draft.operations if draft.workflow else [member]):
        # The envelope's operation documents have their own binding scopes.
        authored = {k: v for k, v in owner.authored.items() if not (owner is draft.envelope and k == 'operations')}
        rewritten = walk(authored, owner)
        edits.append((owner, rewritten))
    for owner, rewritten in edits:
        if owner is member:
            rewritten[section][new] = rewritten[section].pop(old)
        if not owner.base:
            result.update(rewritten)
        else:
            target = result
            parts = owner.base.strip('/').split('/')
            for part in parts[:-1]: target = target[int(part)] if isinstance(target, list) else target[part]
            target[parts[-1]] = rewritten
    return {'input': result}
