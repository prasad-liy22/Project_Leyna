"""Tests for the built-in persona (``app/prompts.py``).

These are content checks rather than behaviour checks: they guard against the
prompt being accidentally truncated or emptied, and against the settings
drifting away from it.
"""

from app.config import Settings
from app.prompts import DEFAULT_SYSTEM_PROMPT

#: Sections the persona is expected to keep. Update this list when the prompt is
#: deliberately restructured.
SECTIONS = (
    "IDENTITY",
    "LANGUAGE AND COMMUNICATION",
    "PERSONALITY",
    "CONVERSATIONAL STYLE",
    "ASSISTANT RESPONSIBILITIES",
    "EDUCATIONAL BEHAVIOR",
    "ACTIONS AND TOOLS",
    "MEMORY AND PERSONALIZATION",
    "RESPONSE QUALITY",
    "CORE IDENTITY",
)


def test_settings_default_to_the_persona() -> None:
    assert Settings.model_fields["system_prompt"].default == DEFAULT_SYSTEM_PROMPT


def test_persona_keeps_its_sections() -> None:
    for section in SECTIONS:
        assert f"# {section}" in DEFAULT_SYSTEM_PROMPT


def test_persona_names_leyan_and_her_languages() -> None:
    assert "Nimna" in DEFAULT_SYSTEM_PROMPT
    assert "Sinhala" in DEFAULT_SYSTEM_PROMPT
    assert "Singlish" in DEFAULT_SYSTEM_PROMPT


def test_persona_is_utf8_with_sinhala_text() -> None:
    encoded = DEFAULT_SYSTEM_PROMPT.encode("utf-8")
    assert encoded.decode("utf-8") == DEFAULT_SYSTEM_PROMPT
    # At least one character from the Sinhala Unicode block (U+0D80–U+0DFF).
    assert any("\u0d80" <= char <= "\u0dff" for char in DEFAULT_SYSTEM_PROMPT)


def test_persona_guards_against_pretending() -> None:
    lowered = DEFAULT_SYSTEM_PROMPT.lower()
    assert "not a human" in lowered
    assert "unless a tool actually did it" in lowered


def test_persona_stays_compact() -> None:
    # It is prepended to every request, so keep an eye on accidental growth.
    assert len(DEFAULT_SYSTEM_PROMPT) < 12_000
