# trace generated using paraview version 5.13.3
#import paraview
#paraview.compatibility.major = 5
#paraview.compatibility.minor = 13

#### import the simple module from the paraview
from paraview.simple import *
#### disable automatic camera reset on 'Show'
paraview.simple._DisableFirstRenderCameraReset()

# create a new 'Wavelet'
wavelet1 = Wavelet(registrationName='Wavelet1')

# create a new 'Slice'
slice1 = Slice(registrationName='Slice1', Input=wavelet1)
slice1.SliceType = 'Plane'
slice1.HyperTreeGridSlicer = 'Plane'
slice1.PointMergeMethod = 'Uniform Binning'

# create a new 'XML PolyData Reader'
xMLPolyDataReader1 = XMLPolyDataReader(registrationName='XMLPolyDataReader1', FileName=['/tmp/schemaxis-paraview-trace-20260906/slice-0.vtp'])
xMLPolyDataReader1.PointArrayStatus = ['RTData']

# destroy xMLPolyDataReader1
Delete(xMLPolyDataReader1)
del xMLPolyDataReader1

# create a new 'XML PolyData Reader'
xMLPolyDataReader1 = XMLPolyDataReader(registrationName='XMLPolyDataReader1', FileName=['/tmp/schemaxis-paraview-trace-20260906/slice-1.vtp'])
xMLPolyDataReader1.PointArrayStatus = ['RTData']

# destroy xMLPolyDataReader1
Delete(xMLPolyDataReader1)
del xMLPolyDataReader1

# create a new 'XML PolyData Reader'
xMLPolyDataReader1 = XMLPolyDataReader(registrationName='XMLPolyDataReader1', FileName=['/tmp/schemaxis-paraview-trace-20260906/slice-2.vtp'])
xMLPolyDataReader1.PointArrayStatus = ['RTData']

# destroy xMLPolyDataReader1
Delete(xMLPolyDataReader1)
del xMLPolyDataReader1

# create a new 'XML PolyData Reader'
xMLPolyDataReader1 = XMLPolyDataReader(registrationName='XMLPolyDataReader1', FileName=['/tmp/schemaxis-paraview-trace-20260906/slice-4.vtp'])
xMLPolyDataReader1.PointArrayStatus = ['RTData']

# destroy xMLPolyDataReader1
Delete(xMLPolyDataReader1)
del xMLPolyDataReader1

# Create a new 'Render View'
renderView1 = CreateView('RenderView')
renderView1.AxesGrid = 'Grid Axes 3D Actor'
renderView1.StereoType = 0
renderView1.CameraFocalDisk = 1.0
renderView1.LegendGrid = 'Legend Grid Actor'
renderView1.PolarGrid = 'Polar Grid Actor'

# add view to a layout so it's visible in UI
AssignViewToLayout(view=renderView1, layout=None, hint=0)

# show data in view
slice1Display = Show(slice1, renderView1, 'GeometryRepresentation')

# get 2D transfer function for 'RTData'
rTDataTF2D = GetTransferFunction2D('RTData')

# get color transfer function/color map for 'RTData'
rTDataLUT = GetColorTransferFunction('RTData')
rTDataLUT.TransferFunction2D = rTDataTF2D
rTDataLUT.RGBPoints = [84.14448547363281, 0.231373, 0.298039, 0.752941, 180.4137954711914, 0.865003, 0.865003, 0.865003, 276.68310546875, 0.705882, 0.0156863, 0.14902]
rTDataLUT.ScalarRangeInitialized = 1.0

# trace defaults for the display properties.
slice1Display.Representation = 'Surface'
slice1Display.ColorArrayName = ['POINTS', 'RTData']
slice1Display.LookupTable = rTDataLUT
slice1Display.SelectNormalArray = 'None'
slice1Display.SelectTangentArray = 'None'
slice1Display.SelectTCoordArray = 'None'
slice1Display.TextureTransform = 'Transform2'
slice1Display.OSPRayScaleArray = 'RTData'
slice1Display.OSPRayScaleFunction = 'Piecewise Function'
slice1Display.Assembly = ''
slice1Display.SelectedBlockSelectors = ['']
slice1Display.SelectOrientationVectors = 'None'
slice1Display.ScaleFactor = 2.0
slice1Display.SelectScaleArray = 'RTData'
slice1Display.GlyphType = 'Arrow'
slice1Display.GlyphTableIndexArray = 'RTData'
slice1Display.GaussianRadius = 0.1
slice1Display.SetScaleArray = ['POINTS', 'RTData']
slice1Display.ScaleTransferFunction = 'Piecewise Function'
slice1Display.OpacityArray = ['POINTS', 'RTData']
slice1Display.OpacityTransferFunction = 'Piecewise Function'
slice1Display.DataAxesGrid = 'Grid Axes Representation'
slice1Display.PolarAxes = 'Polar Axes Representation'
slice1Display.SelectInputVectors = [None, '']
slice1Display.WriteLog = ''

# init the 'Piecewise Function' selected for 'ScaleTransferFunction'
slice1Display.ScaleTransferFunction.Points = [84.14448547363281, 0.0, 0.5, 0.0, 276.68310546875, 1.0, 0.5, 0.0]

# init the 'Piecewise Function' selected for 'OpacityTransferFunction'
slice1Display.OpacityTransferFunction.Points = [84.14448547363281, 0.0, 0.5, 0.0, 276.68310546875, 1.0, 0.5, 0.0]

# reset view to fit data
renderView1.ResetCamera(False, 0.9)

# reset view to fit data
renderView1.ResetCamera(False, 0.9)

# get layout
layout1 = GetLayout()

# layout/tab size in pixels
layout1.SetSize(400, 400)

# current camera placement for renderView1
renderView1.CameraPosition = [0.0, 0.0, 54.64101615137755]
renderView1.CameraParallelScale = 14.142135623730951

# save screenshot
SaveScreenshot(filename='/tmp/schemaxis-paraview-trace-20260906/slice.png', viewOrLayout=renderView1, location=16, ImageResolution=[400, 400])

#================================================================
# addendum: following script captures some of the application
# state to faithfully reproduce the visualization during playback
#================================================================

#--------------------------------
# saving layout sizes for layouts

# layout/tab size in pixels
layout1.SetSize(400, 400)

#-----------------------------------
# saving camera placements for views

# current camera placement for renderView1
renderView1.CameraPosition = [0.0, 0.0, 54.64101615137755]
renderView1.CameraParallelScale = 14.142135623730951


##--------------------------------------------
## You may need to add some code at the end of this python script depending on your usage, eg:
#
## Render all views to see them appears
# RenderAllViews()
#
## Interact with the view, usefull when running from pvpython
# Interact()
#
## Save a screenshot of the active view
# SaveScreenshot("path/to/screenshot.png")
#
## Save a screenshot of a layout (multiple splitted view)
# SaveScreenshot("path/to/screenshot.png", GetLayout())
#
## Save all "Extractors" from the pipeline browser
# SaveExtracts()
#
## Save a animation of the current active view
# SaveAnimation()
#
## Please refer to the documentation of paraview.simple
## https://www.paraview.org/paraview-docs/latest/python/paraview.simple.html
##--------------------------------------------