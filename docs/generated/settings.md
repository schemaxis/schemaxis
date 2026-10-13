# Shared settings and runtime functions

Generated from current code declarations. Do not edit by hand.

## Camera

| Option | Type / constraints | Default |
| --- | --- | --- |
| `direction` | `{"type":"union","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}]}` | `[1,0,0]` |
| `up` | `{"type":"union","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}]}` | `[0,0,1]` |
| `focalPoint` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | omitted |
| `parallel` | `{"type":"boolean"}` | `true` |
| `scale` | `{"type":"number","minimum":0,"exclusiveMinimum":true}` | omitted |
| `distance` | `{"type":"number","minimum":0,"exclusiveMinimum":true}` | omitted |
| `bounds` | `{"type":"array","items":{"type":"number"},"minItems":6,"maxItems":6}` | omitted |
| `padding` | `{"type":"number","minimum":0}` | `0.1` |

## Blender render

| Option | Type / constraints | Default |
| --- | --- | --- |
| `device` | `{"type":"enum","values":["CPU","CUDA","OPTIX"]}` | `"CPU"` |
| `samples` | `{"type":"integer","minimum":1,"maximum":4096}` | `8` |
| `threads` | `{"type":"integer","minimum":1,"maximum":64}` | `4` |
| `denoise` | `{"type":"boolean"}` | `false` |
| `transparent` | `{"type":"boolean"}` | `false` |
| `seed` | `{"type":"integer","minimum":0,"maximum":2147483647}` | `0` |
| `worldColour` | `{"type":"array","items":{"type":"number","minimum":0,"maximum":1},"minItems":3,"maxItems":3}` | `[0.8,0.8,0.8]` |
| `worldStrength` | `{"type":"number","minimum":0}` | `0.8` |
| `lightEnergy` | `{"type":"number","minimum":0}` | `1000` |
| `lightPosition` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | `[4,-4,6]` |
| `lightSize` | `{"type":"number","minimum":0,"exclusiveMinimum":true}` | `1` |

## ParaView appearance

| Option | Type / constraints | Default |
| --- | --- | --- |
| `colour` | `{"type":"union","options":[{"type":"string"},{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":4}]}` | `[0.7,0.7,0.7]` |
| `field` | `{"type":"array","items":{"type":"string"},"minItems":2,"maxItems":2}` | omitted |
| `component` | `{"type":"integer","minimum":-1}` | `-1` |
| `opacity` | `{"type":"number","minimum":0,"maximum":1}` | `1` |
| `representation` | `{"type":"enum","values":["Surface","Surface With Edges","Wireframe","Points","Outline"]}` | `"Surface"` |
| `range` | `{"type":"array","items":{"type":"number"},"minItems":2,"maxItems":2}` | omitted |
| `legend` | `{"type":"boolean"}` | `false` |
| `legendTitle` | `{"type":"string"}` | omitted |
| `preset` | `{"type":"string"}` | omitted |
| `logScale` | `{"type":"boolean"}` | `false` |

## boundsCentre

| Option | Type / constraints | Default |
| --- | --- | --- |
| `bounds` | `{"type":"array","items":{"type":"number"},"minItems":6,"maxItems":6}` | **required** |

Result: `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}`.

## boundsCentre3D

| Option | Type / constraints | Default |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | **required** |

Result: `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}`.

## boundsExtend

| Option | Type / constraints | Default |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | **required** |
| `before` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | `[0,0,0]` |
| `after` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | `[0,0,0]` |

Result: `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}`.

## boundsFrame

| Option | Type / constraints | Default |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | **required** |
| `before` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | `[0,0,0]` |
| `after` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | `[0,0,0]` |
| `floor` | `{"type":"number"}` | **required** |
| `aspect` | `{"type":"array","items":{"type":"number","minimum":0,"exclusiveMinimum":true},"minItems":2,"maxItems":2}` | `[16,9]` |

Result: `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}`.

## boundsSize

| Option | Type / constraints | Default |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | **required** |

Result: `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}`.

## boundsUnion

| Option | Type / constraints | Default |
| --- | --- | --- |
| `bounds` | `{"type":"array","items":{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}},"minItems":1}` | **required** |

Result: `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}`.

## directionVector

| Option | Type / constraints | Default |
| --- | --- | --- |
| `direction` | `{"type":"union","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}]}` | **required** |
| `length` | `{"type":"number","minimum":0}` | `1` |

Result: `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}`.

