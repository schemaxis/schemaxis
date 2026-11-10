# Copyright (C) 2026 David L F Gaden
"""Curated report publication discovery."""
import json
from importlib.resources import files


def catalogue():
    return {'application':{'label':'Pandoc','purpose':'Publish structured reports as standalone HTML and editable Word DOCX, and optionally EPUB 3, with independently checked semantic retention.','keywords':['document converter','report publication','publish transcript','caption timestamps table','whisper transcript','Word','DOCX','HTML','EPUB','EPUB 3','ebook','e-book','report authors','author metadata','document description','EPUB creator','dc:creator']},
        'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':['Declare an ordered section outline, plain paragraphs, rectangular text tables and optional local plain PNG images.',
            'Replace each image path with an absolute regular RGB/RGBA PNG. Images are captured before native execution.',
            'In a workflow, an image block source may be the typed PNG image artifact of an earlier step, for example {"$artifact":"decode","index":0} from the WebP decodeToPng route; it is captured and checked exactly like a PNG path.',
            'To publish a whisper.cpp transcript, name its retained segments.json (or hand it over as a workflow text artifact) in a transcript block; the file is read at run time and shown as an unreviewed machine draft, or, for a reviewed document from the whisper.cpp corrections route, with its author-declared review status.',
            'To also publish an EPUB 3 e-book, declare epub with the plain ASCII language of the text (for example en or fr-CA); omitting epub publishes none.',
            'To credit the report, declare metadata with authors (1-8 distinct plain-text names, no semicolon, in publication order) and/or a description (plain text up to 1000 characters); both are your declarations, carried by HTML, DOCX and any EPUB and read back from each, never verified identity, accessibility or review.',
            'Only the bounded report model is supported; arbitrary Markdown, HTML, filters, templates and scripts are excluded.'],
        'references':['docs/pandoc.md','src/schemaxis/adaptors/pandoc/readiness.json'],
        'operations':{'report':{'purpose':'Publish a structured Word report, standalone HTML document and optional EPUB 3 e-book, preserving declared section order, headings, paragraphs, table cells and embedded PNG imagery.',
            'keywords':['HH:MM:SS.mmm', 'publish report as EPUB', 'EPUB transcript', 'Word report','DOCX','standalone HTML','document','report','section','heading','table','local image','Pandoc JSON AST','transcript','whisper transcript','segments.json','speech recognition','captions','timestamps','milliseconds','dialogue','timecode','HH:MM:SS.mmm','time format','EPUB','EPUB 3','epub3','ebook','e-book','book','language','dc:language','authors','author metadata','document description','dc:creator','dc:description','report author','creator'],
            'semantics':['Trusted JSON AST maps directly to public Header/Para/Table/Image constructors; no authored code.',
                'Both generated documents and fresh native DOCX readback are independently checked against authored report values.',
                'A transcript block reads one retained whisper.cpp segments.json at run time under a closed machine-draft contract, or a schemaxis.timedtext.reviewed/1, reviewed/2 or reviewed/3 document, and expands to a provenance paragraph plus the existing table; no new native mapping. An optional per-block timeFormat shows cue times as integer milliseconds (the default) or as exact HH:MM:SS.mmm. A reviewed status is the author\'s declaration, never verified identity, accuracy or accessibility.',
                'An optional report-level epub object (language only) adds an EPUB 3 publication from the same model with the official Pandoc epub3 writer; the package and content are checked by independent host ZIP/OPF/XHTML inspection and a fresh Pandoc EPUB readback, a bounded structural proof, not EPUBCheck, device rendering or accessibility.',
                'An optional report-level metadata object (authors list and description, plain text only, no other keys) is written by Pandoc into HTML author/description meta elements and title-block author lines, DOCX creator/description properties and Author-style paragraphs and EPUB dc:creator/dc:description and title-page lines; each format is read back by independent host parsers and a fresh Pandoc reader, and the authors and description are author declarations, never verified identity.'],
            'examples':[{'reference':'examples/schemaxis/pandoc-report.json','purpose':'A calibration report with an ordered outline, measured table and local PNG.'},
                {'reference':'examples/schemaxis/pandoc-report-variant.json','purpose':'Change a cell, image display width and heading level to exercise semantic retention.'},
                {'reference':'examples/schemaxis/pandoc-transcript.json','purpose':'A timed transcript or captions as a table of literal millisecond start and end times and dialogue text.'},
                {'reference':'examples/schemaxis/pandoc-transcript-artifact.json','purpose':'Publish a retained whisper.cpp segments.json as a provenance paragraph and a millisecond cue table.'},
                {'reference':'examples/schemaxis/pandoc-transcript-timecode.json','purpose':'Publish the same retained segments.json with cue start and end times as HH:MM:SS.mmm for readers.'},
                {'reference':'examples/schemaxis/pandoc-report-epub.json','purpose':'Publish the report as HTML, DOCX and an EPUB 3 e-book by declaring the language of the text.'},
                {'reference':'examples/schemaxis/pandoc-report-metadata.json','purpose':'Credit a report with two ordered authors and a description in HTML and DOCX.'},
                {'reference':'examples/schemaxis/pandoc-report-metadata-epub.json','purpose':'Change the authors, order and description and also publish an EPUB 3 with the same credits.'},
                {'reference':'examples/schemaxis/pandoc-transcript-mixed-formats.json','purpose':'Two transcript blocks of one report, one in timecodes and one in integer milliseconds.'}]}}}
