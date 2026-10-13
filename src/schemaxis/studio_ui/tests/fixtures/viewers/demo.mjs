// Mounts all four viewers with fixture data. Query: ?only=3d|image|text|table&theme=dark&lines=200000
import {createChip} from '../../../viewers/chip.mjs';

const params = new URLSearchParams(location.search);
const only = params.get('only');
const status = document.getElementById('demo-status');
const chips = document.getElementById('demo-chips');
const viewers = {};
window.demo = {viewers, picks: [], extracts: [], errors: []};

if (params.get('theme') === 'dark') {
  document.documentElement.dataset.theme = 'dark';
}
document.getElementById('demo-theme').addEventListener('click', () => {
  const dark = document.documentElement.dataset.theme !== 'dark';
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  document.dispatchEvent(new CustomEvent('themechange', {detail: {theme: dark ? 'dark' : 'light'}}));
});
if (only) {
  document.querySelector('.demo-grid').classList.add('demo-only');
  for (const cell of document.querySelectorAll('.demo-cell')) {
    cell.hidden = cell.id !== `slot-${only}`;
  }
}

function addChip(reference) {
  window.demo.picks.push(reference);
  chips.append(createChip({reference}));
}

/** Deterministic OpenFOAM-like solver log. */
export function syntheticLog(steps) {
  const lines = ['/*---------------------------------------------------------------------------*\\',
    '  =========                 |', '  \\\\      /  F ield         | OpenFOAM-like synthetic log', 'Build  : demo',
    'Exec   : simpleFoam -parallel', 'Starting time loop', ''];
  let residual = 1;
  for (let step = 1; lines.length < steps; step++) {
    residual *= 0.985 + 0.01 * Math.sin(step / 7);
    const time = (step * 0.005).toFixed(3).replace(/\.?0+$/, '');
    lines.push(`Time = ${time}`, '');
    for (const [field, factor] of [['Ux', 1], ['Uy', 1.7], ['Uz', 0.6], ['p', 4.2], ['k', 0.3]]) {
      const initial = (residual * factor * (1 + 0.15 * Math.cos(step + factor))).toExponential(4);
      const final = (residual * factor * 0.01).toExponential(3);
      const iterations = field === 'p' ? 12 + (step % 5) : 1 + (step % 3);
      lines.push(`smoothSolver:  Solving for ${field}, Initial residual = ${initial}, `
        + `Final residual = ${final}, No Iterations ${iterations}`);
    }
    lines.push(`ExecutionTime = ${(step * 0.41).toFixed(2)} s  ClockTime = ${Math.round(step * 0.43)} s`, '');
  }
  lines.length = steps;
  return lines.join('\n');
}

async function mount(name, path, factory, setup) {
  if (only && only !== name) {
    return;
  }
  try {
    const module = await import(path);
    const viewer = module[factory](document.getElementById(`slot-${name}`), {});
    viewers[name] = viewer;
    viewer.on('pick', addChip);
    viewer.on('error', (error) => window.demo.errors.push(error));
    await setup(viewer);
  } catch (error) {
    window.demo.errors.push({name, message: String(error?.stack || error)});
    console.error(error);
  }
}

await Promise.all([
  mount('3d', '../../../viewers/viewer3d.mjs', 'createViewer3d', async (viewer) => {
    await viewer.load(fetch('mesh.json').then((response) => response.json()));
  }),
  mount('image', '../../../viewers/image.mjs', 'createImageViewer', async (viewer) => {
    await viewer.load({src: 'sample.png', name: 'sample.png'});
  }),
  mount('text', '../../../viewers/text.mjs', 'createTextViewer', async (viewer) => {
    viewer.on('extract', (table) => window.demo.extracts.push(table));
    viewer.on('openTable', (table) => viewers.table?.load(table));
    await viewer.load({text: syntheticLog(Number(params.get('lines') || 200000)), name: 'log.simpleFoam'});
  }),
  mount('table', '../../../viewers/table.mjs', 'createTableViewer', async (viewer) => {
    await viewer.load({csv: await (await fetch('sample.csv')).text(), name: 'sample.csv'});
  }),
]);
status.textContent = window.demo.errors.length ? `${window.demo.errors.length} error(s)` : 'Ready';
window.demo.ready = true;
