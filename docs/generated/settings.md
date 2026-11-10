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
| `renderer` | `{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["cycles"],"required":true},"shadingSystem":{"type":"enum","values":["svm","osl"]}}},{"type":"object","properties":{"kind":{"type":"enum","values":["eevee"],"required":true},"samples":{"type":"integer","default":8,"minimum":1,"maximum":4096},"rayTracing":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["off"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["screen"],"required":true},"resolution":{"type":"enum","values":["1","2","4","8","16"],"default":"2"},"denoise":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["none"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["filtered"],"required":true},"spatial":{"type":"boolean","default":true},"temporal":{"type":"boolean","default":true},"bilateral":{"type":"boolean","default":true}}}],"default":{"kind":"filtered","spatial":true,"temporal":true,"bilateral":true}},"quality":{"type":"number","default":0.25,"minimum":0,"maximum":1},"thickness":{"type":"number","default":0.1,"minimum":1e-06,"maximum":100000},"backfaces":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["singleSided"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["bothSides"],"required":true},"radianceReuse":{"type":"number","default":0.25,"minimum":0,"maximum":1}}}],"default":{"kind":"bothSides","radianceReuse":0.25}}}}],"default":{"kind":"off"}},"fastGI":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["off"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["ambient"],"required":true},"resolution":{"type":"enum","values":["1","2","4","8","16"],"default":"2"},"quality":{"type":"number","default":0.25,"minimum":0,"maximum":1},"rays":{"type":"integer","default":2,"minimum":1,"maximum":16},"steps":{"type":"integer","default":8,"minimum":1,"maximum":64},"roughnessThreshold":{"type":"number","default":0.5,"minimum":0,"maximum":1,"exclusiveMaximum":true},"distance":{"type":"number","default":0,"minimum":0,"maximum":100000},"thickness":{"type":"number","default":0.1,"minimum":0,"maximum":100000},"bias":{"type":"number","default":0.05,"minimum":0,"maximum":1}}},{"type":"object","properties":{"kind":{"type":"enum","values":["global"],"required":true},"resolution":{"type":"enum","values":["1","2","4","8","16"],"default":"2"},"quality":{"type":"number","default":0.25,"minimum":0,"maximum":1},"rays":{"type":"integer","default":2,"minimum":1,"maximum":16},"steps":{"type":"integer","default":8,"minimum":1,"maximum":64},"roughnessThreshold":{"type":"number","default":0.5,"minimum":0,"maximum":1,"exclusiveMaximum":true},"distance":{"type":"number","default":0,"minimum":0,"maximum":100000},"thickness":{"type":"number","default":0.1,"minimum":0,"maximum":100000},"bias":{"type":"number","default":0.05,"minimum":0,"maximum":1}}}],"default":{"kind":"off"}},"shadowRays":{"type":"integer","default":1,"minimum":1,"maximum":4},"shadowSteps":{"type":"integer","default":6,"minimum":1,"maximum":16}}},{"type":"object","properties":{"kind":{"type":"enum","values":["workbench"],"required":true},"lighting":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["flat"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["studio"],"required":true},"preset":{"type":"enum","values":["basic.sl","outdoor.sl","paint.sl","rim.sl","studio.sl"],"default":"basic.sl"},"worldSpace":{"type":"boolean","default":false},"rotation":{"type":"number","default":0,"minimum":-3.141592653589793,"maximum":3.141592653589793},"specular":{"type":"boolean","default":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["matcap"],"required":true},"preset":{"type":"enum","values":["basic_bright.exr","basic_dark.exr","basic_grey.exr","basic_side.exr","ceramic_dark.exr","ceramic_lightbulb.exr","check_gradient.exr","check_normal+y.exr","check_reflection_horizontal.exr","check_reflection_vertical.exr","check_rim_dark.exr","check_rim_light.exr","clay_brown.exr","clay_green.exr","clay_studio.exr","clay_warm.exr","fullmetal.exr","hard_surface_grey.exr","hard_surface_red.exr","metal_bronze.exr","metal_carpaint.exr","pearl.exr","red_wax.exr","resin.exr","toon_dark.exr","toon_light.exr"],"default":"basic_grey.exr"}}}],"default":{"kind":"studio","preset":"basic.sl","worldSpace":false,"rotation":0,"specular":true}},"colourSource":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["material"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["object"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["random"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["attribute"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["single"],"required":true},"colour":{"type":"array","items":{"type":"number","minimum":0,"maximum":1},"minItems":3,"maxItems":3,"default":[0.8,0.8,0.8]}}},{"type":"object","properties":{"kind":{"type":"enum","values":["texture"],"required":true}}}],"default":{"kind":"material"}},"background":{"type":"array","items":{"type":"number","minimum":0,"maximum":1},"minItems":3,"maxItems":3,"default":[0.05,0.05,0.05]},"antiAliasing":{"type":"enum","values":["OFF","FXAA","5","8","11","16","32"],"default":"8"},"shadows":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["off"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["on"],"required":true},"direction":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"default":[1,1,1]},"darkness":{"type":"number","default":0.5,"minimum":0,"maximum":1},"shift":{"type":"number","default":0.1,"minimum":0,"maximum":1},"focus":{"type":"number","default":0,"minimum":0,"maximum":1}}}],"default":{"kind":"off"}},"cavity":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["off"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["world"],"required":true},"ridge":{"type":"number","default":1,"minimum":0,"maximum":250},"valley":{"type":"number","default":1,"minimum":0,"maximum":250}}},{"type":"object","properties":{"kind":{"type":"enum","values":["screen"],"required":true},"ridge":{"type":"number","default":1,"minimum":0,"maximum":2},"valley":{"type":"number","default":1,"minimum":0,"maximum":2}}},{"type":"object","properties":{"kind":{"type":"enum","values":["both"],"required":true},"worldRidge":{"type":"number","default":1,"minimum":0,"maximum":250},"worldValley":{"type":"number","default":1,"minimum":0,"maximum":250},"screenRidge":{"type":"number","default":1,"minimum":0,"maximum":2},"screenValley":{"type":"number","default":1,"minimum":0,"maximum":2}}}],"default":{"kind":"off"}},"outline":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["off"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["on"],"required":true},"colour":{"type":"array","items":{"type":"number","minimum":0,"maximum":1},"minItems":3,"maxItems":3,"default":[0,0,0]}}}],"default":{"kind":"off"}},"xray":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["off"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["on"],"required":true},"alpha":{"type":"number","default":0.5,"minimum":0,"maximum":1}}}],"default":{"kind":"off"}},"backfaceCulling":{"type":"boolean","default":false}}}]}` | `{"kind":"cycles"}` |
| `colourManagement` | `{"type":"object","properties":{"view":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["agx"],"required":true},"contrast":{"type":"enum","values":["base","punchy","veryHigh","high","mediumHigh","mediumLow","low","veryLow"],"default":"base"}}},{"type":"object","properties":{"kind":{"type":"enum","values":["standard"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["neutral"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["aces13"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["aces20"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["raw"],"required":true}}}],"default":{"kind":"agx","contrast":"base"}},"exposure":{"type":"number","default":0,"minimum":-32,"maximum":32},"gamma":{"type":"number","default":1,"minimum":0,"exclusiveMinimum":true,"maximum":5},"whiteBalance":{"type":"union","options":[{"type":"object","properties":{"kind":{"type":"enum","values":["off"],"required":true}}},{"type":"object","properties":{"kind":{"type":"enum","values":["on"],"required":true},"temperature":{"type":"number","default":6500,"minimum":1800,"maximum":100000},"tint":{"type":"number","default":10,"minimum":-500,"maximum":500}}}],"default":{"kind":"off"}}}}` | `{"view":{"kind":"agx","contrast":"base"},"exposure":0,"gamma":1,"whiteBalance":{"kind":"off"}}` |
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

## boundsFromExtents

| Option | Type / constraints | Default |
| --- | --- | --- |
| `extents` | `{"type":"array","items":{"type":"number"},"minItems":6,"maxItems":6}` | **required** |

Result: `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}`.

## boundsPoint

| Option | Type / constraints | Default |
| --- | --- | --- |
| `bounds` | `{"type":"object","properties":{"min":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true},"max":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3,"required":true}}}` | **required** |
| `x` | `{"type":"enum","values":["min","mid","max"]}` | `"mid"` |
| `y` | `{"type":"enum","values":["min","mid","max"]}` | `"mid"` |
| `z` | `{"type":"enum","values":["min","mid","max"]}` | `"mid"` |

Result: `{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}`.

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
