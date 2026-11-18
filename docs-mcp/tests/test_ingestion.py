import pytest
from pathlib import Path

from apps.ingestion.service import IngestionService
from core.models import IngestRequest


class DummyStore:
    def __init__(self):
        self.upserted = []
        self.deleted = []

    def upsert(self, chunks, vectors):
        self.upserted.extend(chunks)

    def delete(self, chunk_ids):
        self.deleted.extend(chunk_ids)


@pytest.mark.parametrize('name', ['../escape', '..', 'nested/repo', r'nested\repo', 'C:repo'])
def test_remote_repo_name_cannot_escape_clone_directory(tmp_path, name):
    service = IngestionService.__new__(IngestionService)
    service.data_dir = tmp_path
    with pytest.raises(ValueError, match='single directory name'):
        service._resolve_source(IngestRequest(git_url='https://example.org/repo.git', repo_name=name))


def test_file_walker_ignores_only_repo_local_exclusions(tmp_path):
    root = tmp_path / 'build' / 'project'
    root.mkdir(parents=True)
    (root / 'app.py').write_text('print(1)', encoding='utf-8')
    excluded = root / 'node_modules'
    excluded.mkdir()
    (excluded / 'external.js').write_text('external()', encoding='utf-8')
    service = IngestionService.__new__(IngestionService)
    assert list(service._iter_files(root)) == [root / 'app.py']


def test_local_ingestion_requires_directory(tmp_path):
    source = tmp_path / 'app.py'
    source.write_text('print(1)', encoding='utf-8')
    service = IngestionService.__new__(IngestionService)
    with pytest.raises(ValueError, match='not a directory'):
        service._resolve_source(IngestRequest(path=str(source)))


@pytest.mark.asyncio
async def test_ingestion_is_incremental_and_tracks_progress(tmp_path: Path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'README.md').write_text('# Architecture\n' + ('docs ' * 700))
    service = IngestionService()
    service.data_dir = tmp_path / 'data'
    service.data_dir.mkdir()
    service.manifest = service.data_dir / 'index_manifest.json'
    service.progress_index = service.data_dir / 'ingestion_progress.json'
    service.store = DummyStore()
    service.embedder._failed = True
    first = await service.ingest(IngestRequest(path=str(repo), repo_name='repo', force=True, job_id='job-1'))
    second = await service.ingest(IngestRequest(path=str(repo), repo_name='repo', force=False, job_id='job-2'))
    progress = service.get_progress('job-1')
    assert first.indexed_chunks > 0
    assert second.skipped_files == 1
    assert progress is not None
    assert progress.status == 'completed'
