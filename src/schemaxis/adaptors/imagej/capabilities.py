# Copyright (C) 2026 David L F Gaden
"""Operation discovery and domain guidance for bounded ImageJ particle measurement."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'ImageJ',
                'purpose': 'Threshold a calibrated 8/16-bit grayscale image and measure each particle with headless ImageJ 1.x, publishing a typed table in physical units for Calc or R.',
                'keywords': ['Fiji', 'ImageJ', 'image analysis', 'microscopy', 'scientific imaging']},
        'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements': [
            'Supply one absolute .pgm (P5) or uncompressed baseline .tif/.tiff grayscale image with 8- or 16-bit unsigned raw intensities, at most 2048 pixels per side and 1048576 pixels.',
            'Declare the pixel width/height and length unit (nm, um, mm, cm or m); any calibration embedded in the file is recorded by ImageJ and replaced, never silently combined.',
            'The threshold is an inclusive [lower, upper] window on stored raw intensities; automatic threshold methods, filtering and watershed separation are not offered.',
            'Configure a Java 11+ executable with the jdk.compiler module as the imagej location and ImageJ 1.54 ij.jar as imagejJar. Fiji bundles the same ImageJ 1.x core but its launcher is not the qualified runtime.',
            'Keep particle-summary.json with particles.csv: the table carries units in column names, the summary carries image digest, threshold, connectivity and calibration.'],
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
                    {'reference': 'examples/schemaxis/imagej-particles-16bit.json', 'purpose': 'Measure the same geometry from a big-endian 16-bit TIFF.'}]}}}