## fitCamera

| Option | Type / constraints | Default |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | **required** |
| `aspect` | `{"type":"array","items":{"type":"number","minimum":0,"exclusiveMinimum":true},"minItems":2,"maxItems":2}` | `[16,9]` |
| `padding` | `{"type":"number","minimum":0}` | `0.15` |
| `parallel` | `{"type":"boolean"}` | `true` |
| `distanceScale` | `{"type":"number","minimum":0,"exclusiveMinimum":true}` | `2` |
| `direction` | `{"type":"union","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}]}` | `"x+"` |
| `up` | `{"type":"union","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}]}` | `"z+"` |

Result: `{"type":"object","properties":{"direction":{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}],"default":[1,0,0]},"up":{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}],"default":[0,0,1]},"focalPoint":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3},"parallel":{"type":"boolean","default":true},"scale":{"type":"number","minimum":0,"exclusiveMinimum":true},"distance":{"type":"number","minimum":0,"exclusiveMinimum":true},"bounds":{"type":"array","items":{"type":"number"},"minItems":6,"maxItems":6},"padding":{"type":"number","minimum":0,"default":0.1}}}`.

## foamRegions

| Option | Type / constraints | Default |
| --- | --- | --- |
| `groups` | `{"type":"object","properties":{"tyres":{"type":"array","items":{"type":"string","minLength":3},"minItems":1,"required":true},"body":{"type":"array","items":{"type":"string","minLength":3},"minItems":1,"required":true}}}` | **required** |

Result: `{"type":"array","items":{"type":"string"}}`.

## orbitCameras

| Option | Type / constraints | Default |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | **required** |
| `aspect` | `{"type":"array","items":{"type":"number","minimum":0,"exclusiveMinimum":true},"minItems":2,"maxItems":2}` | `[16,9]` |
| `padding` | `{"type":"number","minimum":0}` | `0.15` |
| `parallel` | `{"type":"boolean"}` | `true` |
| `distanceScale` | `{"type":"number","minimum":0,"exclusiveMinimum":true}` | `2` |
| `count` | `{"type":"integer","minimum":1,"maximum":10000}` | `12` |
| `elevation` | `{"type":"number","minimum":-89,"maximum":89}` | `25` |

Result: `{"type":"array","items":{"type":"object","properties":{"direction":{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}],"default":[1,0,0]},"up":{"type":"union","title":"direction","summary":"An axis token, a vector, or an azimuth and elevation about an up axis","options":[{"type":"string","title":"axis token such as 'x+' or 'z-'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},{"type":"object","title":"direction object","properties":{"axis":{"type":"string","summary":"Axis token such as 'x+'"},"azimuth":{"type":"number","minimum":-360,"maximum":360,"summary":"Degrees about the up axis from the reference axis"},"elevation":{"type":"number","minimum":-180,"maximum":180,"summary":"Degrees tilted from the plane perpendicular to up"},"vector":{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3},"up":{"type":"union","title":"up direction","options":[{"type":"string","title":"axis token such as 'z+'"},{"type":"array","title":"vector [x, y, z]","items":{"type":"number"},"minItems":3,"maxItems":3}]}}}],"default":[0,0,1]},"focalPoint":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3},"parallel":{"type":"boolean","default":true},"scale":{"type":"number","minimum":0,"exclusiveMinimum":true},"distance":{"type":"number","minimum":0,"exclusiveMinimum":true},"bounds":{"type":"array","items":{"type":"number"},"minItems":6,"maxItems":6},"padding":{"type":"number","minimum":0,"default":0.1}}}}`.

## rangeCentre

| Option | Type / constraints | Default |
| --- | --- | --- |
| `range` | `{"type":"array","items":{"type":"number"},"minItems":2,"maxItems":2}` | **required** |

Result: `{"type":"number"}`.

## sinDegrees

| Option | Type / constraints | Default |
| --- | --- | --- |
| `angle` | `{"type":"number"}` | **required** |

Result: `{"type":"number"}`.

## slicePositions

| Option | Type / constraints | Default |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | **required** |
| `axis` | `{"type":"enum","values":["x","y","z"]}` | **required** |
| `count` | `{"type":"integer","minimum":1,"maximum":10000}` | `9` |

Result: `{"type":"array","items":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}}`.

## vectorLength

| Option | Type / constraints | Default |
| --- | --- | --- |
| `vector` | `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}` | **required** |

Result: `{"type":"number"}`.
