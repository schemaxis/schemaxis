# Guided ParaView scene authoring

The scene editor supplies controls for the existing `schemaxis/1` document.
There are no new publication keys or native appearance settings. Adaptor-owned
Studio annotations select shared controls; the frontend does not identify
ParaView by name or branch on its operation names.

## Authoring flow

1. **Visible objects.** Choose from the current pipeline, with filtering,
   Select All/Deselect All, Select shown/Deselect shown, Shift-click ranges,
   and drag selection. Ctrl/Cmd-drag toggles. Selection writes exact map keys;
   it is not a rule that automatically includes future nodes. Unavailable
   selections remain visible and retain their settings until explicitly removed.
2. **Appearance.** Open a selected object's appearance. Choose solid colour
   or a cell/point data array. Solid colour supports all 1,163 names in the
   bundled Matplotlib palette, hex, grey levels and RGB/RGBA. Numeric editing
   offers 0–1 or 0–255 and writes normalised components. Representation,
   opacity, components, colour ranges, presets and legends use existing keys.
   Text-annotation operations receive their declared text controls instead.
3. **Inspect only on request.** Ask the application loads the selected object
   and its upstream inputs through existing inspection. The result supplies
   array names, association, components and ranges. It does not transfer data
   tuples. Use inspected range explicitly copies a fixed range; it is not a
   live binding. Without a range override, the runtime rescales each visit.
4. **Images and cameras.** Choose image dimensions, background and PNG
   transparency, then add cameras. Direction shortcuts set a compatible up
   vector. The default frame is all visible geometry. Bounds can link to a
   pipeline object's extents or a named Spatial box, or contain literal bounds.
   New volume opens the existing Spatial builder from the camera. The box
   definition and the camera change are returned as one editor transaction.
5. **Variants and other outputs.** Appearance variants select only visible
   objects and override selected style keys. An empty entry uses the base
   appearance. Geometry and measurement outputs use pipeline selection;
   image-independent writer exports retain their existing forms. Bundle
   controls explain glTF's text limitation and the editable state bundle's
   currently restricted scope.

## State, references and validation

Opening a form does not load native data. Draft fields are local until Apply;
Cancel discards the scene and newly created spatial definitions together.
Removing an array row reconstructs surviving controls at their new pointers,
so nested value pickers still bind to the correct camera. Whole-object runtime
expressions and placeholders remain explicitly editable without being flattened
into literal defaults. Unknown object IDs and additional authored style values
are retained, with host validation responsible for rejecting invalid input.

The existing `visible` map is the base appearance. Each `appearances` entry is
an additional merge into that base. It cannot remove an inherited field key;
a change from field colouring to solid colouring therefore needs a different
base or a separate scene. The editor explains this restriction. Copy settings
to checked objects copies only the explicitly selected keys and keeps unrelated
settings; geometry and text appearances cannot be mixed in that operation.

Spatial values stay linked as `$document` or `$expr` values. The browser does
not evaluate spatial expressions or substitute observed coordinates. Host
checks retain workflow scope and destination types. Flat boxes retain their
existing semantics; native camera validation remains authoritative.

## Coverage audit and further design

Shared numeric entry already reaches scalar, vector, bounds and corner-box
fields. This work closes the missing named-value picker in array items and
union fields, including nested image cameras, and adds the direct volume-builder
entry point for camera bounds. It does not claim that every spatial interaction
throughout every adaptor has a purpose-built visual tool. In particular, a
rendered camera-frame preview and universal typed name completion remain useful
follow-ups.

The current scene contract has no custom lights, material coefficients, gradient
backgrounds, legend placement/fonts, orientation axes, line width, point size,
edge colour, camera view angle or scene-level default style. Those controls must
not appear as if supported. Any later addition requires a separate schema/native
change and native verification. The existing legacy scene snippets still use
fixed scene targets; guided Scene/Image/Appearance forms are the preferred
path. Retargeting those snippets, a dedicated orbit wizard, richer variant tabs,
and host publication counts inside the editor remain separate GUI refinements.

The design deliberately uses guided controls around the existing representation.
It does not replace the scene schema or the Spatial expression language.
