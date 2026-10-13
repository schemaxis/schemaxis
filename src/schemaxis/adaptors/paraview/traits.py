"""VTK representation to framework data traits."""

def paraview_traits(native_type):
    """Semantic traits guaranteed by the named VTK representation, not storage guesses."""
    spatial = {'vtkPolyData','vtkUnstructuredGrid','vtkImageData','vtkStructuredGrid',
               'vtkRectilinearGrid','vtkUniformGrid','vtkHyperTreeGrid','vtkUniformHyperTreeGrid'}
    composite = {'vtkMultiBlockDataSet','vtkPartitionedDataSet',
                 'vtkPartitionedDataSetCollection','vtkOverlappingAMR','vtkNonOverlappingAMR'}
    result = {'family':'unknown', 'topology':'unknown', 'coordinates':'unknown',
              'contiguity':'unknown', 'indexing':'unknown', 'iteration':'unknown'}
    if native_type in spatial:
        result.update(family='spatial', indexing='point-cell-identifiers')
    if native_type in ('vtkImageData','vtkUniformGrid'):
        result.update(topology='structured', coordinates='implicit')
    elif native_type == 'vtkRectilinearGrid':
        result.update(topology='structured', coordinates='axis-arrays')
    elif native_type == 'vtkStructuredGrid':
        result.update(topology='structured', coordinates='explicit')
    elif native_type in ('vtkHyperTreeGrid', 'vtkUniformHyperTreeGrid'):
        # Refinement trees over a regular root grid; vtkDataSet filters do not apply.
        result.update(topology='hyper-tree')
    elif native_type in ('vtkPolyData','vtkUnstructuredGrid'):
        result.update(topology='unstructured', coordinates='explicit')
    elif native_type == 'vtkTable':
        result.update(family='table', indexing='row-column')
    elif native_type in composite:
        result.update(family='composite', iteration='blocks')
    elif native_type in ('vtkDirectedGraph','vtkUndirectedGraph','vtkTree'):
        result.update(family='graph', indexing='vertex-edge-identifiers')
    return result
