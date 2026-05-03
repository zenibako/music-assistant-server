"""Unit tests for the Plex Music Provider audiobook helpers."""

from __future__ import annotations

from typing import Any

import pytest

from music_assistant.providers.plex.helpers import (
    AUDIOBOOK_KEYWORDS,
    PlexSectionInfo,
    _looks_like_audiobook,
    extract_library_name,
)


class TestPlexSectionInfo:
    """Tests for PlexSectionInfo dataclass."""

    def test_from_dict_kwargs_reconstruction(self) -> None:
        """PlexSectionInfo can be reconstructed from a dict via **kwargs."""
        data: dict[str, Any] = {
            "display_name": "My Server / Audiobooks",
            "section_title": "Audiobooks",
            "server_name": "My Server",
            "section_type": "artist",
            "is_likely_audiobook": True,
        }
        info = PlexSectionInfo(**data)
        assert info.display_name == "My Server / Audiobooks"
        assert info.section_title == "Audiobooks"
        assert info.is_likely_audiobook is True


class TestExtractLibraryName:
    """Tests for extract_library_name() config value parser."""

    @pytest.mark.parametrize(
        ("input_value", "expected"),
        [
            ("My Server / Music", "Music"),
            ("My Server / Audiobooks", "Audiobooks"),
            ("  My Server  /  Audiobooks  ", "Audiobooks"),
            ("Audiobooks", "Audiobooks"),
            ("  Audiobooks  ", "Audiobooks"),
        ],
    )
    def test_extract_library_name(self, input_value: str, expected: str) -> None:
        """Extract library name handles both 'server / name' and plain 'name' formats."""
        assert extract_library_name(input_value) == expected

    def test_empty_string_returns_empty(self) -> None:
        """Empty string should be returned as-is (not an error)."""
        assert extract_library_name("") == ""


class TestLooksLikeAudiobook:
    """Tests for _looks_like_audiobook() heuristic detection."""

    class FakeSection:
        """Minimal LibrarySection stub for heuristic unit tests."""

        def __init__(self, title: str, locations: list[str] | None = None) -> None:
            """Initialize fake section."""
            self.title = title
            self.locations = locations or []

    @pytest.mark.parametrize(
        "title",
        [
            "Audiobooks",
            "My Audiobooks",
            "Audio Books",
            "Audible Collection",
            "Hörbuch Sammlung",
            "Hoerbuch",
            "Mixed Audiobook Library",
        ],
    )
    def test_title_matches_audiobook_keywords(self, title: str) -> None:
        """Any title containing an audiobook keyword should trigger detection."""
        section = self.FakeSection(title)
        assert _looks_like_audiobook(section) is True

    @pytest.mark.parametrize(
        "title",
        [
            "Music",
            "Podcasts",
            "My Music",
            "Radio",
        ],
    )
    def test_non_audiobook_title(self, title: str) -> None:
        """Titles without audiobook keywords should not trigger."""
        section = self.FakeSection(title)
        assert _looks_like_audiobook(section) is False

    def test_location_path_audiobook_match(self) -> None:
        """Audiobook keyword in folder path should trigger detection."""
        section = self.FakeSection("Misc", locations=["/media/audiobooks/"])
        assert _looks_like_audiobook(section) is True

    def test_location_no_match(self) -> None:
        """Non-audiobook location should not trigger detection."""
        section = self.FakeSection("Music", locations=["/media/music/"])
        assert _looks_like_audiobook(section) is False

    def test_no_locations_attribute(self) -> None:
        """Sections without locations attribute should not raise."""
        section = self.FakeSection("Music")
        del section.locations
        assert _looks_like_audiobook(section) is False


class TestAudiobookKeywords:
    """Sanity check for AUDIOBOOK_KEYWORDS constant."""

    def test_all_lowercase(self) -> None:
        """All keywords must be lowercase for case-insensitive matching."""
        assert all(
            kw.islower() or not any(c.isupper() or c.islower() for c in kw)
            for kw in AUDIOBOOK_KEYWORDS
        )

    def test_non_empty(self) -> None:
        """At least one keyword is defined."""
        assert len(AUDIOBOOK_KEYWORDS) > 0
