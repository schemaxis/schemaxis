// Copyright (C) 2026 David L F Gaden
// 3D Viewer: native faces, edges and vertices with orbit / walk navigation,
// section plane, wireframe overlay, hover highlight and truthful picking.
//
//   const viewer = createViewer3d(container, {label});
//   viewer.load(geometryPayload | Promise);  viewer.on('pick', (ref) => ...);
//
// Pick payload: {type: 'face'|'edge'|'vertex', object, subelement, point: [x, y, z] (world),
//   revision, document?, label, objectLabel, source: 'pointer'|'keyboard'}

import {h} from '../lib/dom.mjs';
import {createEmitter, createFrame, readTokens, watchTheme} from './common.mjs';
import {blendCameras, createCamera, fitCamera, setNavigation, viewCamera} from './camera.mjs';
import {elementPoint, ensureBvh, prepareGeometry} from './geometry.mjs';
import {
  describeElement, drawParameters, nextSection, PALETTE_TOKENS, paletteFromTokens, pickAt, projectWorld, referenceFor,
  sectionPosition, toolbarState,
} from './viewer3d-scene.mjs';
import {createRenderer} from './viewer3d-gl.mjs';
import {buildToolbar, createGizmo} from './viewer3d-controls.mjs';
import {attachNavigation} from './viewer3d-input.mjs';

