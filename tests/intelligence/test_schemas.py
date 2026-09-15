from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from docsgpt.intelligence.schemas import Claim, ClaimKind, Evidence


def test_factual_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence_ids"):
        Claim(id="c1", text="Dify released feature X", kind=ClaimKind.FACT, evidence_ids=[])


def test_evidence_serializes_utc_timestamp() -> None:
    evidence = Evidence(
        id="e1",
        record_id="r1",
        repository="langgenius/dify",
        source_type="release",
        title="v1",
        excerpt="notes",
        source_url="https://github.com/x",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert evidence.model_dump(mode="json")["occurred_at"] == "2026-01-01T00:00:00Z"
