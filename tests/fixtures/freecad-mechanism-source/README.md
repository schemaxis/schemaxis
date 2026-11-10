# Own native constructor assembly fixture

Created with the Schemaxis typed constructor assembly route on FreeCAD1.1.4.
Two10mm cubes, ground position(2,3,4)mm and rotation90degrees; hinge connects
the ground top to the arm bottom with connectoroffset(3,4,5)mm. At90degrees
of subsequent rotation the arm origin is(-2,16,19)mm with rotation180degrees.
A12.5mm slider end instead puts its origin at(-2,6,31.5)mm.

This portable constructor packet retains authored/plan/nativebuild/reopenfacts,
the actual FCStd and a success marker. Only the publication file identity is
normalised to the explicit relative model.FCStd contract. Machine paths and
runtime archives are absent. Mechanism admission rechecks the native facts,
regenerates a fresh assembly from the typed intent, and binds every saved object,
proxy and payload before opening the supplied file. Document/object UUIDs and
creation/save times are native allocation metadata; all other properties remain
bound. This fixture does not qualify arbitrary native projects or source proxies.
