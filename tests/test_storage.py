"""Unit tests for storage operations (JSON read/write)."""
import json
import tempfile
from pathlib import Path

import pytest

from rolloforge.models import AnalysisResult, Bookmark, ScoringInputs
from rolloforge.storage import (
    load_analysis_results,
    load_bookmarks,
    load_json,
    load_known_bookmark_ids,
    load_seen_bookmark_ids,
    merge_bookmarks,
    save_analysis_results,
    save_bookmarks,
    save_known_bookmark_ids,
    save_seen_bookmark_ids,
    upsert_analysis_results,
    write_json,
)


class TestLoadJson:
    """Tests for load_json function."""

    def test_load_existing_file(self, tmp_path):
        """Load JSON from existing file."""
        test_file = tmp_path / "test.json"
        test_data = {"key": "value", "number": 42}
        test_file.write_text(json.dumps(test_data))

        result = load_json(test_file, default={})
        assert result == test_data

    def test_load_nonexistent_file_returns_default(self, tmp_path):
        """Load from nonexistent file returns default."""
        test_file = tmp_path / "nonexistent.json"
        default = {"default": "value"}

        result = load_json(test_file, default=default)
        assert result == default

    def test_load_invalid_json_returns_default(self, tmp_path):
        """Load invalid JSON returns default."""
        test_file = tmp_path / "invalid.json"
        test_file.write_text("not valid json")
        default = {"default": "value"}

        result = load_json(test_file, default=default)
        assert result == default

    def test_load_empty_file_returns_default(self, tmp_path):
        """Load empty file returns default."""
        test_file = tmp_path / "empty.json"
        test_file.write_text("")
        default = []

        result = load_json(test_file, default=default)
        assert result == default


class TestWriteJson:
    """Tests for write_json function."""

    def test_write_dict(self, tmp_path):
        """Write dictionary to JSON file."""
        test_file = tmp_path / "output.json"
        test_data = {"key": "value", "number": 42}

        write_json(test_file, test_data)

        assert test_file.exists()
        content = json.loads(test_file.read_text())
        assert content == test_data

    def test_write_list(self, tmp_path):
        """Write list to JSON file."""
        test_file = tmp_path / "output.json"
        test_data = [1, 2, 3, "test"]

        write_json(test_file, test_data)

        content = json.loads(test_file.read_text())
        assert content == test_data

    def test_creates_parent_directories(self, tmp_path):
        """Creates parent directories if needed."""
        test_file = tmp_path / "nested" / "dirs" / "output.json"
        test_data = {"test": "data"}

        write_json(test_file, test_data)

        assert test_file.exists()

    def test_writes_pretty_json(self, tmp_path):
        """Writes indented JSON with newline."""
        test_file = tmp_path / "output.json"
        test_data = {"key": "value"}

        write_json(test_file, test_data)

        content = test_file.read_text()
        assert "\n" in content  # Has newline at end
        assert "  " in content  # Has indentation

    def test_handles_unicode(self, tmp_path):
        """Handles unicode characters."""
        test_file = tmp_path / "unicode.json"
        test_data = {"text": "Hello 世界 🌍"}

        write_json(test_file, test_data)

        content = json.loads(test_file.read_text())
        assert content["text"] == "Hello 世界 🌍"


