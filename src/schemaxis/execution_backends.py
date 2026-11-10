"""Trusted execution seam; transport documents never select a backend."""
from dataclasses import dataclass, field
import copy
from pathlib import Path

from .execution_inputs import InputBindings, PlanningRequest, PlanningOutcome


@dataclass(frozen=True)
class ExecutionRequest:
    job_id: str
    plan_id: str
    document: dict
    plan: dict
    document_digest: str
    plan_digest: str
    directory: Path
    workspace: Path
    providers: tuple
    bindings: tuple
    stage_timeout: float
    deadline: float | None
    locations: dict | None = None
    inputs: InputBindings | None = None
    operation_id: str | None = None
    planning_phase: str | None = None


@dataclass(frozen=True)
class VerificationRequest:
    execution: ExecutionRequest
    receipt_digests: tuple = ()


@dataclass(frozen=True)
class ExecutionOutcome:
    response: dict
    isolation: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationOutcome:
    response: dict
    isolation: dict = field(default_factory=dict)
    publications: list | None = None


class LocalExecutor:
    """Existing application dispatch, including its native verification calls."""
    isolated = False

    def plan(self, request, cancellation):
        from . import workflow
        from .adaptors import registry
        planned = (workflow.inspect_plan(request.document)
                   if request.document.get('version') == 'schemaxis.workflow/1'
                   else registry.plan(request.document))
        return PlanningOutcome(planned)

    def run(self, request, cancellation):
        from . import workflow
        from .adaptors import registry
        response = (workflow.execute(request.document, request.directory,
                    locations=request.locations, timeout=request.stage_timeout)
                    if request.document.get('version') == 'schemaxis.workflow/1'
                    else registry.run(request.document, request.directory,
                    locations=request.locations, timeout=request.stage_timeout))
        return ExecutionOutcome(response)

    def verify(self, request, cancellation):
        from . import workflow
        from .adaptors import registry
        execution = request.execution
        response = (workflow.verify(execution.directory)
                    if execution.document.get('version') == 'schemaxis.workflow/1'
                    else registry.verify(execution.directory, execution.document))
        return VerificationOutcome(response)


def collect_publications(job, document, workspace):
    """Run existing publication metadata checks in the execution environment.

    Isolated callers invoke this inside the worker only. The host subsequently
    checks regular-file containment and byte digests without adaptor hooks.
    """
    from .adaptor_runtime import is_common
    from . import workflow
    from .artifacts import file_digest
    from .storage import load
    from .publication_metadata import verify as verify_metadata, MANIFEST
    from .observations import fail
    workspace = Path(workspace)
    root = workspace / job['directory']
    owners = [(root, None)]
    if document.get('version') == 'schemaxis.workflow/1' and not is_common(root):
        outcome = load((root / 'result.json').read_text())
        owners = ([(Path(item['directory']), item['id']) for item in outcome['jobs']]
                  if outcome.get('executionVersion') == 2 else
                  [(root / op['id'], op['id']) for op in workflow.validate(document)])
    resources = []
    for directory, operation in owners:
        if not directory.resolve().is_relative_to(root.resolve()):
            fail('VERIFICATION_FAILED', 'publication owner escaped its job')
        receipt = load((directory / 'verification.json').read_text())
        verify_metadata(directory)
        manifest = load((directory / MANIFEST).read_text())
        companions = {str((directory / item['file']).resolve()): item
                      for item in manifest['publications']}
        for artifact in receipt.get('artifacts', []):
            path = Path(artifact.get('file', '')).resolve()
            if (not path.is_relative_to(root.resolve()) or not path.is_file()
                    or Path(artifact['file']).is_symlink()):
                fail('VERIFICATION_FAILED', 'published artifact escaped its owned job')
            sha = file_digest(path)
            if artifact.get('sha256') is not None and artifact['sha256'] != sha:
                fail('VERIFICATION_FAILED', 'published artifact digest differs')
            companion = companions[str(path)]
            metadata_path = (directory / companion['metadata']).resolve()
            metadata = load(metadata_path.read_text())
            resources.append({'id': 'resource-' + job['id'][4:] + '-' + str(len(resources)),
                'job': job['id'], 'operation': operation, 'documentDigest': job['documentDigest'],
                'file': str(path.relative_to(workspace)), 'name': path.name,
                'kind': artifact.get('kind', artifact.get('identity', {}).get('kind', 'unknown')),
                'sha256': sha, 'bytes': path.stat().st_size,
                'units': metadata.get('spatial', {}).get('units', 'unknown'),
                'metadata': str(metadata_path.relative_to(workspace)),
                'metadataSha256': companion['sha256'],
                'metadataManifest': str((directory / MANIFEST).relative_to(workspace)),
                'metadataManifestSha256': file_digest(directory / MANIFEST),
                'receipt': str((directory / 'verification.json').relative_to(workspace)),
                'receiptSha256': file_digest(directory / 'verification.json')})
    return copy.deepcopy(resources)


def owned_regular(root, path):
    """Check an exported owned regular file without calling any native reader."""
    import stat
    from .observations import fail
    root, path = Path(root), Path(path)
    if not path.is_relative_to(root) or '..' in path.parts:
        fail('VERIFICATION_FAILED', 'exported evidence escaped its job')
    for component in (path, *path.parents):
        if component.is_symlink():
            fail('VERIFICATION_FAILED', 'exported evidence traverses a symlink')
        if component == root:
            break
    details = path.stat()
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        fail('VERIFICATION_FAILED', 'exported evidence is not a regular file')
    return path


def validate_publications(resources, job, workspace):
    """Host-only export checks: no registry, native reader or metadata hook."""
    from .artifacts import file_digest
    from .observations import fail
    workspace = Path(workspace)
    root = workspace / job['directory']
    if not isinstance(resources, list):
        fail('VERIFICATION_FAILED', 'worker omitted its publication inventory')
    checked = []
    for index, resource in enumerate(resources):
        expected_id = 'resource-' + job['id'][4:] + '-' + str(index)
        if (not isinstance(resource, dict) or resource.get('id') != expected_id
                or resource.get('job') != job['id']
                or resource.get('documentDigest') != job['documentDigest']):
            fail('VERIFICATION_FAILED', 'worker publication identity differs')
        for key, sha_key in (('file', 'sha256'), ('receipt', 'receiptSha256'),
                             ('metadata', 'metadataSha256'),
                             ('metadataManifest', 'metadataManifestSha256')):
            relative = resource.get(key)
            if not isinstance(relative, str) or Path(relative).is_absolute():
                fail('VERIFICATION_FAILED', 'worker publication path is invalid')
            path = workspace / relative
            if '..' in Path(relative).parts or not path.is_relative_to(root):
                fail('VERIFICATION_FAILED', 'worker publication escaped its job')
            owned_regular(root, path)
            if file_digest(path) != resource.get(sha_key):
                fail('VERIFICATION_FAILED', 'exported publication or provenance changed')
        path = workspace / resource['file']
        if type(resource.get('bytes')) is not int or path.stat().st_size != resource['bytes']:
            fail('VERIFICATION_FAILED', 'exported publication size differs')
        checked.append(copy.deepcopy(resource))
    return checked
