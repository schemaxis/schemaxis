// Copyright (C) 2026 David L F Gaden
// Width-aware JSON layout. Formatting changes whitespace only.
export function formatJson(value, {indent = '  ', compact = false, width = 100} = {}) {
  if (!compact) return JSON.stringify(value, null, indent);
  const inline = (item) => {
    if (!item || typeof item !== 'object') return JSON.stringify(item);
    if (Array.isArray(item)) return '[' + item.map(inline).join(', ') + ']';
    return '{' + Object.entries(item).map(([key, child]) => JSON.stringify(key) + ': ' + inline(child)).join(', ') + '}';
  };
  function layout(item, depth, prefix = '') {
    const short = inline(item);
    if (indent.repeat(depth).length + prefix.length + short.length + 1 <= width) return short;
    if (!item || typeof item !== 'object' || !Object.keys(item).length) return short;
    const array = Array.isArray(item);
    const entries = Object.entries(item).map(([key, child]) => {
      const lead = array ? '' : JSON.stringify(key) + ': ';
      return indent.repeat(depth + 1) + lead + layout(child, depth + 1, lead);
    });
    return (array ? '[' : '{') + '\n' + entries.join(',\n') + '\n' + indent.repeat(depth) + (array ? ']' : '}');
  }
  return layout(value, 0);
}
