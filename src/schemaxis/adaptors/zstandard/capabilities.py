"""Intent-level compression discovery; importing this module loads no codec."""
import json
from importlib.resources import files

PURPOSES={
 'compress':'Reduce a captured file using Zstandard or one of its four compatibility codecs, preserving every original byte.',
 'restore':'Recover original bytes from a captured compressed stream with a bounded fresh native decoder.',
 'inspect':'Inspect complete Zstandard frame boundaries, sizes, windows, dictionary identities and checksums, backed by actual decoding.',
 'trainDictionary':'Learn a reusable, explicitly identified compression dictionary from a captured corpus of related small files.',
 'encodeDelta':'Compress a changed snapshot relative to a captured earlier snapshot, retaining the reference needed for restoration.',
 'concatenate':'Join complete Zstandard streams in a chosen order and prove that restoration yields the corresponding concatenated content.',
 'compareProfiles':'Compare compressed sizes for several format and level choices while proving exact restoration of every candidate.',
 'benchmark':'Measure native in-memory compression and decompression throughput over captured representative content, with independently checked sizes and round trips.',
 'benchmarkDecode':'Measure native in-memory decompression throughput of an existing captured Zstandard stream with its exact dictionary.',
 'inspectDictionary':'Inspect a captured external trained or raw dictionary, including exact identity and fresh native loading in both compressor and decoder.',
 'compressFiles':'Compress a reusable named or recursively selected file set, preserving relative names with bounded captured inputs and collision checks.',
 'restoreFiles':'Restore a captured compressed file set into collision-checked relative names under one aggregate decoded-output budget.'}

KEYWORDS={
 'compress':['compress file','lossless compression','zstd','gzip','xz','lzma','lz4','compression level','fast compression','streaming input','compress pinned snapshot'],
 'restore':['decompress','restore bytes','decode compressed file','dictionary decompression'],
 'inspect':['frame inspection','compressed content size','frame checksum','dictionary ID','skippable frame','compressed metadata'],
 'trainDictionary':['train dictionary','compression corpus','fastCover','Cover','legacy dictionary','small record compression'],
 'encodeDelta':['delta compression','patch from reference','snapshot difference','reference snapshot'],
 'concatenate':['concatenate frames','join compressed streams','multi-frame stream','ordered frame join'],
 'compareProfiles':['compare compression','compression ratio','size comparison','choose compression level'],
 'benchmark':['native benchmark','compression throughput','decompression throughput','benchmark blocks','benchmark levels'],
 'benchmarkDecode':['decode benchmark','decompression benchmark','existing compressed stream throughput'],
 'inspectDictionary':['inspect dictionary','external compression dictionary','dictionary identity','raw dictionary history'],
 'compressFiles':['compress captured directory snapshot','compress directory','batch compression','recursive compression','named file set'],
 'restoreFiles':['restore directory','batch decompression','recursive decompression','restore file set']}


def catalogue():
    return {'application':{'label':'Zstandard','purpose':'Durable lossless compression, dictionary learning, reference deltas and checked compressed-frame workflows.',
                           'keywords':['Zstandard','zstd','compression','compressed scientific data','lossless codec']},
            'requirements':['Configure a trusted Zstandard 1.5.7 executable for creation AND later verification.',
                            'Capture absolute local regular files or a bounded fileSet directory selection: 64 MiB raw, 72 MiB compressed, 128 MiB total; no selected symbolic links.',
                            'A compressed file preserves content bytes, not its original filename, permissions, ownership or modification time.'],
            'references':['docs/zstandard.md','src/schemaxis/adaptors/zstandard/readiness.json'],
            'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
            'operations':{name:{'purpose':purpose,'keywords':KEYWORDS[name],
                'semantics':[
                    'Native execution uses captured inputs and fixed argument arrays. Fresh verification reads the publications, not historical command receipts.',
                    ('Sizes and content are verified; recorded timing is observational and is explicitly not authenticated during later verification.' if name in ('compareProfiles','benchmark','benchmarkDecode') else
                     'Retain the run directory and its captured dependencies. Verification can proceed after the original source paths disappear.')],
                'examples':[{'reference':'examples/schemaxis/zstandard-'+name+'.json','purpose':purpose}]}
                for name,purpose in PURPOSES.items()}}
