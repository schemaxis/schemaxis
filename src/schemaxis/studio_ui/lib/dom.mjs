// Small DOM helpers. Data is always inserted as text or attributes, never HTML.

const SVG_NS = 'http://www.w3.org/2000/svg';

function applyProps(element, props) {
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) {
      continue;
    }
    if (key === 'class') {
      element.setAttribute('class', Array.isArray(value) ? value.filter(Boolean).join(' ') : value);
    } else if (key === 'style' && typeof value === 'object') {
      for (const [name, styleValue] of Object.entries(value)) {
        if (name.startsWith('--')) {
          element.style.setProperty(name, styleValue);
        } else {
          element.style[name] = styleValue;
        }
      }
    } else if (key === 'dataset') {
      Object.assign(element.dataset, value);
    } else if (key.startsWith('on') && typeof value === 'function') {
      element.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'ref' && typeof value === 'function') {
      value(element);
    } else if (key in element && !(element instanceof SVGElement) && typeof value !== 'string') {
      element[key] = value;
    } else if (value === true) {
      element.setAttribute(key, '');
    } else {
      element.setAttribute(key, String(value));
    }
  }
}

function append(element, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false || child === true) {
      continue;
    }
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

/** Create an HTML element: h('button', {class: 'primary', onClick}, 'Save'). */
export function h(tag, props, ...children) {
  const element = document.createElement(tag);
  applyProps(element, props);
  append(element, children);
  return element;
}

/** Create an SVG element with the same calling convention as h(). */
export function s(tag, props, ...children) {
  const element = document.createElementNS(SVG_NS, tag);
  applyProps(element, props);
  append(element, children);
  return element;
}

/** Replace all children of an element. */
export function mount(element, ...children) {
  element.replaceChildren();
  append(element, children);
  return element;
}

/** A line icon from the shared sprite: icon('play'). */
export function icon(name, label) {
  const svg = s('svg', {class: 'icon', 'aria-hidden': label ? undefined : 'true', role: label ? 'img' : undefined},
    s('use', {href: `/assets/icons.svg#${name}`}));
  if (label) {
    svg.append(s('title', {}, label));
  }
  return svg;
}

/** Debounce a function; the returned function has cancel(). */
export function debounce(fn, delay) {
  let timer = null;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
}
