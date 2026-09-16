"""Tests for production OpenScout query dependency wiring."""

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from docsgpt.intelligence.runtime import (
    IntelligenceHybridRetriever,
    LLMInsightGenerator,
    build_production_query_service,
)
from docsgpt.intelligence.schemas import Evidence, QueryFilters, SourceType
from docsgpt.vectorstore.document_class import Document


PROJECT_ID = "00000000-0000-0000-0000-000000000001"
RECORD_ID = "00000000-0000-0000-0000-000000000002"


def _evidence() -> Evidence:
    """Return one persisted evidence-shaped record."""
    return Evidence(
        id=RECORD_ID,
        record_id=RECORD_ID,
        repository="langgenius/dify",
        source_type=SourceType.RELEASE,
        title="Dify 1.0",
        excerpt="Added SSO support.",
        source_url="https://github.com/langgenius/dify/releases/tag/v1.0",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class FakeRepository:
    """Capture the owner and metadata scope used by the runtime adapter."""

    def __init__(self) -> None:
        self.project_calls: list[str] = []
        self.record_calls: list[tuple[str, list[str], QueryFilters, list[str]]] = []

    def list_projects(self, user_id: str) -> list[dict[str, Any]]:
        """Return two projects so repository filtering is observable."""
        self.project_calls.append(user_id)
        return [
            {"id": PROJECT_ID, "repository": "langgenius/dify"},
            {
                "id": "00000000-0000-0000-0000-000000000003",
                "repository": "other/project",
            },
        ]

    def get_records_for_retrieval(
        self,
        user_id: str,
        project_ids: list[str],
        filters: QueryFilters,
        record_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Return only the owner-scoped record requested by the vector hit."""
        self.record_calls.append((user_id, project_ids, filters, record_ids))
        return [
            {
                "id": RECORD_ID,
                "repository": "langgenius/dify",
                "source_type": "release",
                "title": "Dify 1.0",
                "body": "Added SSO support.",
                "source_url": "https://github.com/langgenius/dify/releases/tag/v1.0",
                "occurred_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            }
        ]


class FakeStore:
    """Return a vector and keyword hit for one project."""

    def __init__(self) -> None:
        self.filters: list[dict[str, Any] | None] = []
        self.vector_k: int | None = None
        self.keyword_k: int | None = None
        self.closed = False

    def search(self, question: str, k: int, **kwargs: Any) -> list[Document]:
        """Return the vector hit and retain the compiled metadata filter."""
        del question
        self.vector_k = k
        self.filters.append(kwargs.get("metadata_filter"))
        return [
            Document(
                "Added SSO support.",
                {"record_id": RECORD_ID, "project_id": PROJECT_ID},
            )
        ]

    def keyword_search(self, question: str, k: int) -> list[Document]:
        """Return the matching keyword hit."""
        del question
        self.keyword_k = k
        return [
            Document(
                "Added SSO support.",
                {"record_id": RECORD_ID, "project_id": PROJECT_ID},
            )
        ]

    def close(self) -> None:
        """Record that the request-scoped store was released."""
        self.closed = True


def test_hybrid_runtime_retrieves_owner_scoped_evidence() -> None:
    """The default adapter must use the selected owner's project indexes."""
    repository = FakeRepository()
    store = FakeStore()

    @contextmanager
    def repository_factory():
        """Yield the fake repository through the production context boundary."""
        yield repository

    retriever = IntelligenceHybridRetriever(
        repository_factory=repository_factory,
        vectorstore_factory=lambda project_id: store,
    )
    retriever.set_user_id("owner")

    evidence = retriever.retrieve_filtered(
        "Which product added SSO?",
        QueryFilters(repositories=["langgenius/dify"], source_types=[SourceType.RELEASE]),
        metadata_filter={"$and": [{"repository": {"$in": ["langgenius/dify"]}}]},
    )

    assert evidence == [_evidence()]
    assert repository.project_calls == ["owner"]
    assert repository.record_calls[0][0] == "owner"
    assert repository.record_calls[0][1] == [PROJECT_ID]
    assert repository.record_calls[0][3] == [RECORD_ID]
    assert store.vector_k == 20
    assert store.keyword_k == 20
    assert store.closed is True


def test_hybrid_runtime_uses_keyword_hits_when_dense_search_fails() -> None:
    """A vector backend failure must not disable the sparse fallback."""

    class DenseFailureStore(FakeStore):
        """Fail only the dense search while retaining keyword search."""

        def search(self, question: str, k: int, **kwargs: Any) -> list[Document]:
            """Raise the backend error the adapter is expected to contain."""
            del question, k, kwargs
            raise RuntimeError("dense backend unavailable")

    repository = FakeRepository()
    store = DenseFailureStore()

    @contextmanager
    def repository_factory():
        """Yield the fake repository through the production context boundary."""
        yield repository

    retriever = IntelligenceHybridRetriever(
        repository_factory=repository_factory,
        vectorstore_factory=lambda project_id: store,
    )
    retriever.set_user_id("owner")

    evidence = retriever.retrieve(
        "Which product added SSO?",
        QueryFilters(repositories=["langgenius/dify"], source_types=[SourceType.RELEASE]),
    )

    assert evidence == [_evidence()]
    assert store.keyword_k == 20


def test_llm_generator_returns_structured_claims() -> None:
    """The configured LLM boundary must preserve evidence ids from JSON output."""
    class FakeLLM:
        """Return the narrow JSON generation contract."""

        model_id = "test-model"

        def gen(self, **kwargs: Any) -> str:
            """Return one evidence-backed factual claim."""
            del kwargs
            return (
                '{"answer":"Dify added SSO.","claims":['
                '{"id":"claim-1","text":"Dify added SSO.",'
                '"kind":"fact","evidence_ids":["' + RECORD_ID + '"]}]}'
            )

    generator = LLMInsightGenerator(llm_factory=lambda _user_id: FakeLLM())
    generator.set_user_id("owner")

    result = generator.generate("Which product added SSO?", [_evidence()])

    assert result["answer"] == "Dify added SSO."
    assert result["claims"][0]["evidence_ids"] == [RECORD_ID]


def test_production_query_service_has_real_runtime_dependencies() -> None:
    """The route factory must not construct the empty query placeholders."""
    service = build_production_query_service()

    assert isinstance(service.retriever, IntelligenceHybridRetriever)
    assert isinstance(service.generator, LLMInsightGenerator)
    assert service.router is not None
    assert service.analytics is not None
