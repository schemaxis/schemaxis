// Display identity for adaptors: name, short mark and colour.

import {h} from '../lib/dom.mjs';

const IDENTITY = {
  paraview: {name: 'ParaView', mark: 'PV', colour: '#3a6fc4'},
  blender: {name: 'Blender', mark: 'Bl', colour: '#e87d0d'},
  freecad: {name: 'FreeCAD', mark: 'FC', colour: '#c0392b'},
  godot: {name: 'Godot', mark: 'Gd', colour: '#478cbf'},
  aseprite: {name: 'Aseprite', mark: 'As', colour: '#7d4fb3'},
  ffmpeg: {name: 'FFmpeg', mark: 'FF', colour: '#2f8f3a'},
  qgis: {name: 'QGIS', mark: 'QG', colour: '#589632'},
  gmsh: {name: 'Gmsh', mark: 'Gm', colour: '#2f8f83'},
  cantera: {name: 'Cantera', mark: 'Ct', colour: '#b5523b'},
  ngspice: {name: 'ngspice', mark: 'Ng', colour: '#5a6b7d'},
  octave: {name: 'Octave', mark: 'Oc', colour: '#0790c0'},
  calc: {name: 'LibreOffice Calc', mark: 'Ca', colour: '#18a303'},
  workflow: {name: 'Workflow', mark: 'Wf', colour: '#4b5563'},
  'workflow-design': {name: 'Workflow design', mark: 'WD', colour: '#4b5563'},
};

// Identities served by the host from each manifest's optional `display` key.
// They take precedence, so installed external adaptor packages need no Studio edit.
const REGISTERED = new Map();

const COLOUR = /^#[0-9a-fA-F]{6}$/;

/** Record `display` metadata from the /api/adaptors list; invalid parts are ignored. */
export function registerIdentities(adaptors) {
  REGISTERED.clear();
  for (const item of adaptors || []) {
    const display = item && item.display;
    if (!item || typeof item.id !== 'string' || !display || typeof display.name !== 'string' || !display.name.trim()) {
      continue;
    }
    const fallback = generated(item.id);
    REGISTERED.set(item.id, {
      name: display.name.trim(),
      mark: typeof display.mark === 'string' && display.mark.trim() ? display.mark.trim().slice(0, 3) : markFor(display.name.trim()),
      colour: typeof display.colour === 'string' && COLOUR.test(display.colour) ? display.colour : fallback.colour,
    });
  }
}

function markFor(text) {
  const words = String(text).split(/[^A-Za-z0-9]+/).filter(Boolean);
  if (words.length > 1) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  const mark = (words[0] || '?').slice(0, 2);
  return mark.charAt(0).toUpperCase() + mark.slice(1);
}

/** A stable, readable identity for an adaptor this Studio build has never seen. */
export function generated(provider) {
  const id = String(provider || '?');
  const name = id.split(/[_-]+/).filter(Boolean).map((word) => word[0].toUpperCase() + word.slice(1)).join(' ') || id;
  let hash = 0;
  for (const character of id) {
    hash = (hash * 31 + character.codePointAt(0)) >>> 0;
  }
  // Fixed saturation and lightness keep white marks legible on every hue.
  return {name, mark: markFor(name), colour: hsl(hash % 360, 0.45, 0.38)};
}

function hsl(hue, saturation, lightness) {
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const part = chroma * (1 - Math.abs((hue / 60) % 2 - 1));
  const [r, g, b] = hue < 60 ? [chroma, part, 0] : hue < 120 ? [part, chroma, 0] : hue < 180 ? [0, chroma, part]
    : hue < 240 ? [0, part, chroma] : hue < 300 ? [part, 0, chroma] : [chroma, 0, part];
  const offset = lightness - chroma / 2;
  return '#' + [r, g, b].map((value) => Math.round((value + offset) * 255).toString(16).padStart(2, '0')).join('');
}

export function identity(provider) {
  return REGISTERED.get(provider) || IDENTITY[provider] || generated(provider);
}

export function avatar(provider, {large = false} = {}) {
  const info = identity(provider);
  return h('span', {class: ['avatar', large && 'large'], style: {'--avatar': info.colour}, 'aria-hidden': 'true'},
    info.mark);
}

/** Which Studio window edits a document of this provider. */
export function windowFor(provider) {
  if (provider === 'workflow-design') {
    return 'designer';
  }
  if (provider === 'workflow') {
    return 'schema-editor';
  }
  return 'workbench';
}
