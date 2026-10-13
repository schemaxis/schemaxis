# Studio supplied help — 2026-10-06

Studio now supplies a Help window in every interface role, opened from the top
bar, rail, command palette or F1. Workbench Help selects the current node's
operation reference and preserves unsaved input. Topics support search/category
filtering, section navigation, internal links, back/forward history, copyable code
and local flow chart rendering. Selected topics persist with Studio tabs.

The package includes 948 topics from 184 repository files, including all 655
ParaView operation identifiers, shared dollar syntax, settings/function signatures,
other adaptor references and linked examples/schemas. Topics load individually;
large schema/source bodies are compressed and expose download/full-text controls.
Markdown remains the editable source. `tools/generate_studio_help.py --check`
verifies supplied help is current without writing files. This is help coverage,
not native qualification of the catalogue.

Checks newly run for this change:

- Python host suite: 1,083 tests, successful, 22 skipped.
- Browser-independent JavaScript suite: 153 tests, successful.
- Real-server Help browser checks: successful in light and dark themes, including
  search, navigation, copying, current-operation selection, preservation of unsaved
  Workbench input, user-role access and tab restoration.
- Existing Studio shell browser smoke checks: successful in both themes.
- Studio HTTP suite: 17 tests, successful, including static packaged JSON serving.
- Help inventory checks: every indexed topic and packaged local target exists;
  heading anchors match rendering; 655 ParaView operation topics; search and
  flow-chart branch/loop tests passed.
- Wheel packaging: 949 help JSON assets (948 topics plus index), UI/CSS assets
  included, browser test harnesses excluded.
- Extracted-wheel HTTP smoke: installed help index, guide and UI assets served
  without repository documentation files.
- Screenshots inspected in both themes; flow chart text contrast corrected for
  the dark theme. No new native algorithm qualification is claimed.

Reproduce:

```sh
PYTHONPATH=src python3 tools/generate_paraview_guide.py
python3 tools/generate_studio_help.py
python3 tools/generate_studio_help.py --check
PYTHONPATH=src python3 -m unittest discover -s tests/unit -q
node --test src/schemaxis/studio_ui/tests/help.test.mjs
node --test src/schemaxis/studio_ui/tests/help.browser.test.mjs \
  src/schemaxis/studio_ui/tests/shell.browser.test.mjs
```

Browser checks require a local loopback server and headless Chromium. Large
schema expansion uses the browser's native gzip decompression; no CDN, Mermaid,
Markdown library or native ParaView process is needed to browse help. The local
Studio server remains required. The renderer supports the Markdown constructs and
simple flow-chart grammar used by the guide; raw HTML is inserted as text.