export function createViewer3d(container, options = {}) {
  const events = createEmitter();
  const frame = createFrame(container, {kind: 'viewer3d', label: options.label || '3D Viewer',
    emptyMessage: options.emptyMessage || 'No geometry loaded'});
  const canvas = h('canvas', {class: 'vw-canvas', tabindex: '0', 'aria-label': '3D view. Drag or arrow keys '
    + 'rotate, Shift pans, wheel or plus/minus zooms, F fits, 0–6 snap views, P toggles perspective, '
    + '[ and ] step through elements, Enter references the selected element.'});
  const gizmo = createGizmo((name) => setView(name));
  const hint = h('div', {class: 'vw-hint'});
  frame.body.append(canvas, gizmo.element, hint);
  const statusLeft = h('span', {class: 'vw-status-main'}, 'No element selected');
  const statusRight = h('span', {class: 'vw-status-meta'});
  frame.status.append(statusLeft, statusRight);

  let renderer = null;
  let mesh = null;
  let camera = createCamera();
  let section = {axis: -1, cut: 0, side: 1};
  let wireframe = false;
  let selected = -1;
  let hovered = -1;
  let colours = null;
  let frameRequest = 0;
  let animation = null;
  let hoverPoint = null;
  let hoverRequest = 0;
  let loadToken = 0;
  let needsFit = true;

  const toolbar = buildToolbar({
    fit: () => fit(),
    view: (name) => setView(name),
    projection: (mode) => setProjection(mode),
    navigation: (mode) => setNavigationMode(mode),
    speed: (value) => {
      camera = {...camera, speed: value};
    },
    wireframe: (on) => setWireframe(on),
    sectionAxis: (axis) => setSection({axis}),
    sectionPosition: (cut) => setSection({cut}),
    flip: () => setSection({side: -section.side}),
  });
  frame.toolbar.append(...toolbar.element);

  try {
    renderer = createRenderer(canvas);
  } catch (error) {
    frame.setState('error', error.message);
  }

  // ---- rendering -------------------------------------------------------

  const aspect = () => canvas.clientWidth / Math.max(1, canvas.clientHeight);

  function readColours() {
    colours = paletteFromTokens(readTokens(frame.root, PALETTE_TOKENS));
  }

  function invalidate() {
    if (!frameRequest) {
      frameRequest = requestAnimationFrame(render);
    }
  }

  function render() {
    frameRequest = 0;
    if (animation) {
      const t = Math.min(1, (performance.now() - animation.start) / animation.duration);
      const eased = 1 - (1 - t) ** 3;
      camera = t >= 1 ? animation.to : blendCameras(animation.from, animation.to, eased);
      if (t >= 1) {
        animation = null;
      } else {
        invalidate();
      }
    }
    const view = drawParameters(camera, aspect());
    gizmo.update(view);
    if (!renderer || !colours) {
      return;
    }
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    renderer.draw({
      ...view,
      pointSize: 7 * dpr,
      axis: section.axis,
      cut: section.cut,
      side: section.side,
      selected,
      hovered,
      wireframe,
      colours,
    }, dpr);
  }

  function updateToolbar() {
    toolbar.update(toolbarState(camera, section, mesh, wireframe, Boolean(renderer?.derivatives)));
    hint.textContent = camera.navigation === 'walk'
      ? 'WASD move · Q/E down/up · Drag look · Shift-drag pan · Click reference'
      : 'Drag rotate · Shift/right-drag pan · Wheel zoom · F fit · Click reference';
  }

  function animateTo(next) {
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced || !mesh) {
      camera = next;
      animation = null;
    } else {
      animation = {from: camera, to: next, start: performance.now(), duration: 220};
    }
    invalidate();
  }

  // ---- picking ---------------------------------------------------------

  function viewAt(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const nx = (2 * (clientX - rect.left)) / rect.width - 1;
    const ny = 1 - (2 * (clientY - rect.top)) / rect.height;
    return {rect, nx, ny};
  }

  function hitAt(clientX, clientY) {
    if (!mesh || renderer?.lost) {
      return null;
    }
    const {rect, nx, ny} = viewAt(clientX, clientY);
    return pickAt(mesh, camera, section, nx, ny, rect.width / rect.height, rect.height);
  }

  const reference = (element, point, source) => referenceFor(mesh, element, point, source);
  const describe = describeElement;

  function emitPick(element, point, source) {
    selected = element.index;
    statusLeft.textContent = describe(element);
    invalidate();
    events.emit('pick', reference(element, point, source));
  }

  function hoverAt(clientX, clientY) {
    hoverPoint = [clientX, clientY];
    if (hoverRequest) {
      return;
    }
    hoverRequest = requestAnimationFrame(() => {
      hoverRequest = 0;
      const [x, y] = hoverPoint;
      const hit = hitAt(x, y);
      const index = hit ? hit.element.index : -1;
      canvas.classList.toggle('vw-can-pick', index >= 0);
      if (index !== hovered) {
        hovered = index;
        statusLeft.textContent = hit ? describe(hit.element) : describe(mesh?.elements[selected]);
        events.emit('hover', hit ? reference(hit.element, hit.point, 'pointer') : null);
        invalidate();
      }
    });
  }

  // ---- input -----------------------------------------------------------

  const navigation = attachNavigation(canvas, {
    getCamera: () => camera,
    setCamera: (next) => {
      animation = null;
      camera = next;
    },
    invalidate,
    render,
    aspect,
    ndcAt: (x, y) => viewAt(x, y),
    click: (x, y) => {
      const hit = hitAt(x, y);
      if (hit) {
        emitPick(hit.element, hit.point, 'pointer');
      } else {
        statusLeft.textContent = 'No native element at this point';
      }
    },
    hover: hoverAt,
    leave: () => {
      if (hovered >= 0) {
        hovered = -1;
        statusLeft.textContent = describe(mesh?.elements[selected]);
        events.emit('hover', null);
        invalidate();
      }
    },
    fit: () => fit(),
    view: (name) => setView(name),
    toggleProjection: () => setProjection(camera.projection === 'perspective' ? 'orthographic' : 'perspective'),
    step: (direction) => stepSelection(direction),
    referenceSelected: () => referenceSelected(),
    clearSelection: () => select(null),
  });

  function stepSelection(direction) {
    if (!mesh?.elements.length) {
      return;
    }
    const count = mesh.elements.length;
    selected = selected < 0 ? (direction > 0 ? 0 : count - 1) : (selected + direction + count) % count;
    statusLeft.textContent = `${describe(mesh.elements[selected])} — Enter to reference`;
  }

  function referenceSelected() {
    const element = mesh?.elements[selected];
    if (!element) {
      return;
    }
    const point = elementPoint(mesh, element, section.axis, section.cut, section.side);
    if (!point) {
      statusLeft.textContent = 'This element is fully clipped. Move or turn off the section plane.';
      return;
    }
    emitPick(element, point, 'keyboard');
  }

  canvas.addEventListener('webglcontextlost', (event) => {
    event.preventDefault();
    renderer?.contextLost();
    frame.setState('loading', 'Graphics context lost; waiting for recovery…');
  });
  canvas.addEventListener('webglcontextrestored', () => {
    renderer?.contextRestored();
    frame.setState(mesh ? 'ready' : 'empty');
    invalidate();
  });

  const resizeObserver = new ResizeObserver(() => resize());
  resizeObserver.observe(frame.body);
  const stopTheme = watchTheme(() => setTheme());

  // ---- public API ------------------------------------------------------

  function resize() {
    if (needsFit && mesh && canvas.clientWidth > 0 && canvas.clientHeight > 0) {
      needsFit = false;
      camera = fitCamera(camera, aspect(), mesh?.bounds);
    }
    invalidate();
  }

  function fit() {
    animateTo(fitCamera(camera, aspect(), mesh?.bounds));
  }

  function setView(name) {
    animateTo(fitCamera(viewCamera(camera, name), aspect(), mesh?.bounds));
    canvas.focus({preventScroll: true});
  }

  function setProjection(mode) {
    camera = {...camera, projection: mode === 'perspective' ? 'perspective' : 'orthographic'};
    updateToolbar();
    invalidate();
  }

  function setNavigationMode(mode) {
    navigation.clearKeys();
    camera = setNavigation(camera, mode === 'walk' ? 'walk' : 'orbit');
    updateToolbar();
    invalidate();
    canvas.focus({preventScroll: true});
  }

  function setWireframe(on) {
    wireframe = Boolean(on) && Boolean(renderer?.derivatives);
    updateToolbar();
    invalidate();
  }

  /** See nextSection() in viewer3d-scene.mjs for the accepted change fields. */
  function setSection(change) {
    section = nextSection(section, change, mesh);
    updateToolbar();
    invalidate();
  }

  function select(ref) {
    const element = ref && mesh?.elements.find((item) => item.object === ref.object && item.id === ref.subelement);
    selected = element ? element.index : -1;
    statusLeft.textContent = describe(element);
    invalidate();
    return Boolean(element);
  }

  function setTheme() {
    readColours();
    invalidate();
  }

  async function load(input) {
    const token = ++loadToken;
    frame.setState('loading', 'Preparing geometry…');
    let prepared;
    try {
      const data = await input;
      // Let the loading state paint before a potentially long synchronous preparation.
      await new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve)));
      if (token !== loadToken) {
        return null;
      }
      prepared = prepareGeometry(data);
    } catch (error) {
      if (token === loadToken) {
        showError(error?.message || String(error));
      }
      return null;
    }
    if (token !== loadToken) {
      return null;
    }
    const sameDocument = mesh && mesh.document === prepared.document && mesh.objects.length > 0;
    mesh = prepared;
    selected = -1;
    hovered = -1;
    renderer?.upload(mesh);
    if (!sameDocument) {
      needsFit = true;
      camera = {...camera, yaw: createCamera().yaw, pitch: createCamera().pitch};
      section = {...section, axis: -1};
    }
    if (renderer) {
      frame.setState(mesh.elements.length ? 'ready' : 'empty', mesh.elements.length ? '' : 'Geometry has no elements');
    }
    statusLeft.textContent = 'No element selected';
    statusRight.textContent = `${mesh.triangleCount.toLocaleString('en-CA')} triangles · `
      + `${mesh.edges.length.toLocaleString('en-CA')} edges · ${mesh.vertices.length.toLocaleString('en-CA')} vertices`
      + ` · rev ${mesh.revision}`;
    readColours();
    resize();
    updateToolbar();
    setTimeout(() => token === loadToken && ensureBvh(mesh), 50);
    const summary = {revision: mesh.revision, triangles: mesh.triangleCount, edges: mesh.edges.length,
      vertices: mesh.vertices.length, objects: mesh.objects.length};
    events.emit('load', summary);
    return summary;
  }

  function clear() {
    loadToken++;
    mesh = null;
    selected = -1;
    hovered = -1;
    renderer?.upload(null);
    statusLeft.textContent = 'No element selected';
    statusRight.textContent = '';
    frame.setState(renderer ? 'empty' : 'error', renderer ? '' : 'WebGL is unavailable in this browser.');
    invalidate();
  }

  function showError(message) {
    frame.setState('error', message);
    events.emit('error', {message});
  }

  function destroy() {
    loadToken++;
    cancelAnimationFrame(frameRequest);
    navigation.detach();
    resizeObserver.disconnect();
    stopTheme();
    renderer?.destroy();
    frame.root.remove();
    events.clear();
  }

  /** Client (CSS pixel) position of a world point, or null when off-view. */
  function projectToClient(worldPoint) {
    const rect = canvas.getBoundingClientRect();
    const projected = mesh && projectWorld(mesh, camera, worldPoint, rect.width / rect.height);
    if (!projected) {
      return null;
    }
    return {
      x: rect.left + ((projected.nx + 1) / 2) * rect.width,
      y: rect.top + ((1 - projected.ny) / 2) * rect.height,
    };
  }

  readColours();
  updateToolbar();
  invalidate();

  return {
    element: frame.root,
    canvas,
    load,
    clear,
    resize,
    destroy,
    showError,
    setLoading: (message) => frame.setState('loading', message),
    on: events.on,
    fit,
    setView,
    setProjection,
    setNavigation: setNavigationMode,
    setWireframe,
    setSection,
    getSection: () => ({...section, position: sectionPosition(mesh, section)}),
    select,
    getSelection: () => (mesh?.elements[selected] ? reference(mesh.elements[selected], null, 'selection') : null),
    setTheme,
    getCamera: () => ({...camera}),
    setCamera: (next) => {
      camera = {...camera, ...next};
      updateToolbar();
      invalidate();
    },
    pickAt: (clientX, clientY) => {
      const hit = hitAt(clientX, clientY);
      return hit ? reference(hit.element, hit.point, 'pointer') : null;
    },
    projectToClient,
    /** Render synchronously and count drawn pixels (diagnostics / tests). */
    coveredPixels: () => {
      render();
      return renderer ? renderer.coveredPixels() : 0;
    },
    get mesh() {
      return mesh;
    },
  };
}
