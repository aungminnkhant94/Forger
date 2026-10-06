"""Unit tests for DeepSeek analysis pipeline."""
import json
from unittest.mock import MagicMock, patch

import pytest
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from rolloforge.deepseek_analysis import (
    DeepSeekAPIError,
    DeepSeekConfigError,
    DeepSeekError,
    _call_analysis_api,
    analyze_with_deepseek,
    deepseek_analyze_bookmark,
    get_analysis_client,
)


class TestDeepSeekClient:
    """Tests for DeepSeek client initialization."""

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_get_client_success(self, mock_openai):
        """Client created successfully with API key."""
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        client = get_analysis_client()

        assert client is not None
        mock_openai.assert_called_once()
        call_kwargs = mock_openai.call_args.kwargs
        assert call_kwargs["api_key"] == "test-key"
        assert call_kwargs["base_url"] == "https://api.deepseek.com"

    @patch.dict("os.environ", {}, clear=True)
    def test_get_client_no_api_key(self):
        """Returns None when API key not set."""
        client = get_analysis_client()
        assert client is None

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_client_configuration(self, mock_openai):
        """Client configured with correct settings."""
        get_analysis_client()

        call_kwargs = mock_openai.call_args.kwargs
        assert call_kwargs["timeout"] == 60
        assert call_kwargs["max_retries"] == 0


class TestCallDeepSeekAPI:
    """Tests for API calling with retries."""

    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_successful_call(self, mock_openai_class):
        """Successful API call returns content."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{"result": "test"}'
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        result = _call_analysis_api(mock_client, "test prompt")

        assert result == '{"result": "test"}'
        mock_client.chat.completions.create.assert_called_once()

    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_api_uses_correct_model(self, mock_openai_class):
        """API call uses correct model and parameters."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{}'
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        _call_analysis_api(mock_client, "test prompt")

        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "deepseek-chat"
        assert call_args.kwargs["temperature"] == 0.7
        assert call_args.kwargs["max_tokens"] == 8000
        assert call_args.kwargs["response_format"] == {"type": "json_object"}

    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_includes_system_prompt(self, mock_openai_class):
        """API call includes system prompt."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{}'
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        _call_analysis_api(mock_client, "test prompt")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "bookmark analyzer" in messages[0]["content"].lower()
        assert messages[1]["role"] == "user"


class TestAnalyzeWithDeepSeek:
    """Tests for the analyze_with_deepseek function."""

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis._call_analysis_api")
    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_successful_analysis(self, mock_openai, mock_call):
        """Successful analysis returns parsed result."""
        mock_response = {
            "title": "Test Title",
            "summary": "Test summary",
            "recommendation_reason": "Because",
            "key_insights": ["insight1"],
            "tags": ["tag1", "tag2"],
            "recommendation_bucket": "test_this_week",
            "priority_score": 7.0,
            "worth_score": 8.0,
            "effort_score": 3.0,
            "relevance": 8.0,
            "practical_value": 7.0,
            "actionability": 6.0,
            "stage_fit": 7.0,
            "novelty": 5.0,
            "excitement": 6.0,
            "difficulty": 4.0,
            "time_cost": 3.0,
        }
        mock_call.return_value = json.dumps(mock_response)

        result = analyze_with_deepseek("test content", "Test Title", "https://example.com")

        assert result is not None
        assert result["title"] == "Test Title"
        assert result["priority_score"] == 7.0
        assert result["analysis_source"] == "deepseek"
        assert result["model"] == "deepseek-chat"

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis._call_analysis_api")
    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_creates_scoring_inputs(self, mock_openai, mock_call):
        """Result includes scoring_inputs structure."""
        mock_response = {
            "title": "Test",
            "actionable_this_week": True,
            "relevance": 8.0,
            "practical_value": 7.0,
            "actionability": 6.0,
            "stage_fit": 7.0,
            "novelty": 5.0,
            "excitement": 6.0,
            "difficulty": 4.0,
            "time_cost": 3.0,
        }
        mock_call.return_value = json.dumps(mock_response)

        result = analyze_with_deepseek("test content")

        assert "scoring_inputs" in result
        assert result["scoring_inputs"]["relevance"] == 8.0

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis._call_analysis_api")
    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_handles_bucket_field(self, mock_openai, mock_call):
        """Handles old 'bucket' field name."""
        mock_response = {
            "title": "Test",
            "bucket": "test_this_week",
        }
        mock_call.return_value = json.dumps(mock_response)

        result = analyze_with_deepseek("test content")

        assert result["recommendation_bucket"] == "test_this_week"

    @patch.dict("os.environ", {}, clear=True)
    def test_returns_none_without_api_key(self):
        """Returns None when API key not available."""
        result = analyze_with_deepseek("test content")
        assert result is None

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_handles_json_decode_error(self, mock_openai):
        """Handles invalid JSON response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "not valid json"
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        result = analyze_with_deepseek("test content")
        assert result is None

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_handles_authentication_error(self, mock_openai):
        """Handles authentication error."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = AuthenticationError(
            "Invalid API key", response=MagicMock(), body=None
        )
        mock_openai.return_value = mock_client

        result = analyze_with_deepseek("test content")
        assert result is None

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis._call_analysis_api")
    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_handles_api_error(self, mock_openai, mock_call):
        """Handles general API error."""
        mock_call.side_effect = Exception("API error")
        mock_openai.return_value = MagicMock()

        result = analyze_with_deepseek("test content")
        assert result is None

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis.OpenAI")
    def test_truncates_long_text(self, mock_openai):
        """Long text is truncated to fit context limits."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{}'
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        long_text = "x" * 10000
        analyze_with_deepseek(long_text)

        call_args = mock_client.chat.completions.create.call_args
        prompt = call_args.kwargs["messages"][1]["content"]
        # Check that the content portion is truncated (not the full prompt)
        assert "truncated" in prompt or len(long_text) > 8000
        assert "truncated" in prompt


