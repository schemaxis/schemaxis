"""Curated intent-level stored-ZIP publication bundle discovery without native imports."""
import json
from importlib.resources import files


def catalogue():
    return {'application': {'label': 'Info-ZIP', 'purpose': 'Package individually chosen publication files (captions, transcripts, audio, reports, images) under safe flat names into one portable stored ZIP with an unsigned inventory, and prove by an independent host reader that every archive byte matches the captured files.',
                            'keywords': ['Info-ZIP', 'ZIP', 'zip archive', 'publication bundle', 'delivery package', 'handoff bundle', 'zip', 'manifest']},
            'searchCases': json.loads(files(__package__).joinpath('search-cases.json').read_text()),
            'requirements': ['bundle: one to sixteen absolute local regular files (at most 32 MiB each and 64 MiB in total), each with a flat portable ASCII member name that has one of the extensions txt, json, srt, vtt, wav, flac, m4a, png, html, docx, epub or pdf.',
                             'A configured Info-ZIP Zip 3.0 zip executable (--infozip, schemaxis configure infozip or SCHEMAXIS_INFOZIP) to create the archive; verification afterwards needs no native program.',
                             'No directory, glob, recursive or symbolic-link input; no extraction, encryption, compression options, ZIP64 or self-extracting archive; contents are opaque and are not sanitised or validated.'],
            'references': ['docs/infozip.md', 'src/schemaxis/adaptors/infozip/readiness.json'],
            'operations': {
                'bundle': {
                    'purpose': 'Package a chosen set of publication files under safe flat names into one stored ZIP with a host-written inventory, and prove every archive byte against the captured files.',
                    'keywords': ['publication bundle', 'zip archive', 'ZIP', 'delivery package', 'handoff bundle', 'package files', 'bundle captions and audio', 'zip files together', 'portable archive', 'manifest inventory', 'Info-ZIP', 'zip'],
                    'semantics': ['Only the files you list are packaged, under the flat names you choose; run directories, receipts and logs are never added. The host adds manifest.json, an unsigned inventory of names, byte counts and SHA-256 digests.',
                                  'Members are stored without compression, so the archive is not smaller than its contents; no compression ratio is claimed. An independent host reader checks every header and byte against the captured files, so verification needs no native program.',
                                  'Contents are opaque: no media, accessibility, security or privacy check is made and nothing is sanitised. For whole-case preservation and restore use the core storage preservation action instead.'],
                    'examples': [{'reference': 'examples/schemaxis/infozip-baseline.json', 'purpose': 'Bundle a text report, an SRT caption file and a JSON note under chosen names.'},
                                 {'reference': 'examples/schemaxis/infozip-variant.json', 'purpose': 'Bundle a small WAV, an empty text file and an HTML page, including binary and empty members.'}]}}}
