"""Unit tests for audio.py focus prompt builder."""

from notebooklm_automation.audio import build_focus_prompt


class TestBuildFocusPrompt:
    def test_contains_primary_coverage(self):
        prompt = build_focus_prompt()
        assert "primary" in prompt.lower()

    def test_contains_secondary_coverage(self):
        prompt = build_focus_prompt()
        assert "secondary" in prompt.lower()

    def test_contains_tertiary_coverage(self):
        prompt = build_focus_prompt()
        assert "tertiary" in prompt.lower()

    def test_references_notebook_sources(self):
        prompt = build_focus_prompt()
        assert "notebook sources" in prompt.lower()

    def test_returns_string(self):
        assert isinstance(build_focus_prompt(), str)
