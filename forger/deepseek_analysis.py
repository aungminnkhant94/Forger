"""DeepSeek LLM integration for Forger bookmark analysis.

Replaces heuristic scoring with real LLM analysis.
"""
import json
import logging
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Load environment variables from .env file
load_dotenv()

LOGGER = logging.getLogger(__name__)

# --- LLM provider configuration ---------------------------------------------
# ANALYSIS_PROVIDER selects the brain:
#   deepseek (default) -> DEEPSEEK_API_KEY @ https://api.deepseek.com
#   kimi               -> KIMI_API_KEY @ https://api.kimi.com/coding/v1
#   custom             -> LLM_API_KEY + LLM_BASE_URL + LLM_MODEL
#                         (any OpenAI-compatible API: GLM, OpenAI, Ollama, ...)
ANALYSIS_PROVIDER = os.getenv("ANALYSIS_PROVIDER", "deepseek").lower()
_PROVIDER_CFGS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "kimi": {
        "base_url": "https://api.kimi.com/coding/v1",
        "model": os.getenv("KIMI_MODEL", "k3"),
        "api_key_env": "KIMI_API_KEY",
    },
    "custom": {
        "base_url": os.getenv("LLM_BASE_URL", ""),
        "model": os.getenv("LLM_MODEL", ""),
        "api_key_env": "LLM_API_KEY",
    },
}
ANALYSIS_TIMEOUT = 60  # seconds
# Some reasoning models spend output tokens on reasoning BEFORE the JSON
# answer; keep enough headroom so finish_reason never becomes "length".
ANALYSIS_MAX_TOKENS = 8000

# --- User context source ----------------------------------------------------
# Personalization comes from ONE plain-text file the user owns: profile.md.
# Copy profile.example.md, describe yourself and your work, done. Override the
# location with FORGER_PROFILE. Optionally point
# FORGER_EXTRA_CONTEXT_DIR at a folder of .md notes; paragraphs matching
# each bookmark are injected as extra context.
BASE_DIR = Path(__file__).resolve().parents[1]
PROFILE_PATH = Path(os.getenv("FORGER_PROFILE", str(BASE_DIR / "profile.md")))
_extra_ctx = os.getenv("FORGER_EXTRA_CONTEXT_DIR")
EXTRA_CONTEXT_DIR = Path(_extra_ctx) if _extra_ctx else None


class DeepSeekError(Exception):
    """Base exception for DeepSeek errors."""
    pass


class DeepSeekConfigError(DeepSeekError):
    """Raised when configuration is invalid."""
    pass


class DeepSeekAPIError(DeepSeekError):
    """Raised when API call fails."""
    pass


@lru_cache(maxsize=1)
def _load_user_context() -> str:
    """Load the user's profile.md to personalize bookmark analysis."""
    sections = []
    max_chars_per_file = 6000

    if not PROFILE_PATH.exists():
        LOGGER.warning(
            "profile.md not found at %s - analysis will run WITHOUT user "
            "personalization. Copy profile.example.md to profile.md and "
            "describe yourself to fix this.",
            PROFILE_PATH,
        )
        return "No user profile was available."

    for path in (PROFILE_PATH,):
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            LOGGER.warning("Profile file missing for DeepSeek context: %s", path)
            continue
        except Exception as exc:
            LOGGER.warning("Failed to read profile file %s: %s", path, exc)
            continue

        trimmed = content[:max_chars_per_file]
        if len(content) > max_chars_per_file:
            trimmed += "\n...[truncated]"
        sections.append(f"## {path.name}\n{trimmed}")

    if not sections:
        return "No user profile files were available."

    return "\n\n".join(sections)


