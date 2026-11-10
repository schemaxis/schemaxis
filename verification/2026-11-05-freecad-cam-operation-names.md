# FreeCAD CAM operation identities

A permitted hyphenated operation ID passed planning but FreeCAD sanitized its
native object name, causing execution to fail. `pilot-hole` and `pilot_hole`
also collided after sanitation. The repair derives a complete, injective native
name map from typed operation IDs before construction. All existing IDs without
hyphens retain their native names. Allocated names avoid every reserved name,
including safe IDs declared later in the operation list. Native creation must
return the exact compiled object before further configuration.

Runtime repair commits: `4618fe3` and `d668a67`; qualifier-only fixture repair:
`d7c7953`. The unchanged provider source digest for the repaired phases was
`sha256:37cd241cf381b87f943c4920013866f822486197cb3719ccd1367f32a0a22de4`.
The source snapshot also contained unregistered pointed-tool development; this
record accepts no pointed-tool capability.

Sixty CAM host checks passed. Actual FreeCAD 1.1.4 native build and separate
reopen preserved the distinct authored/native identities `pilot-hole` /
`Op_SCX1`, `pilot_hole` / `Op_pilot_hole`, and `SCX0` / `Op_SCX0`. The same
project preserved tool order 1→2→1, G81/G83/G85 cycles and independently expected
removed volume `24*pi` mm³. Refreshed native tool-binding tampering and coforged
sanitized-name observations were refused. Unchanged restoration passed.

Workflow reuse and standalone verification after producer retirement passed.
Actual private GUI editing and separate reopen produced exactly the same posted
program as a freshly constructed typed edit. Existing safe-ID legacy milling
passed current verification. The new legacy hyphen construction then encountered
a retired original fixture path before native execution, so that full qualifier
invocation remains failed. A qualifier-only repair selected the fixture's exact
retained captured source. Only the unfinished legacy construction and fresh
verification were rerun; both passed, including distinct native names and the
existing independent material gate. Completed phases retain their original
source identity and failed invocation record.

The schema, authored IDs, whole native reconstruction, complete SID/map/postfix
binding and geometry tolerances are unchanged. This closes the operation-name
regression within the qualified milling and drilling contracts. It does not
complete the CAM family or the FreeCAD adaptor; combined integration and package
gates remain the integration owner's responsibility.

## Integrated acceptance

The scoped repair is now accepted on integrated source `a5cf29b`. Current native
qualification repeats the complete identity trio, independent removed volume,
cycles, tool bindings, refreshed tamper refusals, restoration, actual GUI edit
and fresh reopen with exact reposting, reuse and producer retirement. Both the
historical safe-ID milling case and new hyphenated legacy milling case pass.
The same source passes 343 FreeCAD host controls, 101 shared controls and the
complete Studio suite (926 passed, three existing skips).

Clean installation of the source-matched wheel passes the three-operation naming
case, independent volume and sections, reuse and standalone verification after
producer retirement, plus installed CAM browser authoring. Three machining
passes correctly produce two distinct tracks. A mistaken private assertion of
three tracks stopped the first invocation; its corrected tail uses the same
sealed wheel and completes the unfinished checks. The failed invocation is
retained without being relabelled.

Wheel SHA256:
`b08f95ecb5be45861555e63a229ed8a6b57c43eda389543e3c516dccfdd65e03`.
No tolerance, authored-ID contract, release gate or package version changed.
Pointed-tool development and whole FreeCAD remain INCOMPLETE.
