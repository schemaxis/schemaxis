"""Package repository help as searchable, lazy-loaded Studio topics.

No native applications, Markdown libraries or network resources are required.
Run after updating documentation: python3 tools/generate_studio_help.py.
"""
import argparse
import hashlib
import base64
import gzip
import json
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'src/schemaxis/studio_ui/help'
OPERATIONS = 'docs/paraview-operation-reference.md'


def slug(text):
    return re.sub(r'[^\w\s-]', '', text.strip().lower()).replace(' ', '-')


def headings(text):
    result, counts, fence = [], {}, False
    for line in text.splitlines():
        if line.startswith('```'):
            fence = not fence
        match = None if fence else re.match(r'^(#{1,6})\s+(.+)$', line)
        if match:
            level, title = len(match[1]), match[2]
            base = slug(title)
            count = counts.get(base, 0)
            counts[base] = count + 1
            result.append({'level': level, 'title': title, 'anchor': base + (f'-{count}' if count else '')})
    return result


def build(*, check=False):
    from schemaxis.capabilities import CapabilityCatalogue, operation_id
    from schemaxis.documentation_links import markdown_anchors
    discovery = CapabilityCatalogue()
    pages, entries, links = {}, [], {}
    providers = {p.name for p in (ROOT / 'src/schemaxis/adaptors').iterdir() if (p / 'adaptor.json').is_file()}
    paths = list(sorted((ROOT / 'docs').glob('*.md')))
    paths += list(sorted((ROOT / 'docs/generated').glob('*-operations.md')))
    paths = [p for p in paths if p.name != 'paraview-operations.md']
    # Only linked sources/examples are included; no access to local workspace data.
    pending, seen = paths[:], set()
    while pending:
        path = pending.pop(0).resolve()
        if path in seen or not path.is_file() or not path.is_relative_to(ROOT):
            continue
        seen.add(path)
        source = path.relative_to(ROOT).as_posix()
        if source == 'docs/generated/paraview-operations.md':
            continue
        if path.suffix not in ('.md', '.json', '.py', '.txt'):
            continue
        text = path.read_text()
        title_match = re.search(r'^#\s+(.+)$', text, re.M)
        title = title_match[1] if title_match else path.name
        if path.suffix == '.md':
            for target in re.findall(r'\]\(([^)]+)\)', text):
                target = target.strip('<>').split('#')[0]
                if target and not re.match(r'^[a-z]+:', target):
                    linked = (path.parent / unquote(target)).resolve()
                    if linked.is_relative_to(ROOT) and linked.parts[len(ROOT.parts)] in ('docs', 'examples', 'src'):
                        pending.append(linked)
        group = 'Guides'
        provider = None
        split = source == OPERATIONS or (source.startswith('docs/generated/') and path.name.endswith('-operations.md'))
        if split:
            provider = 'paraview' if source == OPERATIONS else path.name.removesuffix('-operations.md')
            group = f'{provider} operations'
            sections = re.split(r'(?=^##\s+)', text, flags=re.M)
            chunks = [(None, title, sections[0])]
            for section in sections[1:]:
                match = re.match(r'##\s+(.+)', section)
                if match[1] == 'Index':
                    continue
                chunks.append((slug(match[1]), match[1], section))
        else:
            chunks = [(None, title, text)]
            if path.suffix != '.md':
                group = 'Linked files'
            elif source == 'docs/dollar-reference.md':
                group = 'Shared authoring'
            elif source.startswith('docs/studio-'):
                group = 'Studio'
            elif source.startswith('docs/paraview-'):
                group = 'ParaView guide'
                provider = 'paraview'
            elif path.stem.split('-')[0] in providers:
                provider = path.stem.split('-')[0]
                group = f'{provider} guide'
            elif source.startswith('docs/design/'):
                group = 'Design context'
        links[source] = {}
        for anchor, chunk_title, body in chunks:
            key = hashlib.sha256((source + '#' + (anchor or '')).encode()).hexdigest()[:20]
            hs = headings(body) if path.suffix == '.md' else []
            page = {'id': key, 'title': chunk_title, 'source': source, 'format': path.suffix[1:], 'body': body, 'headings': hs}
            pages[key] = page
            if anchor is None:
                links[source][''] = key
            for item in hs:
                links[source][item['anchor']] = key
            summary = next((line.strip() for line in body.splitlines() if line.strip() and not line.startswith(('#', '|', '```', '['))), '')[:220]
            operation = chunk_title if split and anchor else None
            projection = (discovery.operation_search_text(provider, operation)
                          if provider in discovery._declarations and operation in discovery._declarations[provider] else '')
            entries.append({'id': key, 'title': chunk_title, 'source': source, 'anchor': anchor or '',
                            'group': group, 'provider': provider, 'operation': chunk_title if split and anchor else None,
                            **({'capabilityId': operation_id(provider, operation)} if projection else {}),
                            'summary': summary, 'search': ' '.join(sorted(set(re.findall(r'[\w$.-]+', (body + ' ' + projection).lower()))))})
    links['docs/generated/paraview-operations.md'] = links[OPERATIONS]
    # Resolve packaged local navigation to topic IDs at build time.
    anchor_cache, link_errors = {}, []
    for page in pages.values():
        targets = {}
        for target in re.findall(r'\]\(([^)]+)\)', page['body']) if page['format'] == 'md' else []:
            raw = target.strip('<>')
            path, _, anchor = raw.partition('#')
            if re.match(r'^[a-z]+:', path):
                continue
            destination = ((ROOT / page['source']).parent / unquote(path)).resolve() if path else ROOT / page['source']
            if not destination.is_relative_to(ROOT):
                link_errors.append(page['source'] + ': ' + target + ' escapes repository')
                continue
            if not destination.exists():
                link_errors.append(page['source'] + ': ' + target + ' is missing')
                continue
            if anchor and destination.suffix == '.md':
                if destination not in anchor_cache:
                    anchor_cache[destination] = markdown_anchors(destination.read_text())
                if unquote(anchor) not in anchor_cache[destination]:
                    link_errors.append(page['source'] + ': ' + target + ' has no such anchor')
                    continue
            source = destination.relative_to(ROOT).as_posix()
            choices = links.get(source, {})
            key = choices.get(unquote(anchor)) if anchor else choices.get('')
            if key:
                targets[target] = {'id': key, 'anchor': unquote(anchor)}
        page['links'] = targets
    guides = {'workflow': 'workflow-authoring',
              'workflow-design': 'workflow-design'}
    guides = {provider: f'docs/{name}.md' for provider, name in guides.items()}
    # Adaptor guides come from the authoritative route delivery bundle.
    for provider in sorted(providers - set(guides)):
        manifest = json.loads((ROOT / 'src/schemaxis/adaptors' / provider / 'adaptor.json').read_text())
        readiness = ROOT / 'src/schemaxis/adaptors' / provider / 'readiness.json'
        route = json.loads(readiness.read_text())['routes'][manifest['version']] if readiness.is_file() else {}
        studio = ROOT / 'src/schemaxis/adaptors' / provider / 'studio.json'
        library = json.loads(studio.read_text()) if studio.is_file() else {}
        guide = library.get('helpGuide', route.get('guide'))
        if guide:
            guides[provider] = guide
    missing = sorted(providers - set(guides))
    if missing:
        raise SystemExit('Adaptors without a packaged Help guide: ' + ', '.join(missing))
    if link_errors:
        raise SystemExit('Broken local Help links: ' + '; '.join(sorted(set(link_errors))))
    def guide_topic(target):
        source, _, anchor = target.partition('#')
        if source not in links or anchor not in links[source]:
            raise SystemExit('Help guide target is absent: ' + target)
        return links[source][anchor]
    index = {'version': 1, 'guides': {provider: guide_topic(target) for provider, target in guides.items()}, 'home': links['docs/studio-guide.md'][''],
             'paraview': links['docs/paraview-guide.md'][''],
             'shared': links['docs/dollar-reference.md'][''], 'entries': entries}
    assets = {}
    for key, page in pages.items():
        if len(page['body'].encode()) > 100000:
            page['bodyGzip'] = base64.b64encode(gzip.compress(page.pop('body').encode(), mtime=0)).decode()
        assets[key + '.json'] = json.dumps(page, ensure_ascii=False, separators=(',', ':')) + '\n'
    assets['index.json'] = json.dumps(index, ensure_ascii=False, separators=(',', ':')) + '\n'
    if check:
        stale = [name for name, text in assets.items() if not (DEST / name).exists() or (DEST / name).read_text() != text]
        extra = {p.name for p in DEST.glob('*.json')} - set(assets)
        if stale or extra:
            raise SystemExit(f'Stale supplied help: {len(stale)} changed/missing, {len(extra)} extra. Run tools/generate_studio_help.py.')
        print(f'Verified {len(entries)} supplied help topics are current.')
        return
    DEST.mkdir(exist_ok=True)
    # Remove only previously generated JSON topic assets.
    for path in DEST.glob('*.json'):
        path.unlink()
    for name, text in assets.items():
        (DEST / name).write_text(text)
    print(f'Packaged {len(entries)} topics from {len(links)} files ({sum(p.stat().st_size for p in DEST.glob("*.json")):,} bytes).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check packaged help without rewriting assets')
    build(check=parser.parse_args().check)