def _load_wiki_context(bookmark_text: str, title: str = "", url: str = "") -> str:
    """Search FORGER_EXTRA_CONTEXT_DIR (.md notes) for relevant context.

    Returns "" when no extra context dir is configured.
    """
    if EXTRA_CONTEXT_DIR is None:
        return ""
    try:
        # Extract key terms from bookmark for searching
        search_terms = set()
        
        # Add title words (filtered)
        if title:
            search_terms.update(w.lower() for w in re.findall(r'\b[A-Za-z]{4,}\b', title))
        
        # Add URL domain
        if url:
            domain = re.search(r'https?://(?:www\.)?([^/]+)', url)
            if domain:
                search_terms.add(domain.group(1).split('.')[0].lower())
        
        # Add key terms from text (first 500 chars only)
        if bookmark_text:
            text_terms = re.findall(r'\b[A-Za-z]{5,}\b', bookmark_text[:500])
            # Count frequency and take top terms
            from collections import Counter
            term_counts = Counter(t.lower() for t in text_terms)
            search_terms.update(t for t, c in term_counts.most_common(8))
        
        if not search_terms:
            return ""
        
        wiki_sources = EXTRA_CONTEXT_DIR
        if not wiki_sources.is_dir():
            return ""
        
        found_sections = []
        max_sections = 3
        max_chars_per_section = 2000
        
        # Search each source file for matching terms
        for source_file in sorted(wiki_sources.glob("*.md"), reverse=True)[:5]:
            try:
                content = source_file.read_text(encoding="utf-8")
                # Find paragraphs containing search terms
                paragraphs = content.split("\n\n")
                matching = []
                for para in paragraphs:
                    para_lower = para.lower()
                    if any(term in para_lower for term in search_terms):
                        matching.append(para)
                
                if matching:
                    section_text = "\n\n".join(matching[:3])  # Top 3 matching paragraphs
                    if len(section_text) > max_chars_per_section:
                        section_text = section_text[:max_chars_per_section] + "\n...[truncated]"
                    found_sections.append(f"### {source_file.name}\n{section_text}")
                    
                if len(found_sections) >= max_sections:
                    break
                    
            except Exception:
                continue
        
        if found_sections:
            return "\n\n".join(found_sections)
        return ""
        
    except Exception as e:
        LOGGER.warning(f"Wiki context loading failed: {e}")
        return ""


def get_analysis_client() -> Optional[OpenAI]:
    """Initialize the analysis client for the configured provider."""
    cfg = _PROVIDER_CFGS.get(ANALYSIS_PROVIDER)
    if cfg is None:
        LOGGER.error(
            "ANALYSIS_PROVIDER=%r is unknown (use deepseek | kimi | custom)",
            ANALYSIS_PROVIDER,
        )
        return None
    api_key = os.getenv(cfg["api_key_env"])
    if not api_key:
        LOGGER.error(
            "ANALYSIS_PROVIDER=%s but %s is not set",
            ANALYSIS_PROVIDER,
            cfg["api_key_env"],
        )
        return None
    if not cfg["base_url"]:
        LOGGER.error("ANALYSIS_PROVIDER=custom requires LLM_BASE_URL to be set")
        return None
    return OpenAI(
        api_key=api_key,
        base_url=cfg["base_url"],
        timeout=ANALYSIS_TIMEOUT,
        max_retries=0,  # We handle retries with tenacity
    )


def _analysis_model() -> str:
    cfg = _PROVIDER_CFGS.get(ANALYSIS_PROVIDER, {})
    return cfg.get("model", "")


