// Pure help navigation, Markdown blocks and bounded search.
export function slug(text) {
  return text.trim().toLowerCase().replace(/[^\p{L}\p{N}_\s-]/gu, '').replace(/ /g, '-');
}

export function searchTopics(entries, query, group = '') {
  const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  // Prose supports word prefixes, but "place" must not match "replaces".
  // Keep partial title matches for native identifiers such as pvClip.
  const proseTerms = terms.map((term) => {
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(`(?:^|[^\\p{L}\\p{N}_])${escaped}`, 'u');
  });
  return entries.filter((item) => (!group || item.group === group)
    && terms.every((term, index) => item.title.toLowerCase().includes(term)
      || proseTerms[index].test(item.search)))
    .map((item) => ({item, score: terms.reduce((score, term) => score
      + (item.title.toLowerCase() === term ? 10 : item.title.toLowerCase().includes(term) ? 5 : 0), 0)}))
    .sort((a, b) => b.score - a.score || a.item.title.localeCompare(b.item.title))
    .map(({item}) => item);
}

export function contextTopic(index, {provider, operation} = {}) {
  return index.entries.find((entry) => entry.provider === provider && entry.operation === operation && operation)
    || index.entries.find((entry) => entry.id === index.guides?.[provider])
    || index.entries.find((entry) => entry.provider === provider && !entry.operation && entry.source.endsWith('-guide.md'))
    || index.entries.find((entry) => entry.provider === provider && !entry.operation)
    || index.entries.find((entry) => entry.id === index.home);
}

export function cells(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/)
    .map((cell) => cell.trim().replace(/\\\|/g, '|'));
}

export function blocks(text) {
  const lines = text.split('\n');
  const result = []; const counts = {};
  for (let i = 0; i < lines.length;) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (line.startsWith('```')) {
      const language = line.slice(3).trim(); const body = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) body.push(lines[i++]);
      i++;
      result.push({type: 'code', language, text: body.join('\n')}); continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const base = slug(heading[2]); const count = counts[base] || 0; counts[base] = count + 1;
      result.push({type: 'heading', level: heading[1].length, text: heading[2], anchor: base + (count ? `-${count}` : '')});
      i++; continue;
    }
    if (line.startsWith('|') && /^\s*\|?[\s:|-]+\|\s*$/.test(lines[i + 1] || '')) {
      const headers = cells(line); const rows = []; i += 2;
      while (i < lines.length && lines[i].startsWith('|')) rows.push(cells(lines[i++]));
      result.push({type: 'table', headers, rows}); continue;
    }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line); const items = [];
      const pattern = ordered ? /^\s*\d+\.\s+/ : /^\s*[-*]\s+/;
      while (i < lines.length && pattern.test(lines[i])) items.push(lines[i++].replace(pattern, ''));
      result.push({type: 'list', ordered, items}); continue;
    }
    const paragraph = [line]; i++;
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|\||\s*[-*]\s|\s*\d+\.\s)/.test(lines[i])) paragraph.push(lines[i++]);
    result.push({type: 'paragraph', text: paragraph.join(' ')});
  }
  return result;
}

export function diagram(text) {
  const nodes = new Map(); const edges = [];
  for (const line of text.split('\n')) {
    const match = line.trim().match(/^(\w+)(?:\[([^\]]+)\]|\{([^}]+)\})?\s*-->(?:\|([^|]+)\|)?\s*(\w+)(?:\[([^\]]+)\]|\{([^}]+)\})?$/);
    if (!match) continue;
    const [, from, label1, decision1, label, to, label2, decision2] = match;
    for (const [id, title, decision] of [[from, label1 || decision1, decision1], [to, label2 || decision2, decision2]]) {
      if (!nodes.has(id) || title) nodes.set(id, {id, title: title || id, decision: Boolean(decision)});
    }
    edges.push({from, to, label: label || ''});
  }
  return {nodes: [...nodes.values()], edges};
}

/** Expand large packaged schema/source pages only when selected. */
export async function decodePage(page) {
  if (!page.bodyGzip) return page;
  const bytes = Uint8Array.from(atob(page.bodyGzip), (character) => character.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
  return {...page, body: await new Response(stream).text()};
}
