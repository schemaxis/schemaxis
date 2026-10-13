"""Strict JSON and durable atomic publication shared by workspace owners."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from .errors import fail


def encoded(value):
    try:
        return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()
    except (ValueError, TypeError):
        fail('INVALID_DOCUMENT', 'values must be finite JSON data')


def load(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: fail('INVALID_DOCUMENT', 'duplicate JSON key', key)
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=pairs)
        encoded(value)
        return value
    except (ValueError, TypeError) as error:
        fail('INVALID_DOCUMENT', str(error))


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def prepare_run_directory(directory, document):
    """Claim a new or empty run directory without replacing retained evidence.

    Exclusive publication of authored.json arbitrates concurrent fresh starts;
    the retained input also reserves the directory if execution later fails.
    """
    directory = Path(directory).expanduser().absolute()
    payload = encoded(document)
    try:
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            fail('OUTPUT_EXISTS', 'output must be a new or empty directory, not a file or symlink', str(directory))
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            fail('OUTPUT_EXISTS', 'output directory contains files; choose a new or empty directory, '
                 'or use --resume for an unchanged workflow', str(directory))
        atomic(directory / 'authored.json', payload, exclusive=True)
    except OSError as error:
        fail('INVALID_OUTPUT_PATH', 'cannot prepare output directory: ' + str(error), str(directory))
    return directory


class AtomicPublicationError(OSError):
    """Bytes were published, but durability/cleanup failed. Do not assume rollback.

    State owners must reconcile the visible file or stop accepting writes.
    ``published`` does not guarantee survival of a machine/filesystem crash.
    """
    published = True
    durable = False

    def __init__(self, path, cause):
        self.path = Path(path)
        super().__init__(f'Published {path}, but completion is uncertain: {cause}')


def atomic(path, payload, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    published = False
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            try: os.link(temporary, path)
            except FileExistsError: fail('OUTPUT_EXISTS', 'choose a new destination', str(path))
        else:
            os.replace(temporary, path)
        published = True
        fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    except OSError as error:
        if published: raise AtomicPublicationError(path, error) from error
        raise
    finally:
        try:
            if os.path.exists(temporary): os.unlink(temporary)
        except OSError as error:
            if published: raise AtomicPublicationError(path, error) from error
            raise