@retry(
    retry=retry_if_exception_type((APIConnectionError, APITimeoutError, RateLimitError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True
)
def _call_analysis_api(client: OpenAI, prompt: str) -> Optional[str]:
    """Make analysis API call with retry logic."""
    request = dict(
        model=_analysis_model(),
        messages=[
            {"role": "system", "content": "You are an expert bookmark analyzer. You judge every link strictly against the user's profile provided in the prompt. You provide honest, actionable analysis."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=ANALYSIS_MAX_TOKENS,
    )
    if ANALYSIS_PROVIDER != "kimi":
        # Kimi coding endpoint: no json_object mode, temperature locked to 1.
        request["temperature"] = 0.7
        request["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**request)
    choice = response.choices[0]
    content = choice.message.content
    if not content:
        details = getattr(response.usage, "completion_tokens_details", None)
        LOGGER.error(
            "Analysis API returned EMPTY content (finish_reason=%s, reasoning_tokens=%s). "
            "A reasoning model consumed the whole max_tokens budget before answering; "
            "raise ANALYSIS_MAX_TOKENS.",
            choice.finish_reason,
            getattr(details, "reasoning_tokens", None),
        )
    return content


def _parse_json_response(content: str) -> Optional[dict]:
    """Best-effort parser for model JSON output."""
    if not content:
        return None

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()

    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(cleaned[start:end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def _repair_json_response(client: OpenAI, raw_content: str) -> Optional[dict]:
    """Ask Kimi to repair malformed JSON without changing meaning."""
    if not raw_content or not raw_content.strip():
        return None

    response = client.chat.completions.create(
        model=_analysis_model(),
        messages=[
            {
                "role": "system",
                "content": "Repair malformed JSON. Return only one valid JSON object. Preserve meaning; do not add commentary.",
            },
            {
                "role": "user",
                "content": f"Fix this malformed JSON and return only valid JSON:\n\n{raw_content}",
            },
        ],
        temperature=0.1,
        max_tokens=ANALYSIS_MAX_TOKENS,
    )
    repaired = response.choices[0].message.content
    return _parse_json_response(repaired)


def derive_legacy_scores(analysis: dict) -> dict:
    """Derive 0-10 scores, bucket fallback and scoring_inputs from the three
    binary answers (actionable_this_week / reduces_friction / reference_material).

    Used by both the API analysis path and agent-written analyses so both end
    up dashboard-compatible.
    """
    actionable = analysis.get("actionable_this_week", False)
    reduces_friction = analysis.get("reduces_friction", False)
    reference = analysis.get("reference_material", False)

    relevance = 8.0 if actionable else (6.0 if reduces_friction else (4.0 if reference else 2.0))
    practical_value = 8.0 if reduces_friction else (5.0 if reference else 2.0)
    actionability = 9.0 if actionable else (4.0 if reduces_friction else 1.0)
    stage_fit = 7.0 if (actionable or reduces_friction) else 4.0
    novelty = analysis.get("novelty", 5.0)
    excitement = analysis.get("excitement", 5.0)
    difficulty = 3.0 if actionable else (5.0 if reduces_friction else 7.0)
    time_cost = 2.0 if actionable else (5.0 if reduces_friction else 7.0)

    if "recommendation_bucket" not in analysis:
        if actionable:
            analysis["recommendation_bucket"] = "test_this_week"
        elif reduces_friction:
            analysis["recommendation_bucket"] = "build_later"
        elif reference:
            analysis["recommendation_bucket"] = "archive"
        else:
            analysis["recommendation_bucket"] = "ignore"

    worth_score = 8.0 if actionable else (6.5 if reduces_friction else (4.0 if reference else 1.5))
    effort_score = 2.0 if actionable else (5.0 if reduces_friction else 7.0)
    priority_score = max(0.0, min(10.0, worth_score - (0.3 * effort_score)))

    if "scoring_inputs" not in analysis:
        analysis["scoring_inputs"] = {
            "relevance": relevance,
            "practical_value": practical_value,
            "actionability": actionability,
            "stage_fit": stage_fit,
            "novelty": novelty,
            "excitement": excitement,
            "difficulty": difficulty,
            "time_cost": time_cost,
        }

    analysis["worth_score"] = analysis.get("worth_score", worth_score)
    analysis["effort_score"] = analysis.get("effort_score", effort_score)
    analysis["priority_score"] = analysis.get("priority_score", priority_score)
    return analysis


def analyze_with_deepseek(text: str, title: str = "", url: str = "", user_note: str | None = None) -> Optional[dict]:
    """
    Analyze bookmark content using the configured LLM.

    Args:
        user_note: the user's own words accompanying the link, if any. Weighed
            as the strongest signal of why they saved it.

    Returns analysis dict or None if failed.
    """
    client = get_analysis_client()
    if not client:
        LOGGER.error("Failed to initialize analysis client")
        return None

    # Truncate text if too long (Kimi has context limits)
    max_chars = 8000
    if len(text) > max_chars:
        text = text[:max_chars] + "... [truncated]"

    user_context = _load_user_context()
    wiki_context = _load_wiki_context(text, title, url)

    # Build extra-context section if available
    extra_section = ""
    if wiki_context:
        extra_section = f"""

EXTRA CONTEXT (matching notes from the user's knowledge base):
{wiki_context}
"""

    note_section = ""
    if user_note and user_note.strip():
        note_section = f"""
USER NOTE (the user's own words when saving this link — the single strongest
signal of why they care; judge the bookmark through it):
{user_note.strip()}
"""

    prompt = f"""You are the user's personal bookmark analyst. Do not do generic internet summarization.

Your job is to read the bookmark fully, read the user's profile below, and judge whether this is useful for THIS USER specifically.

USER PROFILE:
{user_context}{extra_section}{note_section}

BOOKMARK TO ANALYZE:
URL: {url}
Title: {title}
Content: {text}

Analyze the bookmark against the user's real context:
- their current projects, systems, and workflows as described in the profile
- what they are actively building or fixing now
- whether this reduces friction, creates leverage, saves time, improves infra, or is directly useful for current exploration
- whether it is actually actionable this week, worth building later, or just reference material
- if the profile names priority topics or always-relevant areas, bump those UP

Respond in valid JSON. Instead of arbitrary 0-10 scores, answer these 3 focused questions:

{{
  "title": "Polished title, concise, no trailing dots",
  "summary": "3-4 sentences. Explain what it is, the core takeaway, and why it matters for the user specifically.",
  "recommendation_reason": "One blunt sentence explaining why this is or is not relevant to the user right now.",
  "relates_to": "A short prose paragraph (2-4 sentences) tying this to the user's specific goals, projects, or preferences named in the USER PROFILE above. If nothing connects, say so plainly.",
  "key_insights": ["3-5 concrete takeaways grounded in the content"],
  "tags": ["2-6 specific tags, never generic"],
  "actionable_this_week": false,
  "reduces_friction": false,
  "reference_material": false,
  "recommendation_bucket": "test_this_week|build_later|archive|ignore"
}}

Question definitions:
- **actionable_this_week**: Can the user act on this TODAY or within 7 days? Does it have immediate steps they can take? (Not "someday" — THIS WEEK)
- **reduces_friction**: Does this make something they're currently building faster, cheaper, easier, or better? Does it remove a blocker?
- **reference_material**: Is this something they'll want to FIND again later, even if they don't act on it now? (Docs, benchmarks, comparisons, guides)

Bucketing rules:
- **test_this_week**: actionable_this_week = true (regardless of other answers)
- **build_later**: actionable_this_week = false AND reduces_friction = true
- **archive**: actionable_this_week = false AND reduces_friction = false AND reference_material = true
- **ignore**: All three are false

DEFAULT RULE: When uncertain between two buckets, ALWAYS choose the MORE URGENT one. Action beats reference.

Scoring notes:
- Be strict. Most bookmarks should not be top priority.
- Judge against THIS user's profile, not against a generic tech audience.
- Do not downgrade something just because it is short if it has strong practical leverage.
- Do not use fake personalization language like 'this user should care because'. Just write like an intelligent operator.
- Never use the tag 'general'.
- Prefer specific, concrete tags over broad ones.
- Base the recommendation on the full bookmark content plus the user profile and extra context above, not on crude keyword matching."""

    try:
        content = _call_analysis_api(client, prompt) or ""
        analysis = _parse_json_response(content)
        if analysis is None:
            LOGGER.warning("Analysis response was not valid JSON (len=%d), attempting repair pass", len(content))
            analysis = _repair_json_response(client, content)
        if analysis is None:
            raise json.JSONDecodeError("Unable to parse analysis JSON", content, 0)
        
        # Transform to match expected format
        # Handle both old 'bucket' and new 'recommendation_bucket'
        if "bucket" in analysis and "recommendation_bucket" not in analysis:
            analysis["recommendation_bucket"] = analysis["bucket"]
        
        # Compute derived scores from the binary answers
        derive_legacy_scores(analysis)

        # Add metadata
        analysis["analysis_source"] = "kimi" if ANALYSIS_PROVIDER == "kimi" else "deepseek"
        analysis["model"] = _analysis_model()
        analysis["relates_to"] = str(analysis.get("relates_to", "") or "").strip()

        LOGGER.info(f"Kimi analysis complete: {analysis.get('title', 'N/A')[:50]}...")
        return analysis
        
    except AuthenticationError as e:
        LOGGER.error(f"Kimi authentication failed: {e}")
        return None
    except RateLimitError as e:
        LOGGER.error(f"Kimi rate limit exceeded: {e}")
        raise  # Let retry handle this
    except APITimeoutError as e:
        LOGGER.error(f"Kimi API timeout: {e}")
        raise  # Let retry handle this
    except APIConnectionError as e:
        LOGGER.error(f"Kimi connection error: {e}")
        raise  # Let retry handle this
    except APIError as e:
        LOGGER.error(f"Kimi API error: {e}")
        return None
    except json.JSONDecodeError as e:
        LOGGER.error(f"Failed to parse Kimi response as JSON: {e}")
        return None
    except Exception as e:
        LOGGER.error(f"Kimi analysis failed with unexpected error: {e}")
        return None


def deepseek_analyze_bookmark(text: str, title: str = "", url: str = "", user_note: str | None = None) -> dict:
    """
    Analyze bookmark with the configured LLM, fall back to heuristic on failure.

    Returns analysis dict.
    """
    # Try LLM first
    try:
        result = analyze_with_deepseek(text, title, url, user_note=user_note)
        if result:
            return result
    except Exception as e:
        LOGGER.warning(f"DeepSeek analysis failed after retries: {e}")
    
    # Fallback to heuristic
    LOGGER.warning("LLM analysis failed, using fallback analysis")
    text_str = text if isinstance(text, str) else text.get("text", "") if isinstance(text, dict) else str(text)
    return {
        "title": title or "Untitled",
        "summary": "[LLM failed - basic analysis] " + text_str[:100],
        "recommendation_reason": "LLM analysis failed, fallback analysis",
        "relates_to": "",
        "key_insights": ["LLM analysis failed — review this bookmark manually"],
        "tags": ["deepseek-failed", "review-manually"],
        "recommendation_bucket": "archive",
        "actionable_this_week": False,
        "reduces_friction": False,
        "reference_material": True,
        "priority_score": 3.0,
        "worth_score": 5.0,
        "effort_score": 4.0,
        "relevance": 3.0,
        "practical_value": 3.0,
        "actionability": 3.0,
        "stage_fit": 3.0,
        "novelty": 3.0,
        "excitement": 3.0,
        "difficulty": 5.0,
        "time_cost": 5.0,
        "scoring_inputs": {
            "relevance": 3.0,
            "practical_value": 3.0,
            "actionability": 3.0,
            "stage_fit": 3.0,
            "novelty": 3.0,
            "excitement": 3.0,
            "difficulty": 5.0,
            "time_cost": 5.0
        },
        "analysis_source": "deepseek_fallback"
    }


if __name__ == "__main__":
    # Test
    test_text = """Karpathy open-sourced autoresearch. 42,000 GitHub stars in a week. 
    The pattern works on anything you can score with a number. Ad copy, cold emails, 
    video scripts, job posts, skill files. 12 cycles per hour, 100 overnight."""
    
    try:
        result = analyze_with_deepseek(test_text, "Test Title", "https://x.com/test")
        print(json.dumps(result, indent=2))
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user")
    except Exception as e:
        LOGGER.error(f"Test failed: {e}")
        print(f"Error: {e}")