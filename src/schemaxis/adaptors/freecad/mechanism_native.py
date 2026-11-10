"""Native prescribed open-tree kinematics, imported only inside FreeCAD GUI."""
import json
import os
from pathlib import Path


def matrix(placement):return [float(v) for v in placement.toMatrix().A]


def observe(doc,prepared):
    import FreeCAD as App
    native=prepared['native'];assembly=doc.getObject('Assembly');sim=doc.getObject('Simulation')
    before={key:matrix(doc.getObject(name).Placement) for key,name in native['components'].items()}
    result={'initial':before,'generateCode':assembly.generateSimulation(sim),'frames':[],'shapes':[]}
    if result['generateCode']!=0:raise ValueError('native prescribed simulation did not solve')
    for frame in range(assembly.numberOfFrames()):
        assembly.updateForFrame(frame)
        result['frames'].append({key:matrix(doc.getObject(name).Placement) for key,name in native['components'].items()})
        shapes={}
        for key,name in native['components'].items():
            shape=doc.getObject(name).Shape
            shapes[key]={'valid':bool(shape.isValid()),'solids':len(shape.Solids),'volume':float(shape.Volume),
                'centreOfMass':[float(v) for v in shape.Solids[0].CenterOfMass] if len(shape.Solids)==1 else None}
        result['shapes'].append(shapes)
    assembly.updateForFrame(0)
    result['restored']={key:matrix(doc.getObject(name).Placement) for key,name in native['components'].items()}
    result['runtime']='.'.join(App.Version()[:3]);result['pid']=os.getpid()
    result['joints']={key:{'type':str(doc.getObject(name).JointType),
        'reference1':[doc.getObject(name).Reference1[0].Name,list(doc.getObject(name).Reference1[1])],
        'reference2':[doc.getObject(name).Reference2[0].Name,list(doc.getObject(name).Reference2[1])]}
        for key,name in native['joints'].items()}
    result['motions']={key:{'formula':str(doc.getObject(name).Formula),'type':str(doc.getObject(name).MotionType),
        'joint':doc.getObject(name).Joint[0].Name} for key,name in native['motions'].items()}
    result['simulation']={'start':float(sim.aTimeStart.Value),'end':float(sim.bTimeEnd.Value),
        'step':float(sim.cTimeStepOutput.Value),'fps':int(sim.jFramesPerSecond),'tolerance':float(sim.fGlobalErrorTolerance),
        'group':[obj.Name for obj in sim.Group]}
    result['objects']={o.Name:o.TypeId for o in doc.Objects}
    result['badStates']={o.Name:list(o.State) for o in doc.Objects if any(s in o.State for s in ('Error','Invalid'))}
    return result


def main(directory,stage):
    import FreeCAD as App
    import FreeCADGui as Gui
    import JointObject
    import UtilsAssembly
    import CommandCreateSimulation as simulation
    directory=Path(directory);p=json.loads((directory/'plan.json').read_text())
    if App.Version()[:3]!=['1','1','4']:raise ValueError('mechanisms require the qualified FreeCAD1.1.4 runtime')
    doc=App.openDocument(str(directory/('source.FCStd' if stage=='build' else 'model.FCStd')))
    if stage=='build':
        # Verified batch assemblies have native joint objects but may not yet
        # own GUI editor proxies. Attach the installed providers before any
        # recompute invokes their callbacks. Existing native providers survive.
        ground=doc.getObject('Ground')
        if not isinstance(ground.ViewObject.Proxy,JointObject.ViewProviderGroundedJoint):
            provider=JointObject.ViewProviderGroundedJoint(ground.ViewObject)
            if not hasattr(provider,'app_obj'):provider.attach(ground.ViewObject)
        for name in p['native']['joints'].values():
            joint=doc.getObject(name)
            if not isinstance(joint.ViewObject.Proxy,JointObject.ViewProviderJoint):
                provider=JointObject.ViewProviderJoint.__new__(JointObject.ViewProviderJoint)
                provider.attach(joint.ViewObject)
                JointObject.ViewProviderJoint.__init__(provider,joint.ViewObject)
        doc.Label='Mechanism'
        assembly=doc.getObject('Assembly')
        for motion in p['motions']:
            joint=doc.getObject(p['native']['joints'][motion['joint']])
            joint.JointType='Revolute' if motion['kind']=='rotation' else 'Slider'
        doc.recompute()
        if assembly.solve()!=0:raise ValueError('initial moving-joint solve failed')
        group=UtilsAssembly.getSimulationGroup(assembly)
        if group.Name!='Simulations':raise ValueError('source contains a conflicting simulation group')
        sim=group.newObject('App::FeaturePython','Simulation');simulation.Simulation(sim);simulation.ViewProviderSimulation(sim.ViewObject)
        sim.aTimeStart=0;sim.bTimeEnd=p['durationSeconds'];sim.cTimeStepOutput=p['durationSeconds']/p['intervals']
        sim.jFramesPerSecond=p['framesPerSecond'];sim.fGlobalErrorTolerance=1e-6
        motions=[]
        for motion in p['motions']:
            obj=assembly.newObject('App::FeaturePython',p['native']['motions'][motion['joint']])
            simulation.Motion(obj,'Angular' if motion['kind']=='rotation' else 'Linear',
                doc.getObject(p['native']['joints'][motion['joint']]),motion['formula'])
            simulation.ViewProviderMotion(obj.ViewObject);motions.append(obj)
        sim.Group=motions;doc.recompute()
    elif stage=='edit':
        # Qualification edits a private copy of a published native document.
        # Values still come from the finite compiled motion plan, never Python.
        sim=doc.getObject('Simulation');sim.bTimeEnd=p['durationSeconds'];sim.cTimeStepOutput=p['durationSeconds']/p['intervals']
        sim.jFramesPerSecond=p['framesPerSecond']
        for motion in p['motions']:
            obj=doc.getObject(p['native']['motions'][motion['joint']]);obj.Formula=motion['formula']
        doc.recompute()
    observed=observe(doc,p)
    if stage in ('build','edit'):
        from .gui_native import frame_view
        frame_view(doc,list(p['native']['components'].values()))
        doc.saveAs(str(directory/'model.FCStd'))
    App.closeDocument(doc.Name)
    return observed


def entry(directory,stage):
    from .gui_native import entry as private_entry
    return private_entry(directory,stage,'mechanism')
