"""Chunk and incrementally index normalized OpenScout evidence."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from docsgpt.core.settings import settings
from docsgpt.intelligence.schemas import IntelligenceRecord, SourceType
from docsgpt.parser.tokenization import get_token_counter
from docsgpt.vectorstore.document_class import Document
from docsgpt.vectorstore.model_registry import max_input_tokens_for


DEFAULT_MAX_CHUNK_TOKENS = 384
APPROXIMATE_TOKEN_CHARS = 4
MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S")
RECURSIVE_SEPARATORS = ("\n\n", "\n", " ")
_counter_unavailable = False


@dataclass(frozen=True)
class IndexSummary:
    """Describe the chunks replaced during one indexing operation."""

    embedded_chunks: int = 0
    deleted_chunks: int = 0
    chunk_ids: list[str] = field(default_factory=list)


def chunks_for_record(record: IntelligenceRecord) -> list[Document]:
    """Split one record and attach metadata that identifies its source.

    Documentation is divided at Markdown headings before oversized sections
    are recursively split. Issues, comments, and releases remain one chunk
    until their embedding model's input limit is reached.

    Args:
        record: Normalized evidence record to chunk.

    Returns:
        Documents containing the record text and traceability metadata.
    """
    counter = _token_counter()
    max_tokens = _max_chunk_tokens()
    text = record.body or record.title
    sections = _markdown_sections(text) if record.source_type == SourceType.DOCUMENTATION else [text]

    chunks: list[Document] = []
    for section in sections:
        for piece in _recursive_split(section, counter, max_tokens):
            content = piece.strip()
            if content:
                chunks.append(
                    Document(
                        page_content=content,
                        metadata=_record_metadata(record, project_id=None, source=None),
                    )
                )
    return chunks


class IntelligenceIndexer:
    """Replace only the vector chunks belonging to changed records."""

    def __init__(self, repository: Any, vector_store: Any) -> None:
        """Initialize an indexer with a repository and vector store.

        Args:
            repository: Repository retained for future chunk-reference
                persistence and GraphRAG integration.
            vector_store: Source-scoped DocsGPT vector store.
        """
        self.repository = repository
        self.vector_store = vector_store
        self._chunk_ids_by_source: dict[str, list[str]] = {}

    @property
    def chunk_ids(self) -> dict[str, list[str]]:
        """Return the latest vector chunk ids keyed by stable source URI."""
        return {source: list(ids) for source, ids in self._chunk_ids_by_source.items()}

    def replace_records(
        self,
        project_id: str,
        records: Sequence[IntelligenceRecord],
    ) -> IndexSummary:
        """Replace chunks for changed records without rebuilding the index.

        Args:
            project_id: Intelligence project owning the records.
            records: Records whose content hash changed or that are new.

        Returns:
            Counts of deleted and embedded chunks and their returned ids.
        """
        deleted_chunks = 0
        embedded_chunks = 0
        chunk_ids: list[str] = []

        for record in records:
            record_id = _record_id(record)
            source = _stable_source(project_id, record_id)
            deleted_chunks += self._delete_existing(source)

            chunks = self._project_chunks(record, project_id, source)
            if not chunks:
                self._chunk_ids_by_source[source] = []
                continue

            texts = [chunk.page_content for chunk in chunks]
            metadatas = [chunk.metadata for chunk in chunks]
            returned_ids = self.vector_store.add_texts(texts, metadatas)
            ids = _normalize_ids(returned_ids)
            embedded_chunks += len(ids) if returned_ids is not None else len(texts)
            chunk_ids.extend(ids)
            self._chunk_ids_by_source[source] = ids

        return IndexSummary(
            embedded_chunks=embedded_chunks,
            deleted_chunks=deleted_chunks,
            chunk_ids=chunk_ids,
        )

    def delete_records(
        self,
        project_id: str,
        record_ids: Sequence[str],
    ) -> IndexSummary:
        """Delete vector chunks for records confirmed inactive.

        Args:
            project_id: Intelligence project owning the records.
            record_ids: Persisted record ids whose active state changed.

        Returns:
            The number of removed chunks. No embeddings are generated.
        """
        deleted_chunks = 0
        for record_id in record_ids:
            source = _stable_source(project_id, str(record_id))
            deleted_chunks += self._delete_existing(source)
            self._chunk_ids_by_source.pop(source, None)
        return IndexSummary(deleted_chunks=deleted_chunks)

    def _project_chunks(
        self,
        record: IntelligenceRecord,
        project_id: str,
        source: str,
    ) -> list[Document]:
        """Add project-scoped metadata to record chunks."""
        return [
            Document(
                page_content=chunk.page_content,
                metadata=_record_metadata(
                    record,
                    project_id=project_id,
                    source=source,
                ),
            )
            for chunk in chunks_for_record(record)
        ]

    def _delete_existing(self, source: str) -> int:
        """Delete old chunks for one stable source URI."""
        remover = getattr(self.vector_store, "delete_chunks_by_source_path", None)
        if callable(remover):
            result = remover(source)
            if isinstance(result, bool):
                return int(result)
            try:
                return int(result or 0)
            except (TypeError, ValueError):
                return 0

        getter = getattr(self.vector_store, "get_chunks", None)
        deleter = getattr(self.vector_store, "delete_chunk", None)
        if not callable(getter) or not callable(deleter):
            return 0

        deleted = 0
        for chunk in getter() or []:
            metadata = chunk.get("metadata") or {}
            if metadata.get("source") != source:
                continue
            if deleter(chunk.get("doc_id")):
                deleted += 1
        return deleted


def _max_chunk_tokens() -> int:
    """Return the configured or registered embedding input limit."""
    configured = getattr(settings, "EMBEDDINGS_MAX_INPUT_TOKENS", None)
    if configured and configured > 0:
        return int(configured)
    registered = max_input_tokens_for(getattr(settings, "EMBEDDINGS_NAME", None))
    return registered or DEFAULT_MAX_CHUNK_TOKENS


def _token_counter() -> Any:
    """Return the embedding tokenizer, with an offline-safe fallback."""
    global _counter_unavailable
    if _counter_unavailable:
        return _ApproximateTokenCounter()
    try:
        return get_token_counter(settings.EMBEDDINGS_NAME)
    except Exception:  # noqa: BLE001 -- indexing must work without downloads
        _counter_unavailable = True
        return _ApproximateTokenCounter()


class _ApproximateTokenCounter:
    """Conservative character-based token counter for offline environments."""

    def count(self, text: str) -> int:
        """Estimate token count without loading a model or tokenizer."""
        if not text:
            return 0
        return max(1, (len(text) + APPROXIMATE_TOKEN_CHARS - 1) // APPROXIMATE_TOKEN_CHARS)

    def split(self, text: str, max_tokens: int) -> list[str]:
        """Split text into pieces that fit the approximate token budget."""
        width = max(1, max_tokens) * APPROXIMATE_TOKEN_CHARS
        return [text[start : start + width] for start in range(0, len(text), width)]


def _record_id(record: IntelligenceRecord) -> str:
    """Return a stable record id, including for pre-persistence records."""
    if record.id:
        return str(record.id)
    return f"{record.source_type.value}:{record.external_id}"


def _stable_source(project_id: str, record_id: str) -> str:
    """Build the metadata source used for targeted replacement."""
    return f"openscout://{project_id}/{record_id}"


def _record_metadata(
    record: IntelligenceRecord,
    *,
    project_id: str | None,
    source: str | None,
) -> dict[str, Any]:
    """Build JSON-compatible traceability metadata for one chunk."""
    occurred_at = record.published_at or record.created_at or record.updated_at
    return {
        "record_id": _record_id(record),
        "project_id": project_id,
        "repository": record.repository,
        "source_type": record.source_type.value,
        "occurred_at": occurred_at.isoformat() if occurred_at else None,
        "version": record.version,
        "source": source or str(record.source_url),
    }


def _markdown_sections(text: str) -> list[str]:
    """Split Markdown into sections beginning at heading boundaries."""
    lines = text.splitlines()
    sections: list[str] = []
    current: list[str] = []

    for line in lines:
        if MARKDOWN_HEADING.match(line) and any(item.strip() for item in current):
            section = "\n".join(current).strip()
            if section:
                sections.append(section)
            current = []
        current.append(line)

    section = "\n".join(current).strip()
    if section:
        sections.append(section)
    return sections or [text]


def _recursive_split(text: str, counter: Any, max_tokens: int, start: int = 0) -> list[str]:
    """Recursively split oversized text on progressively smaller boundaries."""
    if not text or counter.count(text) <= max_tokens:
        return [text] if text else []

    for offset, separator in enumerate(RECURSIVE_SEPARATORS, start=start):
        if separator not in text:
            continue
        parts = _parts_with_separator(text, separator)
        packed = _pack_parts(parts, counter, max_tokens)
        result: list[str] = []
        for piece in packed:
            if counter.count(piece) <= max_tokens:
                result.append(piece)
            else:
                result.extend(_recursive_split(piece, counter, max_tokens, offset + 1))
        if result and all(counter.count(piece) <= max_tokens for piece in result):
            return result

    return counter.split(text, max_tokens)


def _parts_with_separator(text: str, separator: str) -> list[str]:
    """Keep separators attached to the preceding part while splitting."""
    raw_parts = text.split(separator)
    return [
        part + (separator if index < len(raw_parts) - 1 else "")
        for index, part in enumerate(raw_parts)
        if part
    ]


def _pack_parts(parts: list[str], counter: Any, max_tokens: int) -> list[str]:
    """Pack separator-preserving parts without exceeding the token budget."""
    packed: list[str] = []
    current = ""
    for part in parts:
        candidate = current + part
        if current and counter.count(candidate) > max_tokens:
            packed.append(current)
            current = part
        else:
            current = candidate
    if current:
        packed.append(current)
    return packed


def _normalize_ids(returned_ids: Any) -> list[str]:
    """Normalize vector-store ids to strings for downstream filtering."""
    if returned_ids is None:
        return []
    if isinstance(returned_ids, (str, int)):
        return [str(returned_ids)]
    return [str(chunk_id) for chunk_id in returned_ids]


__all__ = ["IndexSummary", "IntelligenceIndexer", "chunks_for_record"]
