"""Offline link syntax and Markdown anchor checks, without availability claims."""
import re
from urllib.parse import urlsplit


def url_syntax(reference):
    try:
        parsed = urlsplit(reference)
        return (parsed.scheme in ('http', 'https') and bool(parsed.hostname)
                and parsed.port != 0 and not parsed.username and not parsed.password
                and not any(c.isspace() for c in reference)
                and not parsed.hostname.endswith('.invalid'))
    except (TypeError, ValueError):
        return False


def markdown_anchors(text):
    counts, anchors, fence = {}, set(), None
    for line in text.splitlines():
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
            continue
        heading = re.match(r'^#{1,6}\s+(.+?)\s*#*$', line) if fence is None else None
        if heading:
            slug = re.sub(r'[^\w\s-]', '', heading[1].strip().lower()).replace(' ', '-')
            count = counts.get(slug, 0)
            counts[slug] = count + 1
            anchors.add(slug + ('-' + str(count) if count else ''))
    anchors.update(re.findall(r'<a\s+(?:id|name)=[\"\']([^\"\']+)', text))
    return anchors
