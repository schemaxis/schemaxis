"""Isolated native writer qualification over bounded representative data families."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def native_case(operation, output, runtime):
    sys.path.insert(0,str(runtime))
    from schemaxis.adaptors.paraview.filters import catalogue
    from schemaxis.adaptors.paraview.native import ParaViewBackend
    from schemaxis.adaptors.paraview.writers import publish, LOSSES
    from vtkmodules.vtkCommonCore import vtkPoints, vtkDoubleArray, vtkUnsignedCharArray, vtkStringArray
    from vtkmodules.vtkCommonDataModel import vtkImageData, vtkRectilinearGrid, vtkStructuredGrid, vtkUnstructuredGrid, vtkTetra, vtkTable, vtkPartitionedDataSet, vtkPartitionedDataSetCollection, vtkMultiBlockDataSet, vtkVertex
    backend=ParaViewBackend(); ds=catalogue(); declaration=ds[operation]
    native=declaration['native']
    types=declaration['inputs'].get('Input',{}).get('contract',{}).get('nativeTypes',[])
    # Choose explicit small fixtures, never arbitrary production paths.
    image=vtkImageData();image.SetDimensions(4,4,1)
    values=vtkUnsignedCharArray();values.SetName('value')
    for i in range(16):values.InsertNextValue(i*8)
    image.GetPointData().SetScalars(values)
    points=vtkPoints()
    for value in [(0,0,0),(1,0,0),(0,1,0),(0,0,1)]:points.InsertNextPoint(*value)
    grid=vtkUnstructuredGrid();grid.SetPoints(points)
    tetra=vtkTetra()
    for i in range(4):tetra.GetPointIds().SetId(i,i)
    grid.InsertNextCell(tetra.GetCellType(),tetra.GetPointIds())
    sphere=backend.pv.Sphere(ThetaResolution=12,PhiResolution=12);sphere.UpdatePipeline()
    poly=backend.fetch(sphere)
    data=poly
    if native in ('CSVWriter','DataSetCSVWriter'):
        data=vtkTable()
        for name,values in [('x',[0.,1.,2.]),('y',[2.,3.,4.])]:
            array=vtkDoubleArray();array.SetName(name)
            for value in values:array.InsertNextValue(value)
            data.AddColumn(array)
    elif 'HyperTree' in native or native=='SerialHTGMultiBlock':
        producer=backend.pv.HyperTreeGrid();producer.UpdatePipeline();data=backend.fetch(producer)
        if native=='SerialHTGMultiBlock':
            blocks=vtkMultiBlockDataSet();blocks.SetBlock(0,data);data=blocks
    elif any(n in native for n in ('Hierarchical','AMR')):
        producer=backend.pv.HierarchicalFractal(MaximumLevel=1,Dimensions=4);producer.UpdatePipeline();data=backend.fetch(producer)
    elif 'PartitionedDataSetCollection' in native:
        partition=vtkPartitionedDataSet();partition.SetPartition(0,poly)
        data=vtkPartitionedDataSetCollection();data.SetPartitionedDataSet(0,partition)
    elif 'PartitionedDataSet' in native:
        data=vtkPartitionedDataSet();data.SetPartition(0,poly)
    elif native=='GenericIOWriter':
        particles=vtkUnstructuredGrid();particles.SetPoints(points)
        for i in range(points.GetNumberOfPoints()):
            vertex=vtkVertex();vertex.GetPointIds().SetId(0,i)
            particles.InsertNextCell(vertex.GetCellType(),vertex.GetPointIds())
        for component,name in enumerate(('x','y','z')):
            array=vtkDoubleArray();array.SetName(name)
            for i in range(points.GetNumberOfPoints()):array.InsertNextValue(points.GetPoint(i)[component])
            particles.GetPointData().AddArray(array)
        data=vtkMultiBlockDataSet();data.SetBlock(0,particles)
    elif 'MultiBlock' in native:
        data=vtkMultiBlockDataSet();data.SetBlock(0,poly)
    elif native in ('JPEGWriter','PNGWriter','TIFFWriter','JSONImageWriter','MetaImageWriter','OpenVDBWriter') or 'ImageData' in native:
        data=image
    elif 'Rectilinear' in native:
        data=vtkRectilinearGrid();data.SetDimensions(2,2,2)
        for setter in (data.SetXCoordinates,data.SetYCoordinates,data.SetZCoordinates):
            array=vtkDoubleArray();array.InsertNextValue(0);array.InsertNextValue(1);setter(array)
    elif 'StructuredGrid' in native:
        data=vtkStructuredGrid();data.SetDimensions(2,2,1)
        planar=vtkPoints()
        for p in [(0,0,0),(1,0,0),(0,1,0),(1,1,0)]:planar.InsertNextPoint(*p)
        data.SetPoints(planar)
    elif 'Table' in native:
        data=vtkTable();array=vtkDoubleArray();array.SetName('value')
        for i in range(4):array.InsertNextValue(i)
        data.AddColumn(array)
    elif 'Unstructured' in native or native in ('CGNSWriter','ExodusIIWriter','IOSSWriter','EnSightWriter'):
        data=grid
    elif types==['vtkImageData']:data=image
    proxy=backend.pv.TrivialProducer();proxy.GetClientSideObject().SetOutput(data);proxy.UpdatePipeline()
    options={}
    if 'Precision' in declaration['options']:options['Precision']=17
    if 'WriteTimeValue' in declaration['options']:options['WriteTimeValue']=False
    comparison=declaration['publication']['comparison']
    settings={'id':'writer','node':'fixture','writer':operation,'options':options,
              'extension':declaration['publication']['extensions'][0],'comparison':comparison,
              'acceptLosses':LOSSES[comparison], 'tolerance':3 if native=='JPEGWriter' else 1e-6 if comparison=='geometry' else 0,
              'readback':None}
    if native=='GenericIOWriter':
        settings['readback']={'operation':'pvGenericIOMultiBlockReader', 'options':{
            'xAxis':'x','yAxis':'y','zAxis':'z','PointArrayStatus':['x','y','z']}}
    artifact=publish(backend,proxy,declaration,settings,output/'artifact',0,ds)
    result={'operation':operation,'status':'passed','dataType':data.GetClassName(),'settings':settings,'artifact':artifact}
    (output/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paraview');parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--operation');parser.add_argument('--runtime',type=Path)
    args=parser.parse_args()
    if args.operation:
        native_case(args.operation,args.output_directory,args.runtime);return
    sys.path.insert(0,str(ROOT/'src'))
    from schemaxis.adaptors.paraview.filters import catalogue
    from schemaxis.artifacts import runtime_archive
    args.output_directory.mkdir(exist_ok=False)
    runtime=args.output_directory/'runtime.zip';runtime.write_bytes(runtime_archive())
    checksum=hashlib.sha256(runtime.read_bytes()).hexdigest();results=[]
    for name,declaration in catalogue().items():
        if declaration.get('role')!='writer':continue
        target=args.output_directory/name;target.mkdir()
        command=[args.paraview,'--force-offscreen-rendering',str(Path(__file__).resolve()),'--operation',name,
                 '--runtime',str(runtime.resolve()),'--output-directory',str(target.resolve())]
        try:
            run=subprocess.run(command,capture_output=True,text=True,timeout=45)
            (target/'stdout.log').write_text(run.stdout);(target/'stderr.log').write_text(run.stderr)
            passed=run.returncode==0 and (target/'receipt.json').exists()
            result={'operation':name,'status':'passed' if passed else 'failed','exitCode':run.returncode,'runtimeSHA256':checksum}
        except subprocess.TimeoutExpired:result={'operation':name,'status':'timeout','runtimeSHA256':checksum}
        results.append(result)
        (args.output_directory/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
        print(name,result['status'],flush=True)

if __name__=='__main__':main()
