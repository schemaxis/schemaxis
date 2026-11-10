# Strategic adaptor completion

An adaptor is strategically complete when the stable, important application
workflows can be expressed, executed, inspected, edited and handed on through
Schemaxis without material missing capability families. Completing an individual
feature, a native API mapping, or a declared subset is a development milestone.
It does not complete the application adaptor.

This is the programme acceptance definition. The per-change
[completion checklist](adaptor-completion.md) remains mandatory for each addition.
The [editorial assessments](adaptor-assessments.md) and source-bound native
qualification describe different evidence; neither substitutes for this review.

## Keep the denominator visible

Maintain an adaptor-owned capability-family map grounded in the public stable
application manual and API. Each family needs:

- the user tasks and useful deliverables that require it;
- implemented entry points and important composition restrictions;
- verified native workflows, including representative combinations with other
  families, saved-state editing and downstream use;
- remaining capability and abstraction gaps;
- any omission decision, its relevance or stability rationale, and its evidence.

Do not remove an important family from the denominator because its implementation
is difficult, its verification is expensive, or a smaller example already passes.
An unavailable runtime is an unresolved qualification gap. A stable capability
that needs another execution mode is an implementation decision to resolve.

Experimental APIs, application UI customization, developer debugging facilities,
and third-party extensions can be omitted where they do not serve the intended
product workflows. Such decisions require explicit reasons. A generic exclusion
of all specialist workbenches is insufficient when those workbenches provide
important application workflows. Ask for domain input when relevance is unclear.

A percentage must retain its stated denominator and uncertainty. Wrapper counts,
API method counts, generated schema counts and test counts do not measure useful
workflow completeness. A high abstraction score on a narrow subset is compatible
with substantial unfinished application coverage.

## Express intent above native plumbing

Use three complementary layers rather than choosing between a catalogue and a
small collection of fixed recipes:

1. Reusable domain intent: parts, profiles, stock, mounting relationships,
   assemblies, assets, shots, motion, materials and deliverable requirements.
2. Composable typed model records: named geometry, feature dependencies,
   coordinate frames, parameters, selections, node graphs, timelines and outputs.
3. Reviewed native mappings: finite constructors, properties and operations with
   explicit types, units, reference rules, defaults and readback.

A high-level task should resolve sensible native composition while retaining
inspectable editable state. Authors may need lower-level controls for legitimate
variation; provide those through the same typed contracts. An arbitrary script,
native object path or reflection escape hatch does not complete API coverage.
Generated catalogues are useful implementation tools, but every advertised
mapping still needs semantics, explanations, version compatibility and evidence.

Prefer named entities and geometric intent over accidental native list indices.
Where stable identity is unavailable, state how re-selection works, reject
ambiguity and verify the selected result. Maintain explicit frames and units
across CAD, mesh and scene handoffs. Do not promise native-edit reverse
synchronisation unless it is actually implemented and independently checked.

## Blender programme acceptance

The strategic review covers, at minimum:

- mesh and curve modelling, topology, attributes and modifier composition;
- reusable objects, hierarchy, collections, instancing and asset dependencies;
- materials, textures, UVs and shader-node composition;
- cameras, lights, world, shot composition and rendering outputs;
- animation channels, timing, interpolation, actions and reusable motion;
- armatures, deformation, constraints and rigged animation;
- Geometry Nodes and reusable procedural models;
- compositing and image-output processing;
- supported simulation workflows, cache dependencies and reproducibility;
- sculpt/paint and Grease Pencil workflows where useful stable APIs permit them;
- sequence/video and tracking workflows where strategically relevant;
- native project reuse, import/export, edits and downstream asset handoffs.

Representative acceptance must combine these capabilities. A reusable animated
asset should retain its hierarchy, appearance and motion after saving/reopening;
a prepared scene should support separately requested shots and frame outputs;
a procedural or simulated asset should retain the dependencies needed to
reproduce its outputs. Static object creation alone does not satisfy these tasks.
Important absent families remain unfinished even when these examples pass.

The public [Blender manual](https://docs.blender.org/manual/en/latest/) and
[Python API](https://docs.blender.org/api/current/) provide the family inventory.
The implementation and qualification records must pin the actual stable runtime
rather than assuming that a rolling documentation URL identifies it.

## FreeCAD programme acceptance

The strategic review covers, at minimum:

- general constrained sketches, reusable profiles and coordinate frames;
- composable multi-feature Body histories and multiple Bodies;
- additive/subtractive features, dress-ups, patterns and feature extent modes;
- Part solids, surfaces, booleans, topology and geometry preparation;
- persistent parameters, expressions, dependencies and design variation;
- assemblies, component reuse, joint relationships and mechanism workflows;
- supplier geometry/native project reuse and meaningful import/export coverage;
- dimensions, views, annotations and technical drawing publication;
- material/mesh/constraint/result handoffs for relevant FEM workflows;
- stock, tools, machining operations and manufacturing output for CAM workflows;
- mesh preparation and scan/reverse-engineering workflows where relevant;
- Draft/BIM and other stable specialist families with an explicit relevance
  decision, rather than silent exclusion;
- saved-document editing, recomputation and cross-application handoffs.

Representative acceptance must include a part requiring several additive and
subtractive features on different frames, a parameter change that recomputes the
history, a multi-part assembly, technical documentation and relevant downstream
manufacturing/analysis outputs. Native feature history is part of the product;
a similar final shape constructed by unrelated operations does not establish
coverage of an editable feature workflow. Important absent families remain
unfinished even when these examples pass.

The public [FreeCAD feature overview](https://www.freecad.org/features) and
[stable source/API documentation](https://github.com/FreeCAD/FreeCAD) provide
starting points. Capability decisions must identify concrete relevant APIs and
runtime observations, not infer stability from a workbench name.

## Acceptance and continued ownership

Continue into the next missing strategic family after an accepted milestone.
Keep native assertions independent: expected dimensions, transforms, sample
motion, physical balances or image facts must not merely repeat producer values.
Exercise baseline, variation, incorrect intent, stale/tampered state and relevant
lifecycle controls. Verify important preserved intent as well as current output.

Final strategic sign-off requires a family-by-family gap review and representative
cross-family native workflows, followed by the ordinary host, Studio, generated
asset, package and distribution checks. Report residual important gaps as
unfinished work. Future upstream maintenance is expected; avoid saying no further
work is needed while known strategic implementation gaps remain.
