"""Public read-only projection for shared OpenScout reports."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, jsonify

from docsgpt.storage.db.repositories.intelligence import IntelligenceRepository
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

public_intelligence = Blueprint(
    "public_intelligence",
    __name__,
    url_prefix="/api/public/intelligence",
)


def _items(value: Any) -> list[Any]:
    """Return JSON array items without trusting the stored value's shape."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return list(value)


def _string_list(value: Any) -> list[str]:
    """Keep only non-empty strings from an untrusted JSON array."""
    return [item for item in _items(value) if isinstance(item, str) and item.strip()]


def _section_projection(value: Any) -> dict[str, Any] | None:
    """Project one report section without copying unknown fields."""
    if not isinstance(value, Mapping):
        return None
    return {
        "heading": value.get("heading") if isinstance(value.get("heading"), str) else "",
        "paragraphs": _string_list(value.get("paragraphs")),
        "bullets": _string_list(value.get("bullets")),
    }


def _source_projection(value: Any) -> dict[str, str] | None:
    """Project a source to its public title and URL only."""
    if not isinstance(value, Mapping):
        return None
    title = value.get("title")
    url = value.get("url")
    if not isinstance(title, str) or not isinstance(url, str) or not url.strip():
        return None
    normalized_url = url.strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return {"title": title, "url": normalized_url}


def _coverage_projection(value: Any) -> dict[str, Any]:
    """Project the report coverage fields useful to a public reader."""
    if not isinstance(value, Mapping):
        return {
            "repositories": [],
            "date_from": None,
            "date_to": None,
            "counts": {},
            "capped": False,
        }
    counts = value.get("counts")
    safe_counts = (
        {
            key: item
            for key, item in counts.items()
            if isinstance(key, str) and isinstance(item, (int, float)) and not isinstance(item, bool)
        }
        if isinstance(counts, Mapping)
        else {}
    )
    return {
        "repositories": _string_list(value.get("repositories")),
        "date_from": value.get("date_from") if isinstance(value.get("date_from"), str) else None,
        "date_to": value.get("date_to") if isinstance(value.get("date_to"), str) else None,
        "counts": safe_counts,
        "capped": value.get("capped") is True,
    }


def project_public_report(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build the allow-listed public representation of a saved report."""
    report_data = row.get("report_data")
    if not isinstance(report_data, Mapping):
        report_data = {}

    sections = [
        section
        for raw_section in _items(report_data.get("sections"))
        if (section := _section_projection(raw_section)) is not None
    ]
    sources = [
        source
        for raw_source in _items(report_data.get("sources"))
        if (source := _source_projection(raw_source)) is not None
    ]
    created_at = row.get("created_at")
    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    if not isinstance(created_at, str):
        created_at = report_data.get("created_at")
    if not isinstance(created_at, str):
        created_at = None

    return {
        "title": report_data.get("title") if isinstance(report_data.get("title"), str) else "OpenScout report",
        "sections": sections,
        "sources": sources,
        "coverage": _coverage_projection(report_data.get("coverage")),
        "created_at": created_at,
    }


@public_intelligence.get("/reports/<string:token>")
def get_public_report(token: str):
    """Return a shared report by token without requiring authentication."""
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        with db_readonly() as conn:
            row = IntelligenceRepository(conn).get_public_report(token_hash)
    except Exception:
        logger.exception("Could not read shared intelligence report")
        return jsonify({"success": False, "message": "report unavailable"}), 500

    if row is None:
        return jsonify({"success": False, "message": "report not found"}), 404
    return jsonify({"report": project_public_report(row)}), 200


__all__ = ["get_public_report", "project_public_report", "public_intelligence"]