class TestBookmarkStorage:
    """Tests for bookmark storage operations."""

    def test_load_bookmarks_from_file(self, tmp_path):
        """Load bookmarks from JSON file."""
        test_file = tmp_path / "bookmarks.json"
        bookmarks_data = [
            {
                "id": "bm1",
                "source": "x",
                "url": "https://x.com/test/1",
                "text": "Test tweet",
                "title": "Test Title",
                "author": "testuser",
            },
            {
                "id": "bm2",
                "source": "web",
                "url": "https://example.com",
                "text": "Article content",
            },
        ]
        test_file.write_text(json.dumps(bookmarks_data))

        bookmarks = load_bookmarks(test_file)

        assert len(bookmarks) == 2
        assert all(isinstance(bm, Bookmark) for bm in bookmarks)
        assert bookmarks[0].id == "bm1"
        assert bookmarks[1].url == "https://example.com"

    def test_load_bookmarks_empty_file(self, tmp_path):
        """Load bookmarks from empty file returns empty list."""
        test_file = tmp_path / "empty.json"
        test_file.write_text("[]")

        bookmarks = load_bookmarks(test_file)
        assert bookmarks == []

    def test_load_bookmarks_skips_invalid(self, tmp_path):
        """Load bookmarks skips invalid entries."""
        test_file = tmp_path / "bookmarks.json"
        bookmarks_data = [
            {"id": "bm1", "source": "x", "url": "https://x.com/1", "text": "Valid"},
            "not a dict",  # Invalid entry
            {"id": "", "source": "x", "url": "", "text": ""},  # Invalid (empty id)
        ]
        test_file.write_text(json.dumps(bookmarks_data))

        bookmarks = load_bookmarks(test_file)

        assert len(bookmarks) == 1
        assert bookmarks[0].id == "bm1"

    def test_save_bookmarks(self, tmp_path):
        """Save bookmarks to JSON file."""
        test_file = tmp_path / "bookmarks.json"
        bookmarks = [
            Bookmark(id="bm1", source="x", url="https://x.com/1", text="Test", title="Title"),
            Bookmark(id="bm2", source="web", url="https://example.com", text="Content"),
        ]

        save_bookmarks(bookmarks, test_file)

        content = json.loads(test_file.read_text())
        assert len(content) == 2
        assert content[0]["id"] == "bm1"
        assert content[1]["url"] == "https://example.com"

    def test_save_bookmarks_roundtrip(self, tmp_path):
        """Save and load bookmarks preserves data."""
        test_file = tmp_path / "bookmarks.json"
        original = [
            Bookmark(
                id="bm1",
                source="x",
                url="https://x.com/1",
                text="Test content",
                title="Test Title",
                author="author1",
                tags=["tag1", "tag2"],
            ),
        ]

        save_bookmarks(original, test_file)
        loaded = load_bookmarks(test_file)

        assert len(loaded) == 1
        assert loaded[0].id == "bm1"
        assert loaded[0].title == "Test Title"
        assert loaded[0].tags == ["tag1", "tag2"]


class TestMergeBookmarks:
    """Tests for bookmark merging."""

    def test_merge_no_overlap(self):
        """Merge bookmarks with no overlap."""
        existing = [
            Bookmark(id="bm1", source="x", url="https://x.com/1", text="First"),
        ]
        incoming = [
            Bookmark(id="bm2", source="x", url="https://x.com/2", text="Second"),
        ]

        merged = merge_bookmarks(existing, incoming)

        assert len(merged) == 2
        ids = {bm.id for bm in merged}
        assert ids == {"bm1", "bm2"}

    def test_merge_with_overlap(self):
        """Merge bookmarks with overlapping IDs."""
        existing = [
            Bookmark(id="bm1", source="x", url="https://x.com/1", text="Old"),
            Bookmark(id="bm2", source="x", url="https://x.com/2", text="Second"),
        ]
        incoming = [
            Bookmark(id="bm1", source="x", url="https://x.com/1", text="Updated"),
            Bookmark(id="bm3", source="x", url="https://x.com/3", text="Third"),
        ]

        merged = merge_bookmarks(existing, incoming)

        assert len(merged) == 3
        # bm1 should have updated text
        bm1 = next(bm for bm in merged if bm.id == "bm1")
        assert bm1.text == "Updated"

    def test_merge_sorts_by_date(self):
        """Merge results sorted by bookmarked_at date descending."""
        existing = [
            Bookmark(id="bm1", source="x", url="https://x.com/1", text="First", bookmarked_at="2024-01-01T00:00:00Z"),
        ]
        incoming = [
            Bookmark(id="bm2", source="x", url="https://x.com/2", text="Second", bookmarked_at="2024-01-02T00:00:00Z"),
        ]

        merged = merge_bookmarks(existing, incoming)

        assert merged[0].id == "bm2"  # Newer first
        assert merged[1].id == "bm1"