class TestDeepseekAnalyzeBookmark:
    """Tests for the high-level analyze function with fallback."""

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis.analyze_with_deepseek")
    def test_returns_deepseek_result_on_success(self, mock_analyze):
        """Returns DeepSeek result when available."""
        expected = {"title": "Test", "summary": "From API"}
        mock_analyze.return_value = expected

        result = deepseek_analyze_bookmark("test content")

        assert result == expected

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis.analyze_with_deepseek")
    def test_fallback_on_none_result(self, mock_analyze):
        """Returns fallback when API returns None."""
        mock_analyze.return_value = None

        result = deepseek_analyze_bookmark("test content", "Test Title", "https://example.com")

        assert result["title"] == "Test Title"
        assert result["analysis_source"] == "deepseek_fallback"
        assert result["recommendation_bucket"] == "archive"

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis.analyze_with_deepseek")
    def test_fallback_on_exception(self, mock_analyze):
        """Returns fallback when API raises exception."""
        mock_analyze.side_effect = Exception("API failed")

        result = deepseek_analyze_bookmark("test content", "Original Title")

        assert result["title"] == "Original Title"
        assert result["analysis_source"] == "deepseek_fallback"
        assert "scoring_inputs" in result

    def test_fallback_without_api_key(self):
        """Returns fallback when no API key configured."""
        with patch.dict("os.environ", {}, clear=True):
            result = deepseek_analyze_bookmark("test content")

        assert result["analysis_source"] == "deepseek_fallback"
        assert result["priority_score"] == 3.0

    @patch.dict("os.environ", {"DEEPSEEK_API_KEY": "test-key"})
    @patch("rolloforge.deepseek_analysis.analyze_with_deepseek")
    def test_fallback_has_all_required_fields(self, mock_analyze):
        """Fallback result has all required fields."""
        mock_analyze.return_value = None

        result = deepseek_analyze_bookmark("test content")

        required_fields = [
            "title", "summary", "recommendation_reason", "key_insights",
            "recommendation_bucket", "priority_score", "worth_score", "effort_score",
            "relevance", "practical_value", "actionability", "stage_fit",
            "novelty", "excitement", "difficulty", "time_cost", "scoring_inputs",
            "analysis_source"
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"


class TestExceptionClasses:
    """Tests for custom exception classes."""

    def test_deepseek_error_is_exception(self):
        """DeepSeekError is an Exception."""
        assert issubclass(DeepSeekError, Exception)

    def test_config_error_is_deepseek_error(self):
        """DeepSeekConfigError is a DeepSeekError."""
        assert issubclass(DeepSeekConfigError, DeepSeekError)

    def test_api_error_is_deepseek_error(self):
        """DeepSeekAPIError is a DeepSeekError."""
        assert issubclass(DeepSeekAPIError, DeepSeekError)

    def test_can_raise_and_catch(self):
        """Can raise and catch custom exceptions."""
        with pytest.raises(DeepSeekError):
            raise DeepSeekConfigError("test error")

        with pytest.raises(DeepSeekConfigError):
            raise DeepSeekConfigError("test error")
