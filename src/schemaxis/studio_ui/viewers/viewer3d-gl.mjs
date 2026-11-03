// Copyright (C) 2026 David L F Gaden
// WebGL 1 renderer for prepared geometry (see geometry-prepare.mjs for the
// 10-float vertex layout). Faces, native edges and native vertices share one
// program; barycentric (1,1,1) marks lines and points.

const VERTEX_SHADER = `
attribute vec3 position;
attribute vec3 normal;
attribute float element;
attribute vec3 barycentric;
uniform vec3 uRight;
uniform vec3 uUp;
uniform vec3 uForward;
uniform vec3 uTarget;
uniform vec3 uEye;
uniform vec2 uExtent;
uniform bool uPerspective;
uniform vec2 uDepthRange;
uniform float uPointSize;
varying vec3 vPosition;
varying vec3 vNormal;
varying float vElement;
varying vec3 vBary;

void main() {
  vPosition = position;
  vNormal = normal;
  vElement = element;
  vBary = barycentric;
  vec3 q = position - (uPerspective ? uEye : uTarget);
  float depth = -dot(q, uForward);
  gl_PointSize = uPointSize;
  if (uPerspective) {
    float near = uDepthRange.x;
    float far = uDepthRange.y;
    float z = ((far + near) * depth - 2.0 * far * near) / (far - near);
    gl_Position = vec4(dot(q, uRight) / uExtent.x, dot(q, uUp) / uExtent.y, z, depth);
  } else {
    gl_Position = vec4(dot(q, uRight) / uExtent.x, dot(q, uUp) / uExtent.y, depth / 8.0, 1.0);
  }
}
`;

function fragmentShader(derivatives) {
  return `${derivatives ? '#extension GL_OES_standard_derivatives : enable\n' : ''}
precision highp float;
varying vec3 vPosition;
varying vec3 vNormal;
varying float vElement;
varying vec3 vBary;
uniform int uAxis;
uniform float uCut;
uniform float uSide;
uniform float uSelected;
uniform float uHovered;
uniform bool uWireframe;
uniform vec3 uLight;
uniform vec3 uView;
uniform vec3 uSurface;
uniform vec3 uSelect;
uniform vec3 uHover;
uniform vec3 uLine;
uniform vec3 uWire;

void main() {
  float coordinate = uAxis == 0 ? vPosition.x : (uAxis == 1 ? vPosition.y : vPosition.z);
  if (uAxis >= 0 && uSide * (coordinate - uCut) > 0.0) {
    discard;
  }
  bool selected = abs(vElement - uSelected) < 0.25;
  bool hovered = abs(vElement - uHovered) < 0.25;
  if (vBary.x + vBary.y + vBary.z > 2.0) {
    vec3 lineColour = selected ? uSelect : (hovered ? uHover : uLine);
    gl_FragColor = vec4(lineColour, 1.0);
    return;
  }
  vec3 n = normalize(gl_FrontFacing ? vNormal : -vNormal);
  float diffuse = abs(dot(n, uLight));
  vec3 halfway = normalize(uLight + uView);
  float specular = pow(abs(dot(n, halfway)), 48.0) * 0.18;
  vec3 base = selected ? uSelect : (hovered ? mix(uSurface, uHover, 0.45) : uSurface);
  vec3 colour = base * (0.42 + 0.58 * diffuse) + vec3(specular);
  ${derivatives ? `if (uWireframe) {
    vec3 edge = smoothstep(vec3(0.0), max(fwidth(vBary) * 1.1, vec3(0.00001)), vBary);
    float wire = 1.0 - min(edge.x, min(edge.y, edge.z));
    colour = mix(colour, uWire, wire * 0.6);
  }` : ''}
  gl_FragColor = vec4(colour, 1.0);
}
`;
}

const UNIFORMS = ['uRight', 'uUp', 'uForward', 'uTarget', 'uEye', 'uExtent', 'uPerspective', 'uDepthRange',
  'uPointSize', 'uAxis', 'uCut', 'uSide', 'uSelected', 'uHovered', 'uWireframe', 'uLight', 'uView', 'uSurface',
  'uSelect', 'uHover', 'uLine', 'uWire'];
const ATTRIBUTES = [['position', 3, 0], ['normal', 3, 12], ['element', 1, 24], ['barycentric', 3, 28]];
const STRIDE_BYTES = 40;