class TestAnalysisResultStorage:
    """Tests for analysis result storage."""

    def test_load_analysis_results(self, tmp_path):
        """Load analysis results from file."""
        test_file = tmp_path / "analysis.json"
        analysis_data = [
            {
                "bookmark_id": "bm1",
                "summary": "Test summary",
                "recommendation_reason": "Because",
                "key_insights": ["insight1"],
                "scoring_inputs": {
                    "relevance": 8.0, "practical_value": 7.0, "actionability": 6.0,
                    "stage_fit": 7.0, "novelty": 5.0, "excitement": 6.0,
                    "difficulty": 4.0, "time_cost": 3.0,
                },
                "worth_score": 7.5,
                "effort_score": 3.5,
                "priority_score": 5.5,
                "recommendation_bucket": "test_this_week",
                "analysis_source": "test",
                "analyzed_at": "2024-01-01T00:00:00Z",
            },
        ]
        test_file.write_text(json.dumps(analysis_data))

        results = load_analysis_results(test_file)

        assert len(results) == 1
        assert isinstance(results[0], AnalysisResult)
        assert results[0].bookmark_id == "bm1"
        assert results[0].priority_score == 5.5

    def test_load_analysis_skips_invalid(self, tmp_path):
        """Load analysis skips entries without bookmark_id."""
        test_file = tmp_path / "analysis.json"
        analysis_data = [
            {"bookmark_id": "bm1", "summary": "Valid"},
            {"summary": "No bookmark_id"},  # Invalid
            "not a dict",  # Invalid
        ]
        test_file.write_text(json.dumps(analysis_data))

        results = load_analysis_results(test_file)

        assert len(results) == 1
        assert results[0].bookmark_id == "bm1"

    def test_save_analysis_results(self, tmp_path):
        """Save analysis results to file."""
        test_file = tmp_path / "analysis.json"
        results = [
            AnalysisResult(
                bookmark_id="bm1",
                summary="Summary",
                recommendation_reason="Reason",
                key_insights=["insight"],
                scoring_inputs=ScoringInputs(
                    relevance=8.0, practical_value=7.0, actionability=6.0,
                    stage_fit=7.0, novelty=5.0, excitement=6.0,
                    difficulty=4.0, time_cost=3.0,
                ),
                worth_score=7.0,
                effort_score=3.0,
                priority_score=5.0,
                recommendation_bucket="test_this_week",
                analysis_source="test",
                analyzed_at="2024-01-01T00:00:00Z",
            ),
        ]

        save_analysis_results(results, test_file)

        content = json.loads(test_file.read_text())
        assert len(content) == 1
        assert content[0]["bookmark_id"] == "bm1"
        assert "scoring_inputs" in content[0]

    def test_upsert_analysis_results(self, tmp_path):
        """Upsert merges and sorts by priority."""
        test_file = tmp_path / "analysis.json"
        existing = [
            AnalysisResult(
                bookmark_id="bm1",
                summary="Low priority",
                recommendation_reason="Reason",
                key_insights=[],
                scoring_inputs=ScoringInputs(
                    relevance=5.0, practical_value=5.0, actionability=5.0,
                    stage_fit=5.0, novelty=5.0, excitement=5.0,
                    difficulty=5.0, time_cost=5.0,
                ),
                worth_score=5.0,
                effort_score=5.0,
                priority_score=3.0,
                recommendation_bucket="archive",
                analysis_source="test",
                analyzed_at="2024-01-01T00:00:00Z",
            ),
        ]
        new_results = [
            AnalysisResult(
                bookmark_id="bm2",
                summary="High priority",
                recommendation_reason="Reason",
                key_insights=[],
                scoring_inputs=ScoringInputs(
                    relevance=9.0, practical_value=9.0, actionability=9.0,
                    stage_fit=9.0, novelty=9.0, excitement=9.0,
                    difficulty=3.0, time_cost=3.0,
                ),
                worth_score=9.0,
                effort_score=3.0,
                priority_score=7.0,
                recommendation_bucket="test_this_week",
                analysis_source="test",
                analyzed_at="2024-01-02T00:00:00Z",
            ),
        ]

        upsert_analysis_results(existing, new_results, test_file)
        loaded = load_analysis_results(test_file)

        assert len(loaded) == 2
        assert loaded[0].bookmark_id == "bm2"  # Higher priority first
        assert loaded[1].bookmark_id == "bm1"

    def test_upsert_updates_existing(self, tmp_path):
        """Upsert updates existing entries."""
        test_file = tmp_path / "analysis.json"
        existing = [
            AnalysisResult(
                bookmark_id="bm1",
                summary="Old",
                recommendation_reason="Reason",
                key_insights=[],
                scoring_inputs=ScoringInputs(
                    relevance=5.0, practical_value=5.0, actionability=5.0,
                    stage_fit=5.0, novelty=5.0, excitement=5.0,
                    difficulty=5.0, time_cost=5.0,
                ),
                worth_score=5.0,
                effort_score=5.0,
                priority_score=3.0,
                recommendation_bucket="archive",
                analysis_source="test",
                analyzed_at="2024-01-01T00:00:00Z",
            ),
        ]
        new_results = [
            AnalysisResult(
                bookmark_id="bm1",
                summary="Updated",
                recommendation_reason="Reason",
                key_insights=[],
                scoring_inputs=ScoringInputs(
                    relevance=5.0, practical_value=5.0, actionability=5.0,
                    stage_fit=5.0, novelty=5.0, excitement=5.0,
                    difficulty=5.0, time_cost=5.0,
                ),
                worth_score=5.0,
                effort_score=5.0,
                priority_score=3.0,
                recommendation_bucket="archive",
                analysis_source="test",
                analyzed_at="2024-01-02T00:00:00Z",
            ),
        ]

        upsert_analysis_results(existing, new_results, test_file)
        loaded = load_analysis_results(test_file)

        assert len(loaded) == 1
        assert loaded[0].summary == "Updated"


