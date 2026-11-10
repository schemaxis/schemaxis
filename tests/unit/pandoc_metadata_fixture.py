"""The multilingual EPUB fixture report plus a bounded `metadata` declaration, and the genuine Pandoc 3.12.1 outputs written for it.

`examples/schemaxis/fixtures/pandoc-metadata` holds the real HTML, DOCX, EPUB and readback files that Pandoc 3.12.1 wrote for `document()`; host
tests replay them through the unchanged `run` and `verify` code, so every inspector reads genuine writer output. Nothing here is a Pandoc
implementation. After a reviewed Pandoc change run tools/qualify_pandoc_metadata.py against that Pandoc into a fresh output directory and copy the
files named in its report from the `a/metadata` run; the qualifier asserts the committed files equal the live output and fails until they do.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
import pandoc_epub_fixture as fx  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'examples/schemaxis/fixtures/pandoc-metadata'
AUTHORS = ['Zoë Müller', '李雷 (Li Lei)', 'Rob & <b> "Q" O\'Neil']
DESCRIPTION = 'Résumé des mesures — 校准 & <test> "quoted" \'single\'; العربية.'


def metadata(): return {'authors': list(AUTHORS), 'description': DESCRIPTION}


def document(directory, declared=True, language=fx.LANGUAGE):
    """The EPUB fixture report; `declared=False` leaves the report exactly as the earlier fixture, a dict replaces the metadata."""
    report = fx.document(directory, language)
    if declared is not False: report['metadata'] = metadata() if declared is True else declared
    return report


def stand_in(directory, fixture=FIXTURE): return fx.stand_in(directory, fixture)
