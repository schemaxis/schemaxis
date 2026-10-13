// Resolve the backend's mixed $.object/array/index locations to the closest authored JSON pointer.

export function sourcePointer(location, document) {
  if (!location || location === '$') return '';
  if (location.startsWith('/')) return location;
  let remaining = location.replace(/^\$\.?/, '').replace(/\[(\d+)\]/g, '/$1');
  let value = document;
  const parts = [];
  while (remaining && value && typeof value === 'object') {
    remaining = remaining.replace(/^[./]/, '');
    const key = Object.keys(value).sort((a, b) => b.length - a.length).find((candidate) =>
      remaining === candidate || remaining.startsWith(candidate + '.') || remaining.startsWith(candidate + '/'));
    if (key === undefined) break;
    parts.push(key.replaceAll('~', '~0').replaceAll('/', '~1'));
    remaining = remaining.slice(key.length);
    value = value[key];
  }
  return parts.length ? '/' + parts.join('/') : '';
}
