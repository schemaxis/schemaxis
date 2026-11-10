"""Strict, closed reader for a machine-draft or a human-reviewed timed transcript.

Four documents are accepted: the whisper.cpp machine segment evidence,
``schemaxis.whispercpp.segments/1``, and the separately versioned
``schemaxis.timedtext.reviewed/1`` (text replacements), ``schemaxis.timedtext.reviewed/2`` (text replacements and
explicit cue deletions) and ``schemaxis.timedtext.reviewed/3`` (additionally author-edited cue times) that host-only
correction steps publish. Every object is closed: a
missing or an extra key is a fault, so a changed or richer document needs a new declared ``version``
and a reviewed update here rather than a looser reader. The machine version never accepts review keys. The input is data: it is never interpreted as
blocks, markup, paths or code, and nothing here reads a file.

``parse`` and ``validate`` return a normalised ``schemaxis.timedtext/1`` view that
consumers may rely on: a fixed ``machine-draft`` status, the language, the audio duration,
the pinned digests, and ordered integral-millisecond ``[startMs, endMs)`` cues. The producer's
optional ``segmentation`` member (a cue-length target that is observed, never enforced) is a closed
object and is carried as ``segmentation``, or ``None`` when absent. A review
status other than ``machine-draft`` is refused on the machine version. The reviewed version carries an
author-declared status (``human-corrected`` or ``human-reviewed-unchanged``), a bounded note, the pinned
machine-draft basis and the corrected indices; the status is a declaration that this module cannot verify,
never an identity check or a certification of accuracy. Hashes and structure never certify recognition accuracy.
``reviewed/2`` additionally records the pinned draft's cue count, the deleted source indices, the source index of every
retained cue and the corrected source indices. Its cues are numbered contiguously from zero as published; the source indices
tie them back to the pinned machine draft. It alone may hold no cues, and only when every one of a nonempty pinned draft's cues
is recorded as deleted. The machine draft and ``reviewed/1`` still refuse an empty cue list.

``reviewed/3`` is a separate version because ``reviewed/1`` and ``reviewed/2`` promise the original machine timestamps and are never
reinterpreted. It carries every ``reviewed/2`` member and adds ``timingEditedIndices`` (source indices whose published start or end
differs from the pinned draft), ``timingEditCount``, ``originalTimings`` (the pinned draft's start and end of every retained cue,
by source index) and a ``timingPolicy`` text, and a third declared claim, ``synchronizationCertified: false``. The validator
proves that the edited indices are exactly the retained cues whose published interval differs from the recorded original; the
published times themselves are checked by the shared rules (ordered, nonoverlapping, inside the audio duration), so edited times
are never clamped, reordered or rounded here. The recorded original times are claims about the pinned draft that this module cannot
check without it; the correction route replays them against the draft bytes. A declared timing edit is never a certificate that
the captions are synchronized with the audio.

Budgets are deliberately smaller than the producer's own, so a document that is accepted is
small enough to publish whole; an oversize document is refused, never truncated.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from .faults import Fault, SchemaxisError

SOURCE_VERSION = "schemaxis.whispercpp.segments/1"
REVIEWED_VERSION = "schemaxis.timedtext.reviewed/1"
REVIEWED2_VERSION = "schemaxis.timedtext.reviewed/2"
REVIEWED3_VERSION = "schemaxis.timedtext.reviewed/3"
REVIEWED_STATUSES = ("human-corrected", "human-reviewed-unchanged")
MAX_NOTE_CHARACTERS = 500
VERSION = "schemaxis.timedtext/1"
STATUS = "machine-draft"
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
MAX_CUES = 512
MAX_CUE_CHARACTERS = 256
MAX_TOTAL_CHARACTERS = 32768
MAX_NUMBER = 2**53

HEX = re.compile(r"[0-9a-f]{64}")
LANGUAGE = re.compile(r"[a-z]{2,3}")
# Code points that draw nothing alone; a cue made only of these reads as blank.
INVISIBLE = frozenset("ᅟᅠㅤﾠ⠀")
INVISIBLE_CATEGORIES = frozenset(("Cc", "Cf", "Cs", "Co", "Zs", "Zl", "Zp", "Mn", "Mc", "Me"))
BIDIRECTIONAL = frozenset("‪‫‬‭‮⁦⁧⁨⁩")
RECOVERY = (
    "Provide the segments.json that the whisper.cpp route published and verified, unedited. "
    "Other layouts, extra members and review states are refused until a versioned contract defines them."
)
SOURCE_KEYS = (
    "version", "language", "timeUnit", "audio", "model", "nativeJsonSha256", "segmentCount", "segments", "review")
# Present only when the producer was asked for a cue-length target; absent documents keep exactly SOURCE_KEYS.
SEGMENTATION_KEYS = (
    "maxSegmentLength", "nativeOptions", "enforced", "unit", "cueCount", "cuesOverTarget", "statement")
AUDIO_KEYS = ("sha256", "bytes", "frames", "rate", "channels", "durationMs", "durationRemainderFrames")
MODEL_KEYS = ("sha256", "bytes")
CUE_KEYS = ("index", "startMs", "endMs", "text")
REVIEW_KEYS = ("accuracyCertified", "humanReviewRequired", "statement", "policy")
POLICY_KEYS = ("timing", "text")
REVIEWED_REVIEW_KEYS = (
    "status", "accuracyCertified", "identityVerified", "statement", "note", "basis", "correctionCount", "correctedIndices", "policy")
BASIS_KEYS = ("version", "sha256", "bytes")
REVIEWED2_REVIEW_KEYS = (
    "status", "accuracyCertified", "identityVerified", "statement", "note", "basis", "correctionCount", "correctedIndices",
    "deletionCount", "deletedSourceIndices", "retainedSourceIndices", "policy")
BASIS2_KEYS = ("version", "sha256", "bytes", "cueCount")
REVIEWED3_REVIEW_KEYS = (
    "status", "accuracyCertified", "identityVerified", "synchronizationCertified", "statement", "note", "basis", "correctionCount",
    "correctedIndices", "deletionCount", "deletedSourceIndices", "retainedSourceIndices", "timingEditCount", "timingEditedIndices",
    "originalTimings", "timingPolicy", "policy")
ORIGINAL_TIMING_KEYS = ("sourceIndex", "startMs", "endMs")


def refuse(code: str, message: str, location: str, recovery: str | None = None, **observed: Any) -> None:
    raise SchemaxisError(Fault(code, message, location, "pipeline", observed=observed, recovery=recovery or RECOVERY))


def whole(value: Any) -> bool:
    return type(value) is int and 0 <= value <= MAX_NUMBER


def audio_limit(audio: dict) -> int:
    """The latest end, in whole milliseconds, that a cue may have: the audio duration rounded up to the next millisecond."""
    return audio["durationMs"] + (1 if audio["durationRemainderFrames"] else 0)


def closed(value: Any, names: tuple[str, ...], location: str, code: str = "TIMED_TEXT_UNKNOWN_KEY") -> dict:
    if not isinstance(value, dict):
        refuse("TIMED_TEXT_INVALID", "expected an object", location)
    missing = [name for name in names if name not in value]
    extra = sorted(set(value) - set(names))
    if extra:
        refuse(code, "unsupported members; the contract is closed", location, extra=extra)
    if missing:
        refuse("TIMED_TEXT_INVALID", "required members are absent", location, missing=missing)
    return value


def digest(value: Any, location: str) -> str:
    if not isinstance(value, str) or not HEX.fullmatch(value):
        refuse("TIMED_TEXT_INVALID", "use 64 lowercase hexadecimal digits", location)
    return value


def count(value: Any, location: str, minimum: int = 1) -> int:
    if not whole(value) or value < minimum:
        refuse("TIMED_TEXT_INVALID", f"use an integer of at least {minimum} (booleans and fractions are refused)", location)
    return value


def strict_json(data: bytes, location: str = "$") -> Any:
    """Parse UTF-8 JSON without a byte-order mark, duplicate keys, non-finite numbers (NaN, Infinity and a literal that overflows to infinity, such as 1e400) or deep nesting."""

    def pairs(items: list) -> dict:
        if len({key for key, _ in items}) != len(items):
            raise ValueError("duplicate JSON object key")
        return dict(items)

    def constant(name: str) -> None:
        raise ValueError("non-finite JSON number " + name)

    def real(text: str) -> float:
        value = float(text)
        if value in (float("inf"), float("-inf")):
            raise ValueError("non-finite JSON number " + text[:40] + " (overflows to infinity)")
        return value

    if not isinstance(data, (bytes, bytearray)):
        refuse("TIMED_TEXT_INVALID_JSON", "expected the document bytes", location)
    if len(data) > MAX_DOCUMENT_BYTES:
        refuse("TIMED_TEXT_RESOURCE_LIMIT", f"document exceeds {MAX_DOCUMENT_BYTES} bytes", location,
               "Publish a shorter recording or split the transcript before publication.", bytes=len(data))
    try:
        text = bytes(data).decode("utf-8")
        if text.startswith("﻿"):
            raise ValueError("byte-order mark")
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant, parse_float=real)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        refuse("TIMED_TEXT_INVALID_JSON", "document is not strict UTF-8 JSON: " + str(error)[:160], location)


def cue_text_problem(text: str) -> str | None:
    """Why checked text cannot be published as one plain-text cue, or None."""
    if text != text.strip(" "):
        return "cue text must not begin or end with a space"
    if not text:
        return "cue text must not be blank"
    if any(unicodedata.category(c) in ("Cc", "Cs", "Zl", "Zp") for c in text):
        return "cue text must not contain control, surrogate or line-separator characters"
    if "�" in text or any(c in text for c in "<>{}") or "-->" in text:
        return "cue text must not contain a replacement character, markup brackets or the caption arrow"
    if any(c in BIDIRECTIONAL for c in text):
        return "cue text must not contain bidirectional embeddings, overrides or isolates"
    if all(c in INVISIBLE or invisible_scalar(c) or unicodedata.category(c) in INVISIBLE_CATEGORIES for c in text):
        return "cue text has no visible character (only spaces, joiners, format controls, fillers or combining marks)"
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "cue text is not valid Unicode scalar text"
    return None


def invisible_scalar(char: str) -> bool:
    code = ord(char)
    return unicodedata.category(char) == "Co" or 0xFDD0 <= code <= 0xFDEF or code & 0xFFFE == 0xFFFE


def validate(document: Any, location: str = "$") -> dict:
    """Check a decoded document against the closed contract and return the normalised view."""
    if not isinstance(document, dict):
        refuse("TIMED_TEXT_INVALID", "expected a JSON object", location)
    version = document.get("version")
    if version not in (SOURCE_VERSION, REVIEWED_VERSION, REVIEWED2_VERSION, REVIEWED3_VERSION):
        refuse("TIMED_TEXT_UNSUPPORTED_VERSION", "unsupported timed-text document version", location + ".version",
               f"Only {SOURCE_VERSION} (machine draft), {REVIEWED_VERSION}, {REVIEWED2_VERSION} and {REVIEWED3_VERSION} (author-declared human review) are read; "
               "any other layout needs its own declared version.", observed_version=repr(version)[:80])
    reviewed = version in (REVIEWED_VERSION, REVIEWED2_VERSION, REVIEWED3_VERSION)
    with_deletions = version in (REVIEWED2_VERSION, REVIEWED3_VERSION)
    closed(document, SOURCE_KEYS + (("segmentation",) if "segmentation" in document else ()), location)
    language = document["language"]
    if not isinstance(language, str) or not LANGUAGE.fullmatch(language):
        refuse("TIMED_TEXT_INVALID", "use a lowercase two or three letter language code", location + ".language")
    if document["timeUnit"] != "millisecond":
        refuse("TIMED_TEXT_INVALID", "timeUnit must be millisecond", location + ".timeUnit")
    audio = closed(document["audio"], AUDIO_KEYS, location + ".audio")
    digest(audio["sha256"], location + ".audio.sha256")
    for name in ("bytes", "frames", "rate", "channels"):
        count(audio[name], f"{location}.audio.{name}")
    duration = count(audio["durationMs"], location + ".audio.durationMs", 0)
    remainder = count(audio["durationRemainderFrames"], location + ".audio.durationRemainderFrames", 0)
    if (duration, remainder) != (audio["frames"] * 1000 // audio["rate"], audio["frames"] * 1000 % audio["rate"]):
        refuse("TIMED_TEXT_INVALID", "audio duration disagrees with frames and rate", location + ".audio")
    limit = duration + (1 if remainder else 0)
    model = closed(document["model"], MODEL_KEYS, location + ".model")
    digest(model["sha256"], location + ".model.sha256")
    count(model["bytes"], location + ".model.bytes")
    digest(document["nativeJsonSha256"], location + ".nativeJsonSha256")
    review = document["review"]
    if not reviewed:
        if isinstance(review, dict) and set(review) != set(REVIEW_KEYS):
            refuse("TIMED_TEXT_REVIEW_UNSUPPORTED", "review members differ from the machine-draft contract", location + ".review",
                   f"A human review status is never read from {SOURCE_VERSION}; publish it with {REVIEWED_VERSION}.", members=sorted(review))
        closed(review, REVIEW_KEYS, location + ".review", "TIMED_TEXT_REVIEW_UNSUPPORTED")
        if review["accuracyCertified"] is not False or review["humanReviewRequired"] is not True:
            refuse("TIMED_TEXT_REVIEW_UNSUPPORTED", "only an uncertified machine draft that requires human review is accepted",
                   location + ".review", f"Machine output is always a draft; a human-reviewed status needs {REVIEWED_VERSION}.")
        if not isinstance(review["statement"], str) or not 1 <= len(review["statement"]) <= 1024:
            refuse("TIMED_TEXT_INVALID", "review statement must be text of 1 to 1024 characters", location + ".review.statement")
        policy = closed(review["policy"], POLICY_KEYS, location + ".review.policy")
        for name in POLICY_KEYS:
            if not isinstance(policy[name], str) or not 1 <= len(policy[name]) <= 1024:
                refuse("TIMED_TEXT_INVALID", "policy text must be 1 to 1024 characters", f"{location}.review.policy.{name}")
    segments = document["segments"]
    # Only reviewed/2 and reviewed/3 may hold no cues, and the deletion check then proves that every pinned cue was deleted.
    if not isinstance(segments, list) or (not segments and not with_deletions):
        refuse("TIMED_TEXT_INVALID", "segments must be a nonempty array", location + ".segments")
    if len(segments) > MAX_CUES:
        refuse("TIMED_TEXT_RESOURCE_LIMIT", f"more than {MAX_CUES} cues", location + ".segments",
               "Publish a shorter recording or split the transcript before publication.", cues=len(segments))
    if document["segmentCount"] != len(segments) or type(document["segmentCount"]) is not int:
        refuse("TIMED_TEXT_INVALID", "segmentCount disagrees with the segments array", location + ".segmentCount")
    target = None
    if "segmentation" in document:
        target = closed(document["segmentation"], SEGMENTATION_KEYS, location + ".segmentation")
        at = location + ".segmentation"
        if type(target["maxSegmentLength"]) is not int or not 16 <= target["maxSegmentLength"] <= 200:
            refuse("TIMED_TEXT_INVALID", "maxSegmentLength must be an integer from 16 to 200", at + ".maxSegmentLength")
        if target["nativeOptions"] != ["-ml", str(target["maxSegmentLength"]), "-sow"] or target["enforced"] is not False:
            refuse("TIMED_TEXT_INVALID", "segmentation must record the -ml/-sow target as not enforced", at)
        for name in ("unit", "statement"):
            if not isinstance(target[name], str) or not 1 <= len(target[name]) <= 2048:
                refuse("TIMED_TEXT_INVALID", "segmentation text must be 1 to 2048 characters", f"{at}.{name}")
        if target["cueCount"] != len(segments) or type(target["cueCount"]) is not int:
            refuse("TIMED_TEXT_INVALID", "segmentation cueCount disagrees with the segments array", at + ".cueCount")
    cues, previous, total = [], 0, 0
    for position, item in enumerate(segments):
        at = f"{location}.segments[{position}]"
        item = closed(item, CUE_KEYS, at)
        if item["index"] != position or type(item["index"]) is not int:
            refuse("TIMED_TEXT_INVALID", "cue indexes must be contiguous from zero", at + ".index", position=position)
        start, end = item["startMs"], item["endMs"]
        if not whole(start) or not whole(end):
            refuse("TIMED_TEXT_TIMING", "times must be integer milliseconds", at)
        if not 0 <= start < end:
            refuse("TIMED_TEXT_TIMING", "a cue needs 0 <= startMs < endMs", at, startMs=start, endMs=end)
        if start < previous:
            refuse("TIMED_TEXT_TIMING", "cues must be ordered and nonoverlapping", at, startMs=start, previousEndMs=previous)
        if end > limit:
            refuse("TIMED_TEXT_TIMING", "cue ends beyond the recorded audio duration", at, endMs=end, limitMs=limit)
        text = item["text"]
        if not isinstance(text, str):
            refuse("TIMED_TEXT_CUE_TEXT", "cue text must be a string", at + ".text")
        problem = cue_text_problem(text)
        if problem:
            refuse("TIMED_TEXT_CUE_TEXT", problem, at + ".text", "Correct the cue in the producing route; invalid text is never repaired or dropped here.")
        total += len(text)
        if len(text) > MAX_CUE_CHARACTERS or total > MAX_TOTAL_CHARACTERS:
            refuse("TIMED_TEXT_RESOURCE_LIMIT", f"a cue is limited to {MAX_CUE_CHARACTERS} characters and the document to {MAX_TOTAL_CHARACTERS}",
                   at + ".text", "Use shorter cues (for example the whisper.cpp cue-length option) or a shorter recording.", characters=len(text))
        cues.append({"startMs": start, "endMs": end, "text": text})
        previous = end
    segmentation = None
    if target is not None:
        over = sum(len(cue["text"]) > target["maxSegmentLength"] for cue in cues)
        if target["cuesOverTarget"] != over or type(target["cuesOverTarget"]) is not int:
            refuse("TIMED_TEXT_INVALID", "segmentation cuesOverTarget disagrees with the cue text", location + ".segmentation.cuesOverTarget", cuesOver=over)
        segmentation = {"maxSegmentLength": target["maxSegmentLength"], "cuesOverTarget": over, "enforced": False}
    view = {"version": VERSION, "source": REVIEWED_VERSION if reviewed else SOURCE_VERSION, "status": STATUS, "language": language,
            "segmentation": segmentation, "durationMs": duration, "audioSha256": audio["sha256"], "modelSha256": model["sha256"],
            "nativeJsonSha256": document["nativeJsonSha256"], "cues": cues}
    if reviewed:
        view["source"] = version
        if version == REVIEWED3_VERSION:
            declared = reviewed_timings(review, cues, limit, location + ".review")
        else:
            declared = (reviewed_deletions if with_deletions else reviewed_review)(review, len(cues), location + ".review")
        view["status"] = declared["status"]
        view["review"] = declared
    return view


def reviewed_review(review: Any, cue_count: int, location: str) -> dict:
    """The closed, author-declared review of a reviewed document; the status is provenance, never verified."""
    review = closed(review, REVIEWED_REVIEW_KEYS, location, "TIMED_TEXT_REVIEW_UNSUPPORTED")
    if review["status"] not in REVIEWED_STATUSES:
        refuse("TIMED_TEXT_REVIEW_UNSUPPORTED", "review status must be human-corrected or human-reviewed-unchanged", location + ".status",
               "Only the two declared review statuses are read; machine output stays a machine draft.", observed_status=repr(review["status"])[:80])
    if review["accuracyCertified"] is not False or review["identityVerified"] is not False:
        refuse("TIMED_TEXT_REVIEW_UNSUPPORTED", "a review never certifies accuracy or verifies the identity of the reviewer", location,
               "Set accuracyCertified and identityVerified to false; they are claims this contract cannot make.")
    if not isinstance(review["statement"], str) or not 1 <= len(review["statement"]) <= 1024:
        refuse("TIMED_TEXT_INVALID", "review statement must be text of 1 to 1024 characters", location + ".statement")
    problem = note_problem(review["note"])
    if problem:
        refuse("TIMED_TEXT_INVALID", problem, location + ".note", f"Use a plain-text note of 1 to {MAX_NOTE_CHARACTERS} characters.")
    basis = closed(review["basis"], BASIS_KEYS, location + ".basis")
    if basis["version"] != SOURCE_VERSION:
        refuse("TIMED_TEXT_INVALID", f"the review basis must be a {SOURCE_VERSION} machine draft", location + ".basis.version")
    digest(basis["sha256"], location + ".basis.sha256")
    count(basis["bytes"], location + ".basis.bytes")
    indices = review["correctedIndices"]
    if (not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < cue_count for i in indices)
            or indices != sorted(set(indices)) or type(review["correctionCount"]) is not int or review["correctionCount"] != len(indices)):
        refuse("TIMED_TEXT_INVALID", "correctedIndices must be unique ascending cue indexes and correctionCount must equal their number", location + ".correctedIndices")
    if (review["status"] == "human-corrected") != bool(indices):
        refuse("TIMED_TEXT_INVALID", "human-corrected needs at least one corrected cue and human-reviewed-unchanged needs none", location + ".status")
    policy = closed(review["policy"], POLICY_KEYS, location + ".policy")
    for name in POLICY_KEYS:
        if not isinstance(policy[name], str) or not 1 <= len(policy[name]) <= 1024:
            refuse("TIMED_TEXT_INVALID", "policy text must be 1 to 1024 characters", f"{location}.policy.{name}")
    return {"status": review["status"], "note": review["note"], "basisSha256": basis["sha256"], "basisBytes": basis["bytes"],
            "correctionCount": len(indices), "correctedIndices": list(indices), "accuracyCertified": False, "identityVerified": False}


def whole_list(value: Any, limit: int) -> bool:
    """A strictly ascending list of unique source indices, each below the limit."""
    return (isinstance(value, list) and all(type(i) is int and 0 <= i < limit for i in value)
            and all(a < b for a, b in zip(value, value[1:])))


def reviewed_deletions(review: Any, cue_count: int, location: str, timing_edits: int | None = None) -> dict:
    """The closed, author-declared review of a reviewed/2 document, checked for consistency with the pinned draft's cue count.

    The cue list, the deleted source indices and the retained source indices must partition the draft's cues exactly, so a document
    with no cues is accepted only when every cue of a nonempty pinned draft is recorded as deleted. ``timing_edits`` is None for a
    reviewed/2 document; reviewed/3 passes its number of edited cue times, which also make ``human-corrected`` the only valid status."""
    review = closed(review, REVIEWED2_REVIEW_KEYS, location, "TIMED_TEXT_REVIEW_UNSUPPORTED")
    if review["status"] not in REVIEWED_STATUSES:
        refuse("TIMED_TEXT_REVIEW_UNSUPPORTED", "review status must be human-corrected or human-reviewed-unchanged", location + ".status",
               "Only the two declared review statuses are read; machine output stays a machine draft.", observed_status=repr(review["status"])[:80])
    if review["accuracyCertified"] is not False or review["identityVerified"] is not False:
        refuse("TIMED_TEXT_REVIEW_UNSUPPORTED", "a review never certifies accuracy or verifies the identity of the reviewer", location,
               "Set accuracyCertified and identityVerified to false; they are claims this contract cannot make.")
    if not isinstance(review["statement"], str) or not 1 <= len(review["statement"]) <= 1024:
        refuse("TIMED_TEXT_INVALID", "review statement must be text of 1 to 1024 characters", location + ".statement")
    problem = note_problem(review["note"])
    if problem:
        refuse("TIMED_TEXT_INVALID", problem, location + ".note", f"Use a plain-text note of 1 to {MAX_NOTE_CHARACTERS} characters.")
    basis = closed(review["basis"], BASIS2_KEYS, location + ".basis")
    if basis["version"] != SOURCE_VERSION:
        refuse("TIMED_TEXT_INVALID", f"the review basis must be a {SOURCE_VERSION} machine draft", location + ".basis.version")
    digest(basis["sha256"], location + ".basis.sha256")
    count(basis["bytes"], location + ".basis.bytes")
    source = count(basis["cueCount"], location + ".basis.cueCount")
    if source > MAX_CUES:
        refuse("TIMED_TEXT_INVALID", f"the pinned draft cannot have more than {MAX_CUES} cues", location + ".basis.cueCount")
    deleted, retained, corrected = review["deletedSourceIndices"], review["retainedSourceIndices"], review["correctedIndices"]
    for name, value in (("deletedSourceIndices", deleted), ("retainedSourceIndices", retained), ("correctedIndices", corrected)):
        if not whole_list(value, source):
            refuse("TIMED_TEXT_INVALID", "use unique ascending source cue indexes inside the pinned draft", f"{location}.{name}", source_cues=source)
    if type(review["deletionCount"]) is not int or review["deletionCount"] != len(deleted):
        refuse("TIMED_TEXT_INVALID", "deletionCount must equal the number of deleted source indexes", location + ".deletionCount")
    if type(review["correctionCount"]) is not int or review["correctionCount"] != len(corrected):
        refuse("TIMED_TEXT_INVALID", "correctionCount must equal the number of corrected source indexes", location + ".correctionCount")
    if len(retained) != cue_count:
        refuse("TIMED_TEXT_INVALID", "retainedSourceIndices must name the source cue of every published cue", location + ".retainedSourceIndices",
               published=cue_count, mapped=len(retained))
    if set(deleted) & set(retained) or sorted(deleted + retained) != list(range(source)):
        refuse("TIMED_TEXT_INVALID", "deleted and retained source indexes must partition the pinned draft's cues exactly", location + ".deletedSourceIndices",
               source_cues=source)
    if not set(corrected) <= set(retained):
        refuse("TIMED_TEXT_INVALID", "a corrected source index must be one of the retained cues; a deleted cue is not also replaced", location + ".correctedIndices")
    if timing_edits is None:
        if (review["status"] == "human-corrected") != bool(deleted or corrected):
            refuse("TIMED_TEXT_INVALID", "human-corrected needs at least one corrected or deleted cue and human-reviewed-unchanged needs neither", location + ".status")
    elif (review["status"] == "human-corrected") != bool(deleted or corrected or timing_edits):
        refuse("TIMED_TEXT_INVALID", "human-corrected needs at least one corrected cue, deleted cue or edited cue time and human-reviewed-unchanged needs none", location + ".status")
    policy = closed(review["policy"], POLICY_KEYS, location + ".policy")
    for name in POLICY_KEYS:
        if not isinstance(policy[name], str) or not 1 <= len(policy[name]) <= 1024:
            refuse("TIMED_TEXT_INVALID", "policy text must be 1 to 1024 characters", f"{location}.policy.{name}")
    return {"status": review["status"], "note": review["note"], "basisSha256": basis["sha256"], "basisBytes": basis["bytes"],
            "correctionCount": len(corrected), "correctedIndices": list(corrected), "accuracyCertified": False, "identityVerified": False,
            "sourceCueCount": source, "deletionCount": len(deleted), "deletedSourceIndices": list(deleted), "retainedSourceIndices": list(retained)}


def reviewed_timings(review: Any, cues: list[dict], limit: int, location: str) -> dict:
    """The closed, author-declared review of a reviewed/3 document: the reviewed/2 facts plus author-edited cue times.

    Everything reviewed/2 proves is proved here too. In addition the recorded original times must be integral, ordered,
    nonoverlapping and inside the audio duration, there must be one for every retained cue in source order, and the declared edited
    source indices must be exactly the retained cues whose published interval differs from its recorded original. Nothing here can
    compare the originals with the pinned draft, so they are claims that the correction route replays against the draft bytes."""
    review = closed(review, REVIEWED3_REVIEW_KEYS, location, "TIMED_TEXT_REVIEW_UNSUPPORTED")
    if review["synchronizationCertified"] is not False:
        refuse("TIMED_TEXT_REVIEW_UNSUPPORTED", "a review never certifies accuracy, audio synchronization or the identity of the reviewer", location,
               "Set accuracyCertified, identityVerified and synchronizationCertified to false; they are claims this contract cannot make.")
    edited = review["timingEditedIndices"]
    declared = reviewed_deletions({name: review[name] for name in REVIEWED2_REVIEW_KEYS}, len(cues), location,
                                  timing_edits=len(edited) if isinstance(edited, list) else 0)
    source, retained = declared["sourceCueCount"], declared["retainedSourceIndices"]
    if (not whole_list(edited, source) or not set(edited) <= set(retained)
            or type(review["timingEditCount"]) is not int or review["timingEditCount"] != len(edited)):
        refuse("TIMED_TEXT_INVALID", "timingEditedIndices must be unique ascending retained source indexes and timingEditCount must equal their number",
               location + ".timingEditedIndices", source_cues=source)
    originals = review["originalTimings"]
    if not isinstance(originals, list) or len(originals) != len(retained):
        refuse("TIMED_TEXT_INVALID", "originalTimings must record the pinned draft's start and end of every retained cue, in source order",
               location + ".originalTimings", published=len(retained), recorded=len(originals) if isinstance(originals, list) else None)
    previous, recorded = 0, []
    for position, item in enumerate(originals):
        at = f"{location}.originalTimings[{position}]"
        item = closed(item, ORIGINAL_TIMING_KEYS, at)
        if type(item["sourceIndex"]) is not int or item["sourceIndex"] != retained[position]:
            refuse("TIMED_TEXT_INVALID", "originalTimings must follow retainedSourceIndices exactly", at + ".sourceIndex", expected=retained[position])
        start, end = item["startMs"], item["endMs"]
        if not whole(start) or not whole(end):
            refuse("TIMED_TEXT_TIMING", "original times must be integer milliseconds", at)
        if not 0 <= start < end <= limit or start < previous:
            refuse("TIMED_TEXT_TIMING", "recorded original times must be ordered, nonoverlapping and inside the audio duration", at, startMs=start, endMs=end, limitMs=limit)
        previous = end
        recorded.append({"sourceIndex": item["sourceIndex"], "startMs": start, "endMs": end})
    changed = [retained[position] for position, cue in enumerate(cues)
               if (cue["startMs"], cue["endMs"]) != (recorded[position]["startMs"], recorded[position]["endMs"])]
    if changed != edited:
        refuse("TIMED_TEXT_INVALID", "timingEditedIndices must be exactly the retained source cues whose published start or end differs from the recorded original",
               location + ".timingEditedIndices", changed=changed)
    if not isinstance(review["timingPolicy"], str) or not 1 <= len(review["timingPolicy"]) <= 1024:
        refuse("TIMED_TEXT_INVALID", "timing policy text must be 1 to 1024 characters", location + ".timingPolicy")
    declared.update({"synchronizationCertified": False, "timingEditCount": len(edited), "timingEditedIndices": list(edited),
                     "originalTimings": recorded, "timingPolicy": review["timingPolicy"]})
    return declared


def note_problem(note: Any) -> str | None:
    """Why a review note cannot be recorded as bounded plain text, or None."""
    if not isinstance(note, str):
        return "the review note must be text"
    if len(note) > MAX_NOTE_CHARACTERS:
        return f"the review note is limited to {MAX_NOTE_CHARACTERS} characters"
    if "  " in note:
        return "the review note must use single spaces"
    # A note is published as Pandoc plain text, so it is stricter than a cue: one plain space is the only whitespace, and format
    # controls (joiners, word joiner, byte order mark, bidirectional marks), private use and noncharacters are refused. Caption cues keep them.
    if any(c.isspace() and c != " " for c in note):
        return "the review note must use plain spaces only (no tab, no-break space, ideographic space or other whitespace)"
    if any(unicodedata.category(c) in ("Cf", "Co") or 0xE0000 <= ord(c) <= 0xE007F or invisible_scalar(c) for c in note):
        return "the review note must not contain format controls (joiners, word joiner, byte order mark, bidirectional marks), private-use characters or noncharacters"
    problem = cue_text_problem(note)
    return problem.replace("cue text", "the review note") if problem else None


def clock(ms: int, separator: str) -> str:
    return "%02d:%02d:%02d%s%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, separator, ms % 1000)


def plain_text(cues: list[dict]) -> str:
    """One line per cue."""
    return "".join(cue["text"] + "\n" for cue in cues)


def srt_text(cues: list[dict]) -> str:
    return "".join(f"{i + 1}\n{clock(c['startMs'], ',')} --> {clock(c['endMs'], ',')}\n{c['text']}\n\n" for i, c in enumerate(cues))


def vtt_text(cues: list[dict]) -> str:
    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "WEBVTT\n\n" + "".join(f"{clock(c['startMs'], '.')} --> {clock(c['endMs'], '.')}\n{escape(c['text'])}\n\n" for c in cues)


def canonical_json(value: Any) -> bytes:
    """The one byte form of every published JSON document: sorted keys, two-space indent, UTF-8, final newline."""
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def parse(data: bytes, *, expected_sha256: str | None = None, location: str = "$") -> dict:
    """Validate retained bytes, optionally against a pin, and bind the view to those exact bytes."""
    actual = hashlib.sha256(data).hexdigest() if isinstance(data, (bytes, bytearray)) else None
    if expected_sha256 is not None and actual != expected_sha256:
        refuse("TIMED_TEXT_DIGEST_MISMATCH", "document bytes differ from the pinned SHA-256", location,
               "Re-run the producing route or update the pin only after reviewing the changed document.", expected=expected_sha256, actual=actual)
    view = validate(strict_json(data, location), location)
    view["sha256"], view["bytes"] = actual, len(data)
    return view


def rows(view: dict) -> list[list[str]]:
    """Table rows of start, end and text, times as literal integer milliseconds."""
    return [[str(cue["startMs"]), str(cue["endMs"]), cue["text"]] for cue in view["cues"]]
