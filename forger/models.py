from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(payload: dict[str, Any], key: str) -> bool | None:
    """Return a real bool only when the payload included one."""
    if key not in payload:
        return None
    value = payload[key]
    if isinstance(value, bool):
        return value
    return None


@dataclass(slots=True)
class Bookmark:
    id: str
    source: str
    url: str
    text: str
    title: str | None = None
    note: str | None = None
    author: str | None = None
    created_at: str | None = None
    bookmarked_at: str | None = None
    tags: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Bookmark":
        return cls(
            id=str(payload.get("id", "")).strip(),
            source=str(payload.get("source", "x")).strip() or "x",
            url=str(payload.get("url", "")).strip(),
            text=str(payload.get("text", "")).strip(),
            title=str(payload.get("title", "")).strip() or None,
            note=str(payload.get("note", "")).strip() or None,
            author=payload.get("author"),
            created_at=payload.get("created_at"),
            bookmarked_at=payload.get("bookmarked_at"),
            tags=[str(tag) for tag in payload.get("tags", []) if str(tag).strip()],
            raw_payload=payload.get("raw_payload", {}) or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScoringInputs:
    relevance: float
    practical_value: float
    actionability: float
    stage_fit: float
    novelty: float
    excitement: float
    difficulty: float
    time_cost: float

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScoringInputs":
        return cls(
            relevance=float(payload.get("relevance", 0)),
            practical_value=float(payload.get("practical_value", 0)),
            actionability=float(payload.get("actionability", 0)),
            stage_fit=float(payload.get("stage_fit", 0)),
            novelty=float(payload.get("novelty", 0)),
            excitement=float(payload.get("excitement", 0)),
            difficulty=float(payload.get("difficulty", 0)),
            time_cost=float(payload.get("time_cost", 0)),
        )

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(slots=True)
class AnalysisResult:
    bookmark_id: str
    summary: str
    recommendation_reason: str
    key_insights: list[str]
    scoring_inputs: ScoringInputs
    worth_score: float
    effort_score: float
    priority_score: float
    recommendation_bucket: str
    analysis_source: str
    analyzed_at: str
    confidence: str | None = None
    difficulty_reason: str | None = None
    next_action: str | None = None
    # Title from DeepSeek analysis (2026-05-04)
    title: str | None = None
    # Prose tying the bookmark to the user's goals/preferences (from profile.md)
    relates_to: str | None = None
    # Personalized scoring fields (added 2026-05-01)
    tags: list[str] = field(default_factory=list)
    personalized_worth_score: float | None = None
    personalized_priority_score: float | None = None
    personalized_bucket: str | None = None
    personalized_why: str | None = None
    pinned: bool = False
    pinned_reason: str | None = None
    decayed_at: str | None = None
    decayed_from_bucket: str | None = None
    decay_reason: str | None = None
    original_worth_score: float | None = None
    original_priority_score: float | None = None
    original_bucket: str | None = None
    alignment_score: float | None = None
    # Binary answers from the model/agent. None means the caller did not
    # provide them — do not invent False, or refine_bucket will treat them
    # as a real "all false" decision.
    actionable_this_week: bool | None = None
    reduces_friction: bool | None = None
    reference_material: bool | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AnalysisResult":
        return cls(
            bookmark_id=str(payload.get("bookmark_id", "")).strip(),
            summary=str(payload.get("summary", "")).strip(),
            recommendation_reason=str(payload.get("recommendation_reason", "")).strip(),
            key_insights=[str(item).strip() for item in payload.get("key_insights", []) if str(item).strip()],
            scoring_inputs=ScoringInputs.from_dict(payload.get("scoring_inputs", {})),
            worth_score=float(payload.get("worth_score", 0)),
            effort_score=float(payload.get("effort_score", 0)),
            priority_score=float(payload.get("priority_score", 0)),
            recommendation_bucket=str(payload.get("recommendation_bucket", "archive")).strip(),
            analysis_source=str(payload.get("analysis_source", "fallback")).strip(),
            analyzed_at=str(payload.get("analyzed_at", "")).strip(),
            confidence=str(payload.get("confidence", "")).strip() or None,
            difficulty_reason=str(payload.get("difficulty_reason", "")).strip() or None,
            next_action=str(payload.get("next_action", "")).strip() or None,
            title=str(payload.get("title", "")).strip() or None,
            relates_to=str(payload.get("relates_to", "")).strip() or None,
            tags=[str(tag) for tag in payload.get("tags", []) if str(tag).strip()],
            # Personalized scoring fields
            personalized_worth_score=payload.get("personalized_worth_score"),
            personalized_priority_score=payload.get("personalized_priority_score"),
            personalized_bucket=payload.get("personalized_bucket"),
            personalized_why=payload.get("personalized_why"),
            pinned=bool(payload.get("pinned", False)),
            pinned_reason=_optional_str(payload.get("pinned_reason")),
            decayed_at=_optional_str(payload.get("decayed_at")),
            decayed_from_bucket=_optional_str(payload.get("decayed_from_bucket")),
            decay_reason=_optional_str(payload.get("decay_reason")),
            original_worth_score=payload.get("original_worth_score"),
            original_priority_score=payload.get("original_priority_score"),
            original_bucket=payload.get("original_bucket"),
            alignment_score=payload.get("alignment_score"),
            actionable_this_week=_optional_bool(payload, "actionable_this_week"),
            reduces_friction=_optional_bool(payload, "reduces_friction"),
            reference_material=_optional_bool(payload, "reference_material"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scoring_inputs"] = self.scoring_inputs.to_dict()
        # Ensure tags is always a list
        if payload.get("tags") is None:
            payload["tags"] = []
        # Include title if present
        if self.title is not None:
            payload["title"] = self.title
        # Only persist binary answers the model/agent actually provided.
        for key in ("actionable_this_week", "reduces_friction", "reference_material"):
            if payload.get(key) is None:
                payload.pop(key, None)
        return payload
