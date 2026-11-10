// Copyright (C) 2026 David L F Gaden
// Render packaged Markdown as DOM text, with no raw HTML or remote dependencies.
import {h, s} from '../../lib/dom.mjs';
import {blocks, diagram} from './model.mjs';

export function inline(text, page, navigate) {
  const parts = []; const expression = /(`[^`]+`|\*\*[^*]+\*\*|\[([^\]]+)\]\(([^)]+)\))/g;
  let offset = 0;
  for (const match of text.matchAll(expression)) {
    parts.push(text.slice(offset, match.index));
    if (match[0].startsWith('`')) parts.push(h('code', {}, match[0].slice(1, -1)));
    else if (match[0].startsWith('**')) parts.push(h('strong', {}, match[0].slice(2, -2)));
    else {
      const target = page.links?.[match[3]];
      if (target) parts.push(h('a', {href: `#help-${target.id}`, onClick: (event) => {
        event.preventDefault(); navigate(target);
      }}, match[2]));
      else if (/^https?:\/\//i.test(match[3])) parts.push(h('a', {href: match[3], target: '_blank', rel: 'noopener noreferrer'}, match[2]));
      else parts.push(h('span', {title: `Repository reference: ${match[3]}`}, match[2]));
    }
    offset = match.index + match[0].length;
  }
  parts.push(text.slice(offset));
  return parts;
}

function flowchart(text) {
  const graph = diagram(text);
  if (!graph.nodes.length) return h('pre', {}, text);
  const width = 760; const gap = 98; const height = graph.nodes.length * gap + 50;
  const positions = new Map(graph.nodes.map((node, i) => [node.id, {x: 60, y: 24 + i * gap}]));
  const svg = s('svg', {viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Workflow flow chart', class: 'help-diagram'},
    s('title', {}, 'Workflow flow chart'),
    s('defs', {}, s('marker', {id: 'help-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5,
      markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse'}, s('path', {d: 'M 0 0 L 10 5 L 0 10 z', fill: 'currentColor'}))));
  graph.edges.forEach((edge, i) => {
    const a = positions.get(edge.from), b = positions.get(edge.to);
    const consecutive = b.y - a.y === gap;
    const lane = 650 + (i % 5) * 18;
    const startY = a.y + 32, endY = b.y + 32;
    const d = consecutive ? `M 340 ${a.y + 64} L 340 ${b.y}`
      : `M 620 ${startY} H ${lane} V ${endY} H 620`;
    svg.append(s('path', {d, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.7, 'marker-end': 'url(#help-arrow)'}));
    if (edge.label) svg.append(s('text', {x: consecutive ? 355 : lane - 8, y: (startY + endY) / 2 - 5, class: 'help-edge-label'}, edge.label));
  });
  graph.nodes.forEach((node) => {
    const {x, y} = positions.get(node.id);
    const group = s('g', {}, s('title', {}, node.title));
    group.append(node.decision
      ? s('polygon', {points: `${x},${y + 32} ${x + 280},${y} ${x + 560},${y + 32} ${x + 280},${y + 64}`, class: 'help-flow-node'})
      : s('rect', {x, y, width: 560, height: 64, rx: 10, class: 'help-flow-node'}));
    const label = s('text', {x: x + 280, y: y + 37, 'text-anchor': 'middle'}, node.title);
    group.append(label); svg.append(group);
  });
  return h('figure', {class: 'help-flowchart'}, svg, h('details', {}, h('summary', {}, 'Flow chart source'), h('pre', {}, text)));
}

export function renderPage(page, navigate, notify, {omitParagraphs = []} = {}) {
  const article = h('article', {class: 'help-article'});
  if (page.format !== 'md') {
    article.append(h('h1', {}, page.title), code(page.body, page.format, notify)); return article;
  }
  for (const block of blocks(page.body)) {
    if (block.type === 'paragraph' && omitParagraphs.some(text => text
      && text.replace(/\s+/g, ' ').trim() === block.text.replace(/\s+/g, ' ').trim())) continue;
    if (block.type === 'heading') article.append(h(`h${block.level}`, {id: `help-${block.anchor}`, tabindex: '-1'}, ...inline(block.text, page, navigate)));
    else if (block.type === 'paragraph') article.append(h('p', {}, ...inline(block.text, page, navigate)));
    else if (block.type === 'code') article.append(block.language === 'mermaid' ? flowchart(block.text) : code(block.text, block.language, notify));
    else if (block.type === 'list') article.append(h(block.ordered ? 'ol' : 'ul', {}, block.items.map((item) => h('li', {}, ...inline(item, page, navigate)))));
    else if (block.type === 'table') article.append(h('div', {class: 'help-table-wrap'}, h('table', {},
      h('thead', {}, h('tr', {}, block.headers.map((cell) => h('th', {scope: 'col'}, ...inline(cell, page, navigate))))),
      h('tbody', {}, block.rows.map((row) => h('tr', {}, row.map((cell) => h('td', {}, ...inline(cell, page, navigate)))))))));
  }
  return article;
}

function code(text, language, notify, expanded = false) {
  if (text.length > 100000 && !expanded) {
    const container = h('div', {class: 'help-code'}, h('p', {},
      'This reference contains a large schema or source file. Download it or open its full text.'),
      h('button', {class: 'button small', onClick: () => container.replaceWith(code(text, language, notify, true))}, 'Show full text'),
      h('button', {class: 'button small', onClick: () => {
        const url = URL.createObjectURL(new Blob([text], {type: 'text/plain'}));
        const link = h('a', {href: url, download: `reference.${language || 'txt'}`});
        link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      }}, 'Download'));
    return container;
  }
  const button = h('button', {class: 'button small', onClick: async () => {
    try { await navigator.clipboard.writeText(text); button.textContent = 'Copied'; }
    catch { notify.warn('Could not copy', {body: 'Select the example text and copy it with your keyboard.'}); }
  }}, 'Copy');
  return h('div', {class: 'help-code'}, h('div', {class: 'help-code-header'}, h('span', {}, language || 'Example'), button),
    h('pre', {}, h('code', {}, text)));
}