/** Create a renderer on a canvas. Throws when WebGL is unavailable. */
export function createRenderer(canvas) {
  const gl = canvas.getContext('webgl', {antialias: true, alpha: true, preserveDrawingBuffer: false});
  if (!gl) {
    throw Error('WebGL is unavailable in this browser. Geometry cannot be displayed.');
  }
  let program = null;
  let uniforms = {};
  let attributes = [];
  let buffers = {};
  let counts = {faces: 0, lines: 0, dots: 0};
  let derivatives = false;
  let lost = false;
  let mesh = null;

  function compile(kind, source) {
    const shader = gl.createShader(kind);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw Error(gl.getShaderInfoLog(shader) || 'Shader compilation failed.');
    }
    return shader;
  }

  function initialise() {
    derivatives = Boolean(gl.getExtension('OES_standard_derivatives'));
    program = gl.createProgram();
    const shaders = [compile(gl.VERTEX_SHADER, VERTEX_SHADER), compile(gl.FRAGMENT_SHADER, fragmentShader(derivatives))];
    for (const shader of shaders) {
      gl.attachShader(program, shader);
    }
    gl.linkProgram(program);
    for (const shader of shaders) {
      gl.deleteShader(shader);
    }
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw Error(gl.getProgramInfoLog(program) || 'Shader link failed.');
    }
    uniforms = Object.fromEntries(UNIFORMS.map((name) => [name, gl.getUniformLocation(program, name)]));
    attributes = ATTRIBUTES.map(([name, size, offset]) => [gl.getAttribLocation(program, name), size, offset]);
    buffers = {faces: gl.createBuffer(), lines: gl.createBuffer(), dots: gl.createBuffer()};
    gl.enable(gl.DEPTH_TEST);
    gl.disable(gl.CULL_FACE);
    gl.clearColor(0, 0, 0, 0);
  }

  function upload(prepared) {
    mesh = prepared;
    if (lost || !mesh) {
      return;
    }
    const sources = {faces: mesh.packed, lines: mesh.lines, dots: mesh.dots};
    for (const [name, data] of Object.entries(sources)) {
      gl.bindBuffer(gl.ARRAY_BUFFER, buffers[name]);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      counts[name] = data.length / 10;
    }
  }

  function bindAttributes(buffer) {
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    for (const [location, size, offset] of attributes) {
      if (location >= 0) {
        gl.enableVertexAttribArray(location);
        gl.vertexAttribPointer(location, size, gl.FLOAT, false, STRIDE_BYTES, offset);
      }
    }
  }

  /**
   * Draw a frame. view = {right, up, forward, target, eye, extent: [x, y], perspective, depthRange,
   * axis, cut, side, selected, hovered, wireframe, light, colours: {surface, select, hover, line, wire},
   * pointSize}. Resizes the drawing buffer to the canvas CSS size × dpr.
   */
  function draw(view, dpr) {
    if (lost) {
      return;
    }
    const width = Math.max(1, Math.round(canvas.clientWidth * dpr));
    const height = Math.max(1, Math.round(canvas.clientHeight * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    gl.viewport(0, 0, width, height);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!mesh) {
      return;
    }
    gl.useProgram(program);
    gl.uniform3fv(uniforms.uRight, view.right);
    gl.uniform3fv(uniforms.uUp, view.up);
    gl.uniform3fv(uniforms.uForward, view.forward);
    gl.uniform3fv(uniforms.uTarget, view.target);
    gl.uniform3fv(uniforms.uEye, view.eye);
    gl.uniform2f(uniforms.uExtent, view.extent[0], view.extent[1]);
    gl.uniform1i(uniforms.uPerspective, view.perspective ? 1 : 0);
    gl.uniform2f(uniforms.uDepthRange, view.depthRange[0], view.depthRange[1]);
    gl.uniform1f(uniforms.uPointSize, view.pointSize);
    gl.uniform1i(uniforms.uAxis, view.axis);
    gl.uniform1f(uniforms.uCut, view.cut);
    gl.uniform1f(uniforms.uSide, view.side);
    gl.uniform1f(uniforms.uSelected, view.selected);
    gl.uniform1f(uniforms.uHovered, view.hovered);
    gl.uniform1i(uniforms.uWireframe, view.wireframe ? 1 : 0);
    gl.uniform3fv(uniforms.uLight, view.light);
    gl.uniform3fv(uniforms.uView, view.forward);
    gl.uniform3fv(uniforms.uSurface, view.colours.surface);
    gl.uniform3fv(uniforms.uSelect, view.colours.select);
    gl.uniform3fv(uniforms.uHover, view.colours.hover);
    gl.uniform3fv(uniforms.uLine, view.colours.line);
    gl.uniform3fv(uniforms.uWire, view.colours.wire);
    gl.depthFunc(gl.LEQUAL);
    // Offset filled polygons so their own native boundary wires remain visible.
    gl.enable(gl.POLYGON_OFFSET_FILL);
    gl.polygonOffset(1, 1);
    bindAttributes(buffers.faces);
    gl.drawArrays(gl.TRIANGLES, 0, counts.faces);
    gl.disable(gl.POLYGON_OFFSET_FILL);
    bindAttributes(buffers.lines);
    gl.drawArrays(gl.LINES, 0, counts.lines);
    bindAttributes(buffers.dots);
    gl.drawArrays(gl.POINTS, 0, counts.dots);
  }

  /** Count rendered (non-transparent) pixels; used by browser tests. */
  function coveredPixels() {
    const pixels = new Uint8Array(canvas.width * canvas.height * 4);
    gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    let count = 0;
    for (let i = 3; i < pixels.length; i += 4) {
      count += pixels[i] > 0 ? 1 : 0;
    }
    return count;
  }

  initialise();
  return {
    gl,
    upload,
    draw,
    coveredPixels,
    get derivatives() {
      return derivatives;
    },
    get lost() {
      return lost;
    },
    contextLost() {
      lost = true;
    },
    contextRestored() {
      lost = false;
      initialise();
      upload(mesh);
    },
    destroy() {
      for (const buffer of Object.values(buffers)) {
        gl.deleteBuffer(buffer);
      }
      gl.deleteProgram(program);
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    },
  };
}
