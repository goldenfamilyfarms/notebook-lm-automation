"""Unit tests for reports.py prompt builder."""

import pytest

from notebooklm_automation.reports import STANDARD_FORMATS, build_custom_prompt


class TestStandardFormats:
    def test_matches_config(self):
        assert STANDARD_FORMATS == ["Briefing Doc", "Study Guide", "Blog Post"]


class TestBuildCustomPrompt:
    def test_contains_casual_language_instruction(self):
        prompt = build_custom_prompt("Briefing Doc")
        assert "casual" in prompt.lower()
        assert "simple language" in prompt.lower()

    def test_contains_jargon_avoidance_with_exception(self):
        prompt = build_custom_prompt("Study Guide")
        assert "avoid" in prompt.lower()
        assert "jargon" in prompt.lower()
        assert "meaning" in prompt.lower() or "definition" in prompt.lower()

    def test_contains_concept_coverage(self):
        prompt = build_custom_prompt("Blog Post")
        assert "primary" in prompt.lower()
        assert "secondary" in prompt.lower()
        assert "tertiary" in prompt.lower()

    def test_includes_report_type(self):
        prompt = build_custom_prompt("Briefing Doc")
        assert "Briefing Doc" in prompt

    def test_works_with_suggested_format(self):
        prompt = build_custom_prompt("Architectural Strategy Roadmap")
        assert "Architectural Strategy Roadmap" in prompt
        assert "casual" in prompt.lower()
        assert "primary" in prompt.lower()

    def test_returns_string(self):
        assert isinstance(build_custom_prompt("Study Guide"), str)
