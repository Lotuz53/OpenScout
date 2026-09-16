from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import docsgpt.intelligence.indexing as indexing
from docsgpt.intelligence.indexing import (
    IntelligenceIndexer,
    chunks_for_record,
)
from docsgpt.intelligence.schemas import IntelligenceRecord, SourceType
from docsgpt.intelligence.sync_service import SyncService


PROJECT_ID = "project-1"
RETRIEVED_AT = datetime(2026, 9, 16, tzinfo=timezone.utc)


def issue_record(body: str = "short") -> IntelligenceRecord:
    """Build a small issue record for indexing tests."""
    return IntelligenceRecord(
        id="issue:42",
        repository="owner/repo",
        source_type=SourceType.ISSUE,
        external_id="42",
        title="An issue",
        body=body,
        source_url="https://github.com/owner/repo/issues/42",
        created_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        retrieved_at=RETRIEVED_AT,
        content_hash="hash-42",
    )


def test_issue_stays_single_chunk_when_under_limit() -> None:
    chunks = chunks_for_record(issue_record(body="short"))

    assert len(chunks) == 1
    assert chunks[0].metadata["record_id"] == "issue:42"


def test_documentation_chunks_follow_markdown_headings() -> None:
    record = issue_record(body="# Intro\nfirst\n\n## Setup\nsecond").model_copy(
        update={
            "id": "documentation:README.md",
            "external_id": "README.md",
            "source_type": SourceType.DOCUMENTATION,
            "source_url": "https://github.com/owner/repo/blob/main/README.md",
        }
    )

    chunks = chunks_for_record(record)

    assert [chunk.page_content for chunk in chunks] == [
        "# Intro\nfirst",
        "## Setup\nsecond",
    ]


def test_long_issue_is_recursively_split(monkeypatch) -> None:
    class WordCounter:
        def count(self, text: str) -> int:
            return len(text.split())

        def split(self, text: str, max_tokens: int) -> list[str]:
            words = text.split()
            return [
                " ".join(words[start : start + max_tokens])
                for start in range(0, len(words), max_tokens)
            ]

    monkeypatch.setattr(indexing, "_token_counter", lambda: WordCounter())
    monkeypatch.setattr(indexing, "_max_chunk_tokens", lambda: 3)

    chunks = indexing.chunks_for_record(
        issue_record(body="one two three four five six")
    )

    assert [chunk.page_content for chunk in chunks] == [
        "one two three",
        "four five six",
    ]


def test_changed_record_replaces_only_its_chunks() -> None:
    repository = MagicMock()
    vector_store = MagicMock()
    vector_store.delete_chunks_by_source_path.return_value = 1
    vector_store.add_texts.return_value = ["chunk-1"]
    indexer = IntelligenceIndexer(repository, vector_store)

    summary = indexer.replace_records(PROJECT_ID, [issue_record()])

    vector_store.delete_chunks_by_source_path.assert_called_once_with(
        "openscout://project-1/issue:42"
    )
    vector_store.add_texts.assert_called_once()
    vector_store.delete_index.assert_not_called()
    assert summary.embedded_chunks == 1
    assert summary.chunk_ids == ["chunk-1"]
    metadata = vector_store.add_texts.call_args.args[1][0]
    assert metadata == {
        "record_id": "issue:42",
        "project_id": PROJECT_ID,
        "repository": "owner/repo",
        "source_type": "issue",
        "occurred_at": "2026-01-10T00:00:00+00:00",
        "version": None,
        "source": "openscout://project-1/issue:42",
    }


def test_unchanged_sync_adds_no_embeddings() -> None:
    repository = MagicMock()
    vector_store = MagicMock()
    vector_store.add_texts.return_value = ["chunk-1"]
    indexer = IntelligenceIndexer(repository, vector_store)

    assert indexer.replace_records(PROJECT_ID, [issue_record()]).embedded_chunks == 1
    assert indexer.replace_records(PROJECT_ID, []).embedded_chunks == 0
    assert vector_store.add_texts.call_count == 1


def test_sync_passes_persisted_record_id_to_indexer() -> None:
    repository = MagicMock(spec=["upsert_records"])
    repository.upsert_records.return_value = [
        SimpleNamespace(changed=True, record_id="db-record-1")
    ]
    indexer = MagicMock()

    SyncService(repository, MagicMock(), indexer)._persist_batch(
        PROJECT_ID,
        [issue_record()],
    )

    indexed_record = indexer.replace_records.call_args.args[1][0]
    assert indexed_record.id == "db-record-1"
