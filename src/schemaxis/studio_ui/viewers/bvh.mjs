// Bounding volume hierarchy over triangles for fast ray picking.
// Triangle i occupies positions[9 i .. 9 i + 8] (three XYZ points).

const LEAF_SIZE = 8;

/** Build a BVH. Returns {order, nodeBounds, nodeStart, nodeCount, nodeLeft, nodeRight}. */
export function buildBvh(positions, triangleCount) {
  const order = new Uint32Array(triangleCount);
  const centroids = new Float64Array(triangleCount * 3);
  for (let i = 0; i < triangleCount; i++) {
    order[i] = i;
    for (let axis = 0; axis < 3; axis++) {
      const base = i * 9 + axis;
      centroids[i * 3 + axis] = (positions[base] + positions[base + 3] + positions[base + 6]) / 3;
    }
  }
  const capacity = Math.max(1, Math.ceil((2 * triangleCount) / LEAF_SIZE) * 2 + 1);
  const nodes = {
    order,
    nodeBounds: new Float64Array(capacity * 6),
    nodeStart: new Uint32Array(capacity),
    nodeCount: new Uint32Array(capacity),
    nodeLeft: new Int32Array(capacity).fill(-1),
    nodeRight: new Int32Array(capacity).fill(-1),
    size: 0,
  };
  if (triangleCount === 0) {
    return nodes;
  }
  const stack = [[createNode(nodes), 0, triangleCount]];
  while (stack.length) {
    const [node, start, end] = stack.pop();
    nodes.nodeStart[node] = start;
    nodes.nodeCount[node] = end - start;
    setBounds(nodes, node, positions, order, start, end);
    if (end - start <= LEAF_SIZE) {
      continue;
    }
    const middle = partition(order, centroids, start, end);
    if (middle <= start || middle >= end) {
      continue;
    }
    const left = createNode(nodes);
    const right = createNode(nodes);
    nodes.nodeLeft[node] = left;
    nodes.nodeRight[node] = right;
    stack.push([left, start, middle], [right, middle, end]);
  }
  return nodes;
}

function createNode(nodes) {
  if (nodes.size >= nodes.nodeStart.length) {
    throw Error('BVH capacity exceeded');
  }
  return nodes.size++;
}

function setBounds(nodes, node, positions, order, start, end) {
  const bounds = nodes.nodeBounds;
  const base = node * 6;
  bounds.fill(Infinity, base, base + 3);
  bounds.fill(-Infinity, base + 3, base + 6);
  for (let i = start; i < end; i++) {
    const triangle = order[i] * 9;
    for (let corner = 0; corner < 9; corner += 3) {
      for (let axis = 0; axis < 3; axis++) {
        const value = positions[triangle + corner + axis];
        if (value < bounds[base + axis]) {
          bounds[base + axis] = value;
        }
        if (value > bounds[base + 3 + axis]) {
          bounds[base + 3 + axis] = value;
        }
      }
    }
  }
}

/** Split order[start..end) at the centroid median of the widest axis (nth-element). */
function partition(order, centroids, start, end) {
  const low = [Infinity, Infinity, Infinity];
  const high = [-Infinity, -Infinity, -Infinity];
  for (let i = start; i < end; i++) {
    for (let axis = 0; axis < 3; axis++) {
      const value = centroids[order[i] * 3 + axis];
      low[axis] = Math.min(low[axis], value);
      high[axis] = Math.max(high[axis], value);
    }
  }
  const extents = high.map((value, axis) => value - low[axis]);
  const axis = extents.indexOf(Math.max(...extents));
  if (!(extents[axis] > 0)) {
    return (start + end) >> 1;
  }
  const middle = (start + end) >> 1;
  let left = start;
  let right = end - 1;
  const key = (i) => centroids[order[i] * 3 + axis];
  while (left < right) {
    const pivot = key((left + right) >> 1);
    let i = left;
    let j = right;
    while (i <= j) {
      while (key(i) < pivot) {
        i++;
      }
      while (key(j) > pivot) {
        j--;
      }
      if (i <= j) {
        const swap = order[i];
        order[i] = order[j];
        order[j] = swap;
        i++;
        j--;
      }
    }
    if (middle <= j) {
      right = j;
    } else if (middle >= i) {
      left = i;
    } else {
      break;
    }
  }
  return middle;
}

/** Ray entry distance into node bounds, or Infinity on a miss. */
function entryDistance(bounds, node, origin, inverse) {
  let near = 0;
  let far = Infinity;
  const base = node * 6;
  for (let axis = 0; axis < 3; axis++) {
    const minimum = bounds[base + axis] - 1e-9;
    const maximum = bounds[base + 3 + axis] + 1e-9;
    if (!Number.isFinite(inverse[axis])) {
      if (origin[axis] < minimum || origin[axis] > maximum) {
        return Infinity;
      }
      continue;
    }
    const a = (minimum - origin[axis]) * inverse[axis];
    const b = (maximum - origin[axis]) * inverse[axis];
    near = Math.max(near, Math.min(a, b));
    far = Math.min(far, Math.max(a, b));
    if (near > far) {
      return Infinity;
    }
  }
  return near;
}

/**
 * Visit candidate triangles along a ray. visit(triangle) returns the current
 * nearest accepted distance (Infinity when none), used to prune farther nodes.
 */
export function traverseBvh(bvh, origin, direction, visit) {
  if (!bvh.size) {
    return;
  }
  const inverse = direction.map((value) => (Math.abs(value) < 1e-12 ? Infinity : 1 / value));
  let nearest = Infinity;
  const stack = [0];
  while (stack.length) {
    const node = stack.pop();
    if (entryDistance(bvh.nodeBounds, node, origin, inverse) > nearest) {
      continue;
    }
    const left = bvh.nodeLeft[node];
    if (left < 0) {
      const start = bvh.nodeStart[node];
      const end = start + bvh.nodeCount[node];
      for (let i = start; i < end; i++) {
        nearest = Math.min(nearest, visit(bvh.order[i]));
      }
    } else {
      stack.push(left, bvh.nodeRight[node]);
    }
  }
}
