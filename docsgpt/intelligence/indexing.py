"""Chunk and incrementally index normalized OpenScout evidence."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from docsgpt.core.settings import settings
from docsgpt.intelligence.schemas import IntelligenceRecord, SourceType
from docsgpt.parser.tokenization import get_token_counter
from docsgpt.vectorstore.document_class import Document
from docsgpt.vectorstore.model_registry import max_input_tokens_for


DEFAULT_MAX_CHUNK_TOKENS = 384
APPROXIMATE_TOKEN_CHARS = 4
MIN_TOKENIZER_INPUT_CHARS = 2048
DEFAULT_INDEX_BATCH_SIZE = 32
MAX_INDEX_BATCH_SIZE = 512
MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S")
RECURSIVE_SEPARATORS = ("\n\n", "\n", " ")
_counter_unavailable = False
logger = logging.getLogger(__name__)


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
    return list(iter_chunks_for_record(record))


def iter_chunks_for_record(record: IntelligenceRecord) -> Iterator[Document]:
    """Yield one record's chunks without materializing the complete record.

    Documentation sections are still discovered as a list because their
    headings are needed for deterministic section boundaries. Recursive
    splitting of each section is lazy so one large issue, comment, or release
    cannot consume memory before the configured embedding batch is flushed.

    Args:
        record: Normalized evidence record to chunk.

    Yields:
        Documents containing the record text and traceability metadata.
    """
    counter = _token_counter()
    max_tokens = _max_chunk_tokens()
    text = record.body or record.title
    sections = _markdown_sections(text) if record.source_type == SourceType.DOCUMENTATION else (text,)

    for section in sections:
        for piece in _iter_recursive_split(section, counter, max_tokens):
            content = piece.strip()
            if content:
                yield Document(
                    page_content=content,
                    metadata=_record_metadata(record, project_id=None, source=None),
                )


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
        pending: list[tuple[str, dict[str, Any], str, str]] = []
        batch_number = 0
        processed_chunks = 0
        batch_size = _index_batch_size()

        def flush_batch() -> None:
            """Embed and persist at most one configured batch of chunks."""
            nonlocal batch_number, embedded_chunks, pending, processed_chunks
            if not pending:
                return

            batch = pending
            pending = []
            texts = [item[0] for item in batch]
            metadatas = [item[1] for item in batch]
            affected_ids = list(dict.fromkeys(item[3] for item in batch))
            batch_number += 1
            try:
                returned_ids = self.vector_store.add_texts(texts, metadatas)
            except Exception as exc:  # noqa: BLE001 -- attach stable source ids
                raise RuntimeError(
                    "Failed to index records "
                    f"[{', '.join(affected_ids)}]: {exc}"
                ) from exc

            ids = _normalize_ids(returned_ids)
            if returned_ids is not None and len(ids) != len(texts):
                raise RuntimeError(
                    "Vector store returned "
                    f"{len(ids)} ids for {len(texts)} chunks in records "
                    f"[{', '.join(affected_ids)}]"
                )

            embedded_chunks += len(ids) if returned_ids is not None else len(texts)
            for chunk_id, item in zip(ids, batch):
                self._chunk_ids_by_source[item[2]].append(chunk_id)
            chunk_ids.extend(ids)
            processed_chunks += len(texts)
            logger.info(
                "Intelligence indexing batch project=%s batch=%d chunks=%d processed=%d",
                project_id,
                batch_number,
                len(texts),
                processed_chunks,
            )

        for record in records:
            record_id = _record_id(record)
            source = _stable_source(project_id, record_id)
            deleted_chunks += self._delete_existing(source)

            self._chunk_ids_by_source[source] = []
            for chunk in self._iter_project_chunks(record, project_id, source):
                pending.append(
                    (
                        chunk.page_content,
                        chunk.metadata,
                        source,
                        record_id,
                    )
                )
                if len(pending) >= batch_size:
                    flush_batch()

        flush_batch()

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

    def _iter_project_chunks(
        self,
        record: IntelligenceRecord,
        project_id: str,
        source: str,
    ) -> Iterator[Document]:
        """Yield record chunks with project-scoped metadata."""
        for chunk in iter_chunks_for_record(record):
            yield Document(
                page_content=chunk.page_content,
                metadata=_record_metadata(
                    record,
                    project_id=project_id,
                    source=source,
                ),
            )

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
    """Return a safe token budget for one intelligence index chunk.

    A model context window is not a safe embedding chunk size. Local ONNX
    embedding memory grows with the longest input, so intelligence indexing
    keeps the historical 384-token default while honoring a lower configured
    limit or a model with a smaller context window.
    """
    configured = getattr(settings, "EMBEDDINGS_MAX_INPUT_TOKENS", None)
    if configured and configured > 0:
        return min(int(configured), DEFAULT_MAX_CHUNK_TOKENS)
    registered = max_input_tokens_for(getattr(settings, "EMBEDDINGS_NAME", None))
    return min(registered or DEFAULT_MAX_CHUNK_TOKENS, DEFAULT_MAX_CHUNK_TOKENS)


def _index_batch_size() -> int:
    """Return the bounded number of chunks sent to one vector-store call."""
    configured = getattr(settings, "INTELLIGENCE_INDEX_BATCH_SIZE", DEFAULT_INDEX_BATCH_SIZE)
    if isinstance(configured, bool):
        return DEFAULT_INDEX_BATCH_SIZE
    try:
        configured = int(configured)
    except (TypeError, ValueError):
        return DEFAULT_INDEX_BATCH_SIZE
    return min(max(configured, 1), MAX_INDEX_BATCH_SIZE)


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
    return list(_iter_recursive_split(text, counter, max_tokens, start))


def _iter_recursive_split(
    text: str,
    counter: Any,
    max_tokens: int,
    start: int = 0,
) -> Iterator[str]:
    """Yield recursively split text without retaining all pieces."""
    if not text:
        return

    max_chars_before_count = max(
        MIN_TOKENIZER_INPUT_CHARS,
        max(1, max_tokens) * APPROXIMATE_TOKEN_CHARS,
    )
    if len(text) <= max_chars_before_count and counter.count(text) <= max_tokens:
        yield text
        return

    if len(text) > max_chars_before_count:
        for offset in range(start, len(RECURSIVE_SEPARATORS)):
            separator = RECURSIVE_SEPARATORS[offset]
            if separator not in text:
                continue
            for part in _iter_parts_with_separator(text, separator):
                yield from _iter_recursive_split(part, counter, max_tokens, offset + 1)
            return

        for offset in range(0, len(text), max_chars_before_count):
            piece = text[offset : offset + max_chars_before_count]
            yield from _iter_recursive_split(
                piece,
                counter,
                max_tokens,
                len(RECURSIVE_SEPARATORS),
            )
        return

    for offset in range(start, len(RECURSIVE_SEPARATORS)):
        separator = RECURSIVE_SEPARATORS[offset]
        if separator not in text:
            continue
        has_parts = False
        for piece in _iter_pack_parts(_iter_parts_with_separator(text, separator), counter, max_tokens):
            has_parts = True
            if counter.count(piece) <= max_tokens:
                yield piece
            else:
                yield from _iter_recursive_split(piece, counter, max_tokens, offset + 1)
        if has_parts:
            return

    yield from _iter_counter_split(text, counter, max_tokens)


def _parts_with_separator(text: str, separator: str) -> list[str]:
    """Keep separators attached to the preceding part while splitting."""
    raw_parts = text.split(separator)
    return [
        part + (separator if index < len(raw_parts) - 1 else "")
        for index, part in enumerate(raw_parts)
        if part
    ]


def _iter_parts_with_separator(text: str, separator: str) -> Iterator[str]:
    """Yield separator-preserving parts without copying the full split list."""
    start = 0
    separator_length = len(separator)
    while True:
        end = text.find(separator, start)
        if end < 0:
            part = text[start:]
            if part:
                yield part
            return
        part = text[start:end]
        if part:
            yield part + separator
        start = end + separator_length


def _pack_parts(parts: list[str], counter: Any, max_tokens: int) -> list[str]:
    """Pack separator-preserving parts without exceeding the token budget."""
    return list(_iter_pack_parts(parts, counter, max_tokens))


def _iter_pack_parts(
    parts: Iterator[str],
    counter: Any,
    max_tokens: int,
) -> Iterator[str]:
    """Yield packed parts as soon as the next part exceeds the budget."""
    current = ""
    for part in parts:
        candidate = current + part
        if current and counter.count(candidate) > max_tokens:
            yield current
            current = part
        else:
            current = candidate
    if current:
        yield current


def _iter_counter_split(text: str, counter: Any, max_tokens: int) -> Iterator[str]:
    """Yield tokenizer fallback pieces, using bounded slicing when possible."""
    if isinstance(counter, _ApproximateTokenCounter):
        width = max(1, max_tokens) * APPROXIMATE_TOKEN_CHARS
        for start in range(0, len(text), width):
            yield text[start : start + width]
        return
    yield from counter.split(text, max_tokens)


def _normalize_ids(returned_ids: Any) -> list[str]:
    """Normalize vector-store ids to strings for downstream filtering."""
    if returned_ids is None:
        return []
    if isinstance(returned_ids, (str, int)):
        return [str(returned_ids)]
    return [str(chunk_id) for chunk_id in returned_ids]


__all__ = [
    "IndexSummary",
    "IntelligenceIndexer",
    "chunks_for_record",
    "iter_chunks_for_record",
]
