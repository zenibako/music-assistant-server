"""Unit tests for Plex provider audiobook and podcast methods."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from music_assistant_models.errors import MediaNotFoundError

from music_assistant.providers.plex import PlexProvider

LIBRARY_TYPE_AUDIOBOOKS = "audiobooks"
LIBRARY_TYPE_MUSIC = "music"
LIBRARY_TYPE_PODCASTS = "podcasts"


def _make_provider(library_type: str = LIBRARY_TYPE_MUSIC) -> Any:
    """Create a minimal PlexProvider instance for testing."""
    mock_mass = MagicMock()
    mock_mass.cache = MagicMock()

    mock_config = MagicMock()
    mock_config.instance_id = "plex_instance_1"

    # Set up a proper dict-like values container so _get_library_type works
    mock_config_values: dict[str, Any] = {
        "library_type": library_type,
        "log_level": "INFO",
        "token": "local_auth",
    }

    class MockValue:
        """Simple wrapper for mock config values."""

        def __init__(self, val: Any) -> None:
            self.value = val

    mock_config.values = {k: MockValue(v) for k, v in mock_config_values.items()}
    mock_config.get_value = lambda key: mock_config_values.get(key)

    mock_manifest = MagicMock()
    mock_manifest.type = "music"
    mock_manifest.domain = "plex"

    provider = PlexProvider(mock_mass, mock_manifest, mock_config)
    provider._baseurl = "http://localhost:32400"
    provider._plex_server = MagicMock()
    provider._plex_library = MagicMock()
    provider._myplex_account = MagicMock()

    return provider


class FakePlexTrack:
    """Minimal PlexTrack stub for testing."""

    def __init__(  # noqa: D107
        self,
        key: str = "/library/metadata/1",
        title: str = "Track 1",
        duration: int = 1000,
        has_media: bool = True,
        has_parts: bool = True,
        parent_index: int | None = 1,
        track_number: int | None = 1,
        container: str | None = "mp3",
    ) -> None:
        self.key = key
        self.title = title
        self.duration = duration
        self.parentIndex = parent_index
        self.trackNumber = track_number
        if has_media:
            media = MagicMock()
            media.container = container
            media.parts = [MagicMock()] if has_parts else []
            self.media = [media]
        else:
            self.media = []

    def getWebURL(self, baseurl: str) -> str:  # noqa: N802, D102
        return f"{baseurl}/web/index.html#!/server/item/{self.key}"

    def firstAttr(self, *attrs: str) -> str | None:  # noqa: N802, D102
        return None


class FakePlexAlbum:
    """Minimal PlexAlbum stub for testing."""

    def __init__(  # noqa: D107
        self,
        tracks: list[Any],
        title: str = "Test Album",
        key: str = "/library/metadata/100",
    ) -> None:
        self._tracks = tracks
        self.title = title
        self.key = key
        self.summary = ""
        self.year = None
        self.studio = None
        self.parentTitle = None
        self.grandparentTitle = None

    def tracks(self) -> list[Any]:  # noqa: D102
        return self._tracks

    def getWebURL(self, baseurl: str) -> str:  # noqa: N802, D102
        return f"{baseurl}/web/index.html#!/server/item/{self.key}"

    def firstAttr(self, *attrs: str) -> str | None:  # noqa: N802, D102
        return None


class TestBuildAudiobookChapters:
    """Tests for _build_audiobook_chapters numbering behavior."""

    @pytest.mark.asyncio
    async def test_chapters_numbered_sequentially(self) -> None:
        """Chapters should have sequential positions starting from 1."""
        provider = _make_provider(LIBRARY_TYPE_AUDIOBOOKS)
        tracks = [
            FakePlexTrack(key="/1", title="Intro", duration=3000),
            FakePlexTrack(key="/2", title="Chapter 1", duration=5000),
            FakePlexTrack(key="/3", title="Outro", duration=2000),
        ]
        album = FakePlexAlbum(tracks)

        chapters = await provider._build_audiobook_chapters(album)

        assert len(chapters) == 3
        assert chapters[0].position == 1
        assert chapters[1].position == 2
        assert chapters[2].position == 3
        assert chapters[0].name == "Intro"
        assert chapters[1].name == "Chapter 1"
        assert chapters[2].name == "Outro"

    @pytest.mark.asyncio
    async def test_chapters_skip_tracks_without_media(self) -> None:
        """Tracks without media should be skipped without creating gaps in numbering."""
        provider = _make_provider(LIBRARY_TYPE_AUDIOBOOKS)
        tracks = [
            FakePlexTrack(key="/1", title="Valid Track 1", duration=3000),
            FakePlexTrack(key="/2", title="No Media", duration=5000, has_media=False),
            FakePlexTrack(key="/3", title="Valid Track 2", duration=2000),
        ]
        album = FakePlexAlbum(tracks)

        chapters = await provider._build_audiobook_chapters(album)

        assert len(chapters) == 2
        assert chapters[0].position == 1
        assert chapters[1].position == 2
        assert chapters[0].name == "Valid Track 1"
        assert chapters[1].name == "Valid Track 2"

    @pytest.mark.asyncio
    async def test_chapters_skip_tracks_without_parts(self) -> None:
        """Tracks with media but no parts should be skipped without gaps."""
        provider = _make_provider(LIBRARY_TYPE_AUDIOBOOKS)
        tracks = [
            FakePlexTrack(key="/1", title="Valid", duration=3000),
            FakePlexTrack(key="/2", title="No Parts", duration=5000, has_parts=False),
            FakePlexTrack(key="/3", title="Another Valid", duration=2000),
        ]
        album = FakePlexAlbum(tracks)

        chapters = await provider._build_audiobook_chapters(album)

        assert len(chapters) == 2
        assert chapters[0].position == 1
        assert chapters[1].position == 2

    @pytest.mark.asyncio
    async def test_chapters_cumulative_times(self) -> None:
        """Chapter start/end times should be cumulative across valid tracks."""
        provider = _make_provider(LIBRARY_TYPE_AUDIOBOOKS)
        tracks = [
            FakePlexTrack(key="/1", title="First", duration=1000),
            FakePlexTrack(key="/2", title="Second", duration=2000),
            FakePlexTrack(key="/3", title="Third", duration=3000),
        ]
        album = FakePlexAlbum(tracks)

        chapters = await provider._build_audiobook_chapters(album)

        assert chapters[0].start == 0.0
        assert chapters[0].end == 1.0
        assert chapters[1].start == 1.0
        assert chapters[1].end == 3.0
        assert chapters[2].start == 3.0
        assert chapters[2].end == 6.0


class TestBuildPodcastEpisodes:
    """Tests for _build_podcast_episodes numbering behavior."""

    @pytest.mark.asyncio
    async def test_episodes_numbered_sequentially(self) -> None:
        """Episodes should have sequential positions starting from 1."""
        provider = _make_provider(LIBRARY_TYPE_PODCASTS)
        tracks = [
            FakePlexTrack(key="/1", title="Intro"),
            FakePlexTrack(key="/2", title="Main Episode"),
            FakePlexTrack(key="/3", title="Outro"),
        ]
        album = FakePlexAlbum(tracks, title="Test Podcast")

        episodes = await provider._build_podcast_episodes(album)

        assert len(episodes) == 3
        assert episodes[0].position == 1
        assert episodes[1].position == 2
        assert episodes[2].position == 3
        assert episodes[0].name == "Intro"
        assert episodes[1].name == "Main Episode"
        assert episodes[2].name == "Outro"

    @pytest.mark.asyncio
    async def test_episodes_skip_tracks_without_media(self) -> None:
        """Tracks without media should be skipped without creating gaps."""
        provider = _make_provider(LIBRARY_TYPE_PODCASTS)
        tracks = [
            FakePlexTrack(key="/1", title="Valid Ep 1"),
            FakePlexTrack(key="/2", title="No Media", has_media=False),
            FakePlexTrack(key="/3", title="Valid Ep 2"),
        ]
        album = FakePlexAlbum(tracks, title="Test Podcast")

        episodes = await provider._build_podcast_episodes(album)

        assert len(episodes) == 2
        assert episodes[0].position == 1
        assert episodes[1].position == 2
        assert episodes[0].name == "Valid Ep 1"
        assert episodes[1].name == "Valid Ep 2"

    @pytest.mark.asyncio
    async def test_episode_default_name(self) -> None:
        """Tracks without titles should use default episode name with correct number."""
        provider = _make_provider(LIBRARY_TYPE_PODCASTS)
        tracks = [
            FakePlexTrack(key="/1", title=""),
            FakePlexTrack(key="/2", title="Has Title"),
            FakePlexTrack(key="/3", title=""),
        ]
        album = FakePlexAlbum(tracks, title="Test Podcast")

        episodes = await provider._build_podcast_episodes(album)

        assert episodes[0].name == "Episode 1"
        assert episodes[1].name == "Has Title"
        assert episodes[2].name == "Episode 3"

    @pytest.mark.asyncio
    async def test_episode_podcast_reference(self) -> None:
        """Each episode should reference the parent podcast correctly."""
        provider = _make_provider(LIBRARY_TYPE_PODCASTS)
        tracks = [
            FakePlexTrack(key="/1", title="Ep 1"),
        ]
        album = FakePlexAlbum(tracks, title="My Podcast", key="/library/metadata/100")

        episodes = await provider._build_podcast_episodes(album)

        assert len(episodes) == 1
        assert episodes[0].podcast.name == "My Podcast"
        assert episodes[0].podcast.item_id == "podcast:/library/metadata/100"


class TestStreamDetailsGuards:
    """Tests for library type guards in stream detail methods."""

    @pytest.mark.asyncio
    async def test_audiobook_stream_rejects_music_library(self) -> None:
        """_get_audiobook_stream_details should raise when library type is music."""
        provider = _make_provider(LIBRARY_TYPE_MUSIC)

        with pytest.raises(MediaNotFoundError, match="not configured for audiobooks"):
            await provider._get_audiobook_stream_details("audiobook:/library/metadata/1")

    @pytest.mark.asyncio
    async def test_audiobook_stream_rejects_podcast_library(self) -> None:
        """_get_audiobook_stream_details should raise when library type is podcasts."""
        provider = _make_provider(LIBRARY_TYPE_PODCASTS)

        with pytest.raises(MediaNotFoundError, match="not configured for audiobooks"):
            await provider._get_audiobook_stream_details("audiobook:/library/metadata/1")

    @pytest.mark.asyncio
    async def test_podcast_stream_rejects_music_library(self) -> None:
        """_get_podcast_episode_stream_details should raise when library type is music."""
        provider = _make_provider(LIBRARY_TYPE_MUSIC)

        with pytest.raises(MediaNotFoundError, match="not configured for podcasts"):
            await provider._get_podcast_episode_stream_details(
                "podcast_episode:/library/metadata/1"
            )

    @pytest.mark.asyncio
    async def test_podcast_stream_rejects_audiobook_library(self) -> None:
        """_get_podcast_episode_stream_details should raise when library type is audiobooks."""
        provider = _make_provider(LIBRARY_TYPE_AUDIOBOOKS)

        with pytest.raises(MediaNotFoundError, match="not configured for podcasts"):
            await provider._get_podcast_episode_stream_details(
                "podcast_episode:/library/metadata/1"
            )
