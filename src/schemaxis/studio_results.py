"""Present local run directories through the standalone artifact viewer library."""
from pathlib import Path

from schemaxis_viewer.library import LocalLibrary


class StudioResults:
    def __init__(self, app):
        self.app = app
        self.library = LocalLibrary(app.session.workspace/'viewer-recent.json')
        self.warnings = []

    def refresh(self):
        app = self.app
        sources = []
        # Listing previous results must remain responsive during native work.
        if app.lock.acquire(blocking=False):
            try:
                for document in app.session._state['documents'].values():
                    for checkpoint in document.get('checkpoints', [])[-20:]:
                        if checkpoint.get('native'):
                            sources.append(('preview-'+checkpoint['id'], checkpoint['directory'],
                                            f'{document["name"]} · revision {checkpoint["revision"]}',
                                            checkpoint.get('artifacts', [])))
            finally:
                app.lock.release()
        with app.job_lock:
            for identity, job in list(app.jobs.items())[-40:]:
                result = job.get('result', {})
                if not isinstance(result, dict) or result.get('native') is False:
                    continue
                directory = result.get('directory') or result.get('preview')
                label = next((source[2] for source in sources if source[1] == directory), job.get('label') or (Path(directory).name if directory else 'Run'))
                if job.get('status') == 'succeeded' and directory:
                    sources.append(('job-'+identity, directory, label,
                                    result.get('outputs', result.get('artifacts', []))))
        for key, directory, label, artifacts in sources:
            if key in self.library.collections:
                continue
            try:
                root = Path(directory).resolve(strict=True)
                expected = {}
                for artifact in artifacts:
                    filename = artifact.get('path') or artifact.get('file')
                    if filename and artifact.get('sha256'):
                        path = Path(filename)
                        path = path if path.is_absolute() else root/path
                        path = path.resolve()
                        if not path.is_relative_to(root):
                            raise ValueError('Publication escaped its run directory')
                        expected[str(path)] = artifact['sha256']
                self.library.register([root], kind='run', label=label, key=key, expected=expected)
            except (OSError, ValueError) as error:
                self.warnings.append(f'{label}: {error}')
        return self.library
