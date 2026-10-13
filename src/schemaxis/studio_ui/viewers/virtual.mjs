// Virtual scrolling arithmetic shared by the text and table viewers.
// Browsers cap element heights (about 16-33 million CSS pixels), so very long
// documents use a scaled scroll range: the scrollbar position maps
// proportionally onto the row range, while small scrolls stay row-exact.

export const MAX_SCROLL_HEIGHT = 8_000_000;

/** Height of the scroll sizer for rowCount rows. */
export function contentHeight(rowCount, rowHeight, maxHeight = MAX_SCROLL_HEIGHT) {
  return Math.min(rowCount * rowHeight, maxHeight);
}

/**
 * Compute which rows to render for a scroll position.
 * Returns {first, last, offset, top}: render rows first..last (inclusive),
 * with row `first` drawn at `offset` px (≤ 0) from the viewport top.
 * `top` is the fractional row index at the viewport top.
 */
export function visibleWindow({scrollTop, viewportHeight, rowHeight, rowCount, maxHeight = MAX_SCROLL_HEIGHT}) {
  if (rowCount <= 0 || rowHeight <= 0) {
    return {first: 0, last: -1, offset: 0, top: 0};
  }
  const top = topRowFor(scrollTop, viewportHeight, rowHeight, rowCount, maxHeight);
  const first = Math.max(0, Math.floor(top));
  const offset = -(top - first) * rowHeight;
  const visible = Math.ceil((viewportHeight - offset) / rowHeight);
  const last = Math.min(rowCount - 1, first + visible);
  return {first, last, offset, top};
}

/** Fractional row index at the top of the viewport for a scroll position. */
export function topRowFor(scrollTop, viewportHeight, rowHeight, rowCount, maxHeight = MAX_SCROLL_HEIGHT) {
  const total = rowCount * rowHeight;
  const height = contentHeight(rowCount, rowHeight, maxHeight);
  const clamped = Math.max(0, scrollTop);
  if (total <= height) {
    return clamped / rowHeight;
  }
  const scrollRange = Math.max(1, height - viewportHeight);
  const rowRange = Math.max(0, rowCount - viewportHeight / rowHeight);
  return Math.min(1, clamped / scrollRange) * rowRange;
}

/** Inverse of topRowFor: the scrollTop that puts fractional row `top` at the viewport top. */
export function scrollTopFor(top, viewportHeight, rowHeight, rowCount, maxHeight = MAX_SCROLL_HEIGHT) {
  const total = rowCount * rowHeight;
  const height = contentHeight(rowCount, rowHeight, maxHeight);
  if (total <= height) {
    return Math.max(0, top * rowHeight);
  }
  const scrollRange = Math.max(1, height - viewportHeight);
  const rowRange = Math.max(1, rowCount - viewportHeight / rowHeight);
  return Math.max(0, Math.min(scrollRange, (top / rowRange) * scrollRange));
}

/** scrollTop that brings `row` fully into view (or null when it already is). */
export function scrollToReveal(row, scrollTop, viewportHeight, rowHeight, rowCount, maxHeight = MAX_SCROLL_HEIGHT) {
  const top = topRowFor(scrollTop, viewportHeight, rowHeight, rowCount, maxHeight);
  const rowsVisible = viewportHeight / rowHeight;
  if (row < top) {
    return scrollTopFor(row, viewportHeight, rowHeight, rowCount, maxHeight);
  }
  if (row + 1 > top + rowsVisible) {
    return scrollTopFor(row + 1 - rowsVisible, viewportHeight, rowHeight, rowCount, maxHeight);
  }
  return null;
}

/** Index of the last element in a sorted numeric array that is ≤ value (binary search). */
export function upperIndex(sorted, value, length = sorted.length) {
  let low = 0;
  let high = length - 1;
  let found = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (sorted[middle] <= value) {
      found = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return found;
}
