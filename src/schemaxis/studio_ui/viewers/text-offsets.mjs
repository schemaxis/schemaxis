// Textareas normalise CRLF/CR to LF and expose UTF-16 offsets. Immutable
// inspection snapshots count Unicode code points in the original source.

/** Convert an original snapshot code-point offset to a normalised DOM offset. */
export function domOffset(source, codePointOffset) {
  return Array.from(source).slice(0, codePointOffset).join('').replace(/\r\n?/g, '\n').length;
}

/** Convert a normalised DOM UTF-16 offset to an original snapshot code-point offset. */
export function snapshotOffset(source, offset) {
  let dom = 0;
  let points = 0;
  for (let i = 0; i < source.length && dom < offset;) {
    const value = source.codePointAt(i);
    const width = value > 0xffff ? 2 : 1;
    if (value === 13 && source[i + 1] === '\n') {
      i += 2;
      points += 2;
      dom++;
    } else {
      i += width;
      points++;
      dom += width;
    }
  }
  return points;
}
