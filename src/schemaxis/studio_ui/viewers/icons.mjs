// Inline 16 px line icons for viewer toolbars (stroke = currentColor).
// Kept local so viewers work without the shell's sprite sheet.

import {s} from '../lib/dom.mjs';

const PATHS = {
  alert: 'M8 2.5 14.5 13.5h-13ZM8 6.5v3.5M8 11.8v.2',
  cube: 'M8 1.8 13.5 4.8v6.4L8 14.2 2.5 11.2V4.8ZM2.5 4.8 8 7.8l5.5-3M8 7.8v6.4',
  image: 'M2 3h12v10H2ZM2 11l3.5-3.5 3 3L11 8l3 3M10.5 5.5h.01',
  text: 'M3 3.5h10M3 6.5h10M3 9.5h7M3 12.5h9',
  table: 'M2 3h12v10H2ZM2 6.3h12M2 9.6h12M6 3v10M10 3v10',
  fit: 'M2 5.5V2h3.5M10.5 2H14v3.5M14 10.5V14h-3.5M5.5 14H2v-3.5M5.5 5.5h5v5h-5Z',
  home: 'M2.5 7.5 8 2.5l5.5 5M4 6.5V13.5h8V6.5',
  'zoom-in': 'M7 2.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9ZM10.3 10.3 14 14M5 7h4M7 5v4',
  'zoom-out': 'M7 2.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9ZM10.3 10.3 14 14M5 7h4',
  wireframe: 'M2.5 3h11v10h-11ZM2.5 3l11 10M8 3v10M2.5 8h11',
  section: 'M3 13 13 3M2 6.5 6.5 2M9.5 14 14 9.5M5 5l6 6',
  flip: 'M3 5.5h9l-2.5-2.5M13 10.5H4l2.5 2.5',
  perspective: 'M2 3.5 14 2v12L2 12.5ZM6 3v10M10 2.5v11',
  orthographic: 'M2.5 3h11v10h-11ZM6.2 3v10M9.8 3v10',
  walk: 'M8.5 2.5a1.2 1.2 0 1 1 0 .01M7 5.5l-2 3 2 1v4.5M7 5.5l3 1.5 1.5 2M8.5 9.5l2 4.5',
  orbit: 'M8 6.5a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3ZM14 8c0 1.9-2.7 3.5-6 3.5S2 9.9 2 8s2.7-3.5 6-3.5c1.4 0 2.7.3 3.7.8M10.5 3.6l1.3 1.7-2 .6',
  search: 'M7 2.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9ZM10.3 10.3 14 14',
  prev: 'M10 3.5 5.5 8l4.5 4.5',
  next: 'M6 3.5 10.5 8 6 12.5',
  up: 'M3.5 10 8 5.5l4.5 4.5',
  down: 'M3.5 6 8 10.5 12.5 6',
  first: 'M4 3v10M11.5 3.5 7 8l4.5 4.5',
  last: 'M12 3v10M4.5 3.5 9 8l-4.5 4.5',
  play: 'M4.5 3v10l8-5Z',
  pause: 'M5 3v10M11 3v10',
  grid: 'M2 2h12v12H2ZM6 2v12M10 2v12M2 6h12M2 10h12',
  close: 'M4 4l8 8M12 4l-8 8',
  copy: 'M5.5 5.5h8v8h-8ZM10.5 5.5v-3h-8v8h3',
  plot: 'M2 2v12h12M4.5 10.5l3-3.5 2.5 2 4-5',
  stats: 'M3 13V8M6.5 13V4M10 13V7M13.5 13V10',
  extract: 'M3 3h10M3 6h4M3 9h4M3 12h4M9.5 7.5h4v5h-4ZM9.5 10h4',
  regex: 'M10.5 2.5v5M8.3 3.7l4.4 2.6M8.3 6.3l4.4-2.6M3.5 11.5h2v2h-2Z',
  case: 'M1.5 12 4.5 4l3 8M2.6 9.3h3.8M12.5 8.2a2 2 0 1 0 0 3.6M14.5 7.5V12',
  pixel: 'M3 3h4v4H3ZM9 9h4v4H9Z',
  actual: 'M3 4.5 5 3v10M9.5 6.5v.01M9.5 10.5v.01M12 4.5 14 3v10',
  sort: 'M5 3v10M2.5 10.5 5 13l2.5-2.5M11 13V3M8.5 5.5 11 3l2.5 2.5',
  edit: 'M10.5 2.5l3 3L6 13H3v-3Z',
  line: 'M2 8h12',
};

/** Create a 16 px icon element for a known name (unknown names render empty). */
export function viewerIcon(name) {
  return s('svg', {class: 'vw-icon', viewBox: '0 0 16 16', 'aria-hidden': 'true', focusable: 'false'},
    s('path', {d: PATHS[name] || '', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.4',
      'stroke-linecap': 'round', 'stroke-linejoin': 'round'}));
}