class TestSeenBookmarksStorage:
    """Tests for seen bookmarks tracking."""

    def test_load_known_bookmark_ids(self, tmp_path):
        """Load known bookmark IDs."""
        test_file = tmp_path / "seen.json"
        test_file.write_text(json.dumps({
            "bookmark_ids": ["bm1", "bm2", "bm3"],
            "analyzed_bookmark_ids": ["bm1"],
        }))

        ids = load_known_bookmark_ids(test_file)

        assert ids == {"bm1", "bm2", "bm3"}

    def test_save_known_bookmark_ids(self, tmp_path):
        """Save known bookmark IDs."""
        test_file = tmp_path / "seen.json"

        save_known_bookmark_ids(["bm1", "bm2", "bm1"], test_file)  # bm1 duplicated

        content = json.loads(test_file.read_text())
        assert content["bookmark_ids"] == ["bm1", "bm2"]  # Sorted, unique
        assert "updated_at" in content

    def test_load_seen_bookmark_ids(self, tmp_path):
        """Load analyzed bookmark IDs."""
        test_file = tmp_path / "seen.json"
        test_file.write_text(json.dumps({
            "bookmark_ids": ["bm1", "bm2"],
            "analyzed_bookmark_ids": ["bm1"],
        }))

        ids = load_seen_bookmark_ids(test_file)

        assert ids == {"bm1"}

    def test_save_seen_bookmark_ids(self, tmp_path):
        """Save analyzed bookmark IDs."""
        test_file = tmp_path / "seen.json"

        save_seen_bookmark_ids(["bm1", "bm2"], test_file)

        content = json.loads(test_file.read_text())
        assert content["analyzed_bookmark_ids"] == ["bm1", "bm2"]

    def test_load_invalid_payload(self, tmp_path):
        """Load from invalid payload returns empty defaults."""
        test_file = tmp_path / "seen.json"
        test_file.write_text("[]")  # Not a dict

        ids = load_known_bookmark_ids(test_file)
        assert ids == set()

    def test_preserves_existing_data(self, tmp_path):
        """Saving preserves existing data in file."""
        test_file = tmp_path / "seen.json"
        test_file.write_text(json.dumps({
            "bookmark_ids": ["old1"],
            "analyzed_bookmark_ids": ["old_analyzed"],
            "custom_field": "preserved",
        }))

        save_known_bookmark_ids(["new1"], test_file)

        content = json.loads(test_file.read_text())
        assert content["bookmark_ids"] == ["new1"]
        assert content["analyzed_bookmark_ids"] == ["old_analyzed"]
        assert content["custom_field"] == "preserved"


class TestIntegration:
    """Integration tests for storage operations."""

    def test_full_workflow(self, tmp_path):
        """Test full storage workflow."""
        bookmarks_file = tmp_path / "bookmarks.json"
        analysis_file = tmp_path / "analysis.json"
        seen_file = tmp_path / "seen.json"

        # Create and save bookmarks
        bookmarks = [
            Bookmark(id="bm1", source="x", url="https://x.com/1", text="Tweet"),
        ]
        save_bookmarks(bookmarks, bookmarks_file)
        save_known_bookmark_ids(["bm1"], seen_file)

        # Create and save analysis
        results = [
            AnalysisResult(
                bookmark_id="bm1",
                summary="Summary",
                recommendation_reason="Reason",
                key_insights=["insight"],
                scoring_inputs=ScoringInputs(
                    relevance=8.0, practical_value=7.0, actionability=6.0,
                    stage_fit=7.0, novelty=5.0, excitement=6.0,
                    difficulty=4.0, time_cost=3.0,
                ),
                worth_score=7.0,
                effort_score=3.0,
                priority_score=5.0,
                recommendation_bucket="test_this_week",
                analysis_source="deepseek",
                analyzed_at="2024-01-01T00:00:00Z",
            ),
        ]
        save_analysis_results(results, analysis_file)
        save_seen_bookmark_ids(["bm1"], seen_file)

        # Load everything back
        loaded_bookmarks = load_bookmarks(bookmarks_file)
        loaded_analysis = load_analysis_results(analysis_file)
        known_ids = load_known_bookmark_ids(seen_file)
        seen_ids = load_seen_bookmark_ids(seen_file)

        assert len(loaded_bookmarks) == 1
        assert len(loaded_analysis) == 1
        assert known_ids == {"bm1"}
        assert seen_ids == {"bm1"}
