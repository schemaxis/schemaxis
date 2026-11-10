"""Curated intent-level EPUB standards-check discovery without native imports."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'EPUBCheck', 'purpose': 'Check one local EPUB publication against the official EPUB standard with the W3C EPUBCheck tool, accepting it only when the checker reports no fatal, error or warning messages and a fresh native check of the held bytes agrees.',
                            'keywords': ['EPUBCheck', 'EPUB validation', 'EPUB conformance', 'EPUB standards check', 'W3C EPUB', 'publishing handoff', 'ebook check', 'epubcheck']},
            'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
            'requirements': ['validate: an absolute local .epub ZIP file of at most 32 MiB, 2000 members and 64 MiB uncompressed, with no encrypted members, symbolic links, entity declarations or DOCTYPE SYSTEM identifiers outside the EPUBCheck local DTD catalogue, and XML members (by extension or as declared by the package under any file name) in UTF-8 or byte-order-marked UTF-16.',
                             'A configured trusted EPUBCheck 5.4 launcher (--epubcheck, schemaxis configure epubcheck or SCHEMAXIS_EPUBCHECK): a fixed executable that starts the official JAR with its lib directory and Java; verification needs the same launcher.',
                             'Default EPUB profile only; no authored flags, profiles, plugins, custom message severities. The checker runs with its fixed offline property (not an operating-system network boundary). Zero findings is a scoped tool result, not rendering, accessibility or legal certification.'],
            'references': ['docs/epubcheck.md', 'src/schemaxis/adaptors/epubcheck/readiness.json'],
            'operations': {
                'validate': {
                    'purpose': 'Check a finished EPUB with the official EPUBCheck and publish its JSON assessment and a summary only when it reports no fatal, error or warning messages, proven again by a fresh native check of the held bytes.',
                    'keywords': ['EPUBCheck', 'validate EPUB', 'check EPUB', 'EPUB conformance', 'EPUB standards', 'ebook validation', 'publishing handoff check', 'W3C EPUB', 'epubcheck', 'EPUB errors and warnings', 'publication check'],
                    'semantics': ['EPUBCheck is the standards authority; the host only preflights the ZIP container (size, safe unique names, no encryption, links, entities, non-catalogue DTDs or unsupported XML encodings, indexing the container rootfiles and manifest XML media types) and checks the native JSON report for typed structure, count and item consistency.',
                                  'A rejected publication fails with EPUBCHECK_REJECTED and publishes nothing; findings stay as rejected-assessment.json evidence. An accepted one publishes assessment.json and epubcheck-summary.json. Zero findings is not a guarantee of rendering, accessibility or legal compliance.'],
                    'related': [],
                    'examples': [{'reference': 'examples/schemaxis/epubcheck-baseline.json', 'purpose': 'Check a tiny valid EPUB 3 publication and publish the accepted assessment.'},
                                 {'reference': 'examples/schemaxis/epubcheck-variant.json', 'purpose': 'Check an eight-file EPUB 3 with two chapters, a stylesheet and an image.'}]}}}
