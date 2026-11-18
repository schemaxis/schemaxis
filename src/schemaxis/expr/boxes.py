"""Box algebra: flat boxes are valid and every invalid box is one value."""
import math

from .faults import ExprFault
from .values import INVALID, Box, make_box

FACES = ('x-', 'x+', 'y-', 'y+', 'z-', 'z+')
CORNERS = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))


def read(box):
    if not box.valid:
        raise ExprFault('EXPR_INVALID_BOX', 'a coordinate of an invalid box was read')
    return box


def middle(box):
    read(box)
    return tuple(a / 2 + b / 2 for a, b in zip(box.min, box.max))


def size(box):
    read(box)
    return tuple(b - a for a, b in zip(box.min, box.max))


def span(box):
    return math.hypot(*size(box))


def corner(box, number):
    read(box)
    return tuple(box.max[i] if upper else box.min[i] for i, upper in enumerate(CORNERS[number]))


def face(token):
    if token not in FACES:
        raise ExprFault('EXPR_ARGUMENTS', f'unknown face {token!r}', expected=list(FACES))
    return 'xyz'.index(token[0]), token[1] == '+'


def union(*boxes):
    valid = [box for box in boxes if box.valid]
    if not valid:
        return INVALID
    return Box([min(box.min[i] for box in valid) for i in range(3)],
               [max(box.max[i] for box in valid) for i in range(3)])


def intersect(*boxes):
    if not all(box.valid for box in boxes):
        return INVALID
    return make_box([max(box.min[i] for box in boxes) for i in range(3)],
                    [min(box.max[i] for box in boxes) for i in range(3)])


def overlaps(a, b):
    return intersect(a, b).valid


def contains(box, item):
    if not box.valid:
        return False
    if isinstance(item, Box):
        if not item.valid:
            return False
        lower, upper = item.min, item.max
    else:
        lower = upper = item
    return all(box.min[i] <= lower[i] and upper[i] <= box.max[i] for i in range(3))


def with_face(box, axis, upper, value):
    lower_corner, upper_corner = list(box.min), list(box.max)
    if upper:
        upper_corner[axis] = value
    else:
        lower_corner[axis] = value
    return make_box(lower_corner, upper_corner)


def candidate(a, common, token):
    axis, upper = face(token)
    if upper:
        if not common.max[axis] < a.max[axis]:
            return INVALID
        return with_face(a, axis, False, common.max[axis])
    if not common.min[axis] > a.min[axis]:
        return INVALID
    return with_face(a, axis, True, common.min[axis])


def measure(box):
    dx, dy, dz = size(box)
    return (dx * dy * dz, dx * dy + dy * dz + dz * dx, math.hypot(dx, dy, dz))


def subtract(a, b, keep=None):
    if keep is not None:
        face(keep)
    if not a.valid:
        return INVALID
    common = intersect(a, b)
    if not common.valid:
        return a
    if keep is not None:
        return candidate(a, common, keep)
    best = INVALID
    for token in FACES:
        box = candidate(a, common, token)
        if box.valid and (not best.valid or measure(box) > measure(best)):
            best = box
    return best


def translate(box, offset):
    if not box.valid:
        return INVALID
    return Box([a + d for a, d in zip(box.min, offset)], [a + d for a, d in zip(box.max, offset)])


def per_axis(amount):
    return amount if isinstance(amount, tuple) else (amount, amount, amount)


def resize(box, sizes):
    if not box.valid or any(s < 0 for s in sizes):
        return INVALID
    centre = middle(box)
    return make_box([c - s / 2 for c, s in zip(centre, sizes)], [c + s / 2 for c, s in zip(centre, sizes)])


def inflate(box, factor):
    if not box.valid:
        return INVALID
    return resize(box, [s * (1 + f) for s, f in zip(size(box), per_axis(factor))])


def inflate_abs(box, distance):
    if not box.valid:
        return INVALID
    return resize(box, [s + d for s, d in zip(size(box), per_axis(distance))])


def one_axis(axis, amount):
    return tuple(amount if i == axis else 0 for i in range(3))


def inflate_x(box, factor):
    return inflate(box, one_axis(0, factor))


def inflate_y(box, factor):
    return inflate(box, one_axis(1, factor))


def inflate_z(box, factor):
    return inflate(box, one_axis(2, factor))


def inflate_x_abs(box, distance):
    return inflate_abs(box, one_axis(0, distance))


def inflate_y_abs(box, distance):
    return inflate_abs(box, one_axis(1, distance))


def inflate_z_abs(box, distance):
    return inflate_abs(box, one_axis(2, distance))


def push_abs(box, token, distance):
    axis, upper = face(token)
    if not box.valid:
        return INVALID
    if upper:
        return with_face(box, axis, True, box.max[axis] + distance)
    return with_face(box, axis, False, box.min[axis] - distance)


def push(box, token, factor):
    axis, _ = face(token)
    if not box.valid:
        return INVALID
    return push_abs(box, token, factor * (box.max[axis] - box.min[axis]))


def set_face(box, token, value):
    axis, upper = face(token)
    if not box.valid:
        return INVALID
    return with_face(box, axis, upper, value)


def box_at(centre, sizes):
    if any(s < 0 for s in sizes):
        return INVALID
    return make_box([c - s / 2 for c, s in zip(centre, sizes)], [c + s / 2 for c, s in zip(centre, sizes)])


def from_six(x0, x1, y0, y1, z0, z1):
    return make_box((x0, y0, z0), (x1, y1, z1))
