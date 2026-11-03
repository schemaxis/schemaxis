// Copyright (C) 2026 David L F Gaden
// Toolbar and axis triad for the 3D viewer. The viewer owns state; these
// helpers build DOM with h()/s() and call back through `actions`.

import {h, s} from '../lib/dom.mjs';
import {separator, setPressed, spacer, toolButton, toolSelect} from './common.mjs';
import {VIEWS} from './camera.mjs';
import {dot} from './geometry.mjs';
import {viewerIcon} from './icons.mjs';

/**
 * actions: {fit, view(name), projection(mode), navigation(mode), speed(value), wireframe(on),
 *           sectionAxis(axis|-1), sectionPosition(value), flip()}
 * Returns {element: DocumentFragment-like array, update(state)}.
 */
export function buildToolbar(actions) {
  const fit = toolButton({icon: 'fit', title: 'Fit view (F)', onClick: actions.fit});
  const viewButtons = Object.entries(VIEWS).map(([name, view]) => h('button', {
    type: 'button',
    class: 'vw-seg-btn',
    title: `${view.label} view (${name === 'iso' ? '0' : '1–6'})`,
    'aria-label': `${view.label} view`,
    onClick: () => actions.view(name),
  }, name === 'iso' ? 'Iso' : view.label.split(' ')[0]));
  const views = h('div', {class: 'vw-seg', role: 'group', 'aria-label': 'Standard views'}, viewButtons);

  const perspective = toolButton({icon: 'perspective', title: 'Perspective projection (P)', pressed: false,
    onClick: () => actions.projection(perspective.getAttribute('aria-pressed') === 'true' ? 'orthographic' : 'perspective')});
  const navigation = toolSelect({label: 'Navigation', value: 'orbit',
    options: [['orbit', 'Orbit'], ['walk', 'Walk (WASD)']], onChange: actions.navigation});
  const speed = h('input', {type: 'range', class: 'vw-range vw-range-short', min: '0.05', max: '5', step: '0.05',
    value: '1', 'aria-label': 'Walking speed, model radii per second', title: 'Walking speed'});
  speed.addEventListener('input', () => actions.speed(Number(speed.value)));
  const speedGroup = h('label', {class: 'vw-field', hidden: true}, h('span', {}, 'Speed'), speed);

  const wireframe = toolButton({icon: 'wireframe', title: 'Wireframe overlay', pressed: false,
    onClick: () => actions.wireframe(wireframe.getAttribute('aria-pressed') !== 'true')});

  const sectionAxis = toolSelect({label: 'Section plane', value: 'off',
    options: [['off', 'No section'], ['0', 'Section X'], ['1', 'Section Y'], ['2', 'Section Z']],
    onChange: (value) => actions.sectionAxis(value === 'off' ? -1 : Number(value))});
  const sectionPosition = h('input', {type: 'range', class: 'vw-range', min: '-1', max: '1', step: '0.001',
    value: '0', disabled: true, 'aria-label': 'Section plane position'});
  sectionPosition.addEventListener('input', () => actions.sectionPosition(Number(sectionPosition.value)));
  const sectionValue = h('output', {class: 'vw-readout vw-mono'}, '');
  const flip = toolButton({icon: 'flip', title: 'Flip kept side', pressed: false, onClick: actions.flip});
  flip.disabled = true;

  const element = [fit, views, separator(), perspective, navigation, speedGroup, separator(), wireframe,
    separator(), h('span', {class: 'vw-icon-label', 'aria-hidden': 'true'}, viewerIcon('section')), sectionAxis, sectionPosition,
    sectionValue, flip, spacer()];

  function update(state) {
    setPressed(perspective, state.perspective);
    perspective.disabled = state.navigation === 'walk';
    navigation.value = state.navigation;
    speedGroup.hidden = state.navigation !== 'walk';
    speed.value = String(state.speed);
    setPressed(wireframe, state.wireframe);
    wireframe.disabled = !state.wireframeAvailable;
    sectionAxis.value = state.axis < 0 ? 'off' : String(state.axis);
    sectionPosition.disabled = state.axis < 0;
    flip.disabled = state.axis < 0;
    setPressed(flip, state.side < 0);
    if (state.axis >= 0) {
      sectionPosition.min = String(state.sectionMin);
      sectionPosition.max = String(state.sectionMax);
      sectionPosition.step = String(Math.max((state.sectionMax - state.sectionMin) / 500, 1e-6));
      sectionPosition.value = String(state.cut);
    }
    sectionValue.textContent = state.sectionLabel;
  }

  return {element, update};
}

const AXES = [
  {name: 'X', vector: [1, 0, 0], view: '+x', className: 'vw-axis-x'},
  {name: 'Y', vector: [0, 1, 0], view: '+y', className: 'vw-axis-y'},
  {name: 'Z', vector: [0, 0, 1], view: '+z', className: 'vw-axis-z'},
];

/** Axis triad in a corner. Clicking an axis label snaps to that view. */
export function createGizmo(onView) {
  const size = 76;
  const centre = size / 2;
  const reach = 25;
  const group = s('g', {});
  const svg = s('svg', {class: 'vw-gizmo', viewBox: `0 0 ${size} ${size}`, width: size, height: size,
    role: 'group', 'aria-label': 'Axis triad'}, s('circle', {class: 'vw-gizmo-bg', cx: centre, cy: centre, r: 35}),
  group);

  function update({right, up, forward}) {
    const items = AXES.map((axis) => ({
      ...axis,
      x: centre + dot(axis.vector, right) * reach,
      y: centre - dot(axis.vector, up) * reach,
      depth: dot(axis.vector, forward),
    })).sort((a, b) => a.depth - b.depth);
    group.replaceChildren(...items.flatMap((axis) => [
      s('line', {class: ['vw-gizmo-axis', axis.className], x1: centre, y1: centre, x2: axis.x, y2: axis.y}),
      s('g', {class: ['vw-gizmo-tip', axis.className], tabindex: '-1', onClick: () => onView(axis.view)},
        s('title', {}, `View from +${axis.name}`),
        s('circle', {cx: axis.x, cy: axis.y, r: 8}),
        s('text', {x: axis.x, y: axis.y, 'text-anchor': 'middle', 'dominant-baseline': 'central'}, axis.name)),
    ]));
  }

  return {element: svg, update};
}
