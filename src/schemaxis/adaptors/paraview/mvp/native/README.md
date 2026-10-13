This directory contains upstream-derived metadata captured from ParaView 5.13.3,
using its installed server-manager property and proxy-definition APIs. It is not
an independently authored description of ParaView. See ParaView-Copyright.txt
for the upstream notice and terms supplied with the inspected source tree.

The extractor is ../metadata_runtime.py; the explicit inspect-native CLI command
runs it in the application's own interpreter and retains its submitted source.
The reviewed snapshot has no host-specific installation path and includes its
application source-version string, extraction source, coverage and gaps.

Nine top-level Slice properties and their recursive proxy choices are inventoried.
Coverage of XML attributes is selective and enumerated in the JSON. The public
adaptor supports only the mappings reviewed in ../slice_options.py. Retaining
a native option or its help does not make it an executable Schemaxis argument.
