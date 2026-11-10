# Copyright (C) 2026 David L F Gaden
"""Operation discovery and domain guidance for bounded ImageJ particle and region measurement."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'ImageJ',
                'purpose': 'Threshold a calibrated 8/16-bit grayscale image and measure each particle, or repeat named rectangular-region intensity and area measurements across a small labelled image series, with headless ImageJ 1.x, publishing tables in physical units: the particle table for Calc or a later R analysis, and the labelled region table for a Calc typed-CSV handoff (no R handoff is claimed for regions).',
                'keywords': ['Fiji', 'ImageJ', 'image analysis', 'microscopy', 'scientific imaging']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements': [
            'Supply one absolute .pgm (P5) or uncompressed baseline .tif/.tiff grayscale image with 8- or 16-bit unsigned raw intensities, at most 2048 pixels per side and 1048576 pixels.',
            'Declare the pixel width/height and length unit (nm, um, mm, cm or m); any calibration embedded in the file is recorded by ImageJ and replaced, never silently combined.',
            'The threshold is an inclusive [lower, upper] window on stored raw intensities; automatic threshold methods, filtering and watershed separation are not offered.',
            'Configure a Java 11+ executable with the jdk.compiler module as the imagej location and ImageJ 1.54 ij.jar as imagejJar. Fiji bundles the same ImageJ 1.x core but its launcher is not the qualified runtime.',
            'Keep particle-summary.json with particles.csv: the table carries units in column names, the summary carries image digest, threshold, connectivity and calibration.',
            'For measureRegions supply 2-8 captured grayscale planes of identical width, height and bit depth, each with a unique safe frame ID and declared seconds that strictly increase, plus 1-16 uniquely named zero-based top-left integer rectangles that lie inside every frame; keep region-measurements.json with the CSV. Each frame must be a distinct file (identified by file identity, so an alias or hard link counts as the same file); the series is bounded by 32 MiB, 4194304 pixels and 16777216 rectangle pixel visits before any frame is read or decoded.'],
        'references': ['docs/imagej.md', 'src/schemaxis/adaptors/imagej/readiness.json'],
        'operations': {
            'analyzeParticles': {
                'purpose': 'Count and measure thresholded particles (blobs, grains, pores or cells) in one calibrated grayscale image: area, centroid, bounding box and raw intensity statistics.',
                'keywords': ['Analyze Particles', 'Fiji', 'particle analysis', 'count particles', 'particle size', 'blob counting',
                             'grain size', 'pore size', 'threshold', 'binarize', 'segmentation', 'connected components',
                             'measure area', 'calibrated area', 'centroid', 'count mask'],
                'semantics': [
                    'Pixels with lower <= raw intensity <= upper are foreground. Particles are found in raster order (top row first, left to right) and numbered from 1.',
                    'connectivity eight joins corner-touching pixels; four separates them and requires includeHoles, matching ImageJ.',
                    'includeHoles counts enclosed background and enclosed particles as part of the surrounding particle; excludeEdges drops particles whose bounding box touches the image border.',
                    'minimumArea/maximumArea are inclusive calibrated areas converted to whole-pixel counts before native assignment.',
                    'Every native row, the ImageJ count mask and a fresh-process ImageStatistics readback are checked against an independent connected-component model.'],
                'examples': [
                    {'reference': 'examples/schemaxis/imagej-particles.json', 'purpose': 'Measure eight analytic particles in the synthetic 8-bit target at 0.5 um per pixel.'},
                    {'reference': 'examples/schemaxis/imagej-particles-filled.json', 'purpose': 'Fill the ring hole, drop the edge block and the single-pixel speck.'},
                    {'reference': 'examples/schemaxis/imagej-particles-16bit.json', 'purpose': 'Measure the same geometry from a big-endian 16-bit TIFF.'}]},
            'measureRegions': {
                'purpose': 'Repeat the same named rectangular regions across a short series of captured grayscale images (microscope or materials frames) and publish per-frame, per-region pixel count, calibrated area and raw mean/minimum/maximum with frame ID, region ID and time.',
                'keywords': ['region of interest', 'ROI', 'rectangle', 'rectangular region', 'repeated measurement', 'image series', 'time series',
                             'time lapse', 'frame', 'mean intensity', 'region intensity', 'measure region', 'image stack', 'Measure', 'ROI Manager'],
                'semantics': [
                    'Each region is x, y, width and height in zero-based pixels from the top-left corner; right and bottom edges are exclusive and every pixel inside is counted once.',
                    'The same rectangle list is measured in every frame: nothing moves, tracks, registers or interpolates, and rectangles may overlap because each is an independent measurement.',
                    'Frames are listed in strictly increasing declared seconds; time is never read from files. Frames must share width, height and bit depth.',
                    'Intensities are raw stored values; the declared calibration only scales area (pixelCount x pixelWidth x pixelHeight) and replaces any calibration in the files.',
                    'Every native row and a fresh-process ImagePlus/Roi readback are checked against an independent exact enumeration of the rectangle pixels.'],
                'examples': [
                    {'reference': 'examples/schemaxis/imagej-regions.json', 'purpose': 'Three overlapping rectangles across four 8-bit analytic frames with rectangular pixels.'},
                    {'reference': 'examples/schemaxis/imagej-regions-16bit.json', 'purpose': 'A whole-frame and a nested rectangle across three 16-bit TIFF frames at irregular times.'}]}}}
