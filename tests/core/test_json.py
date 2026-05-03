"""Tests for json helpers."""

from dataclasses import dataclass, field

import pytest

from music_assistant.helpers.json import get_serializable_value, json_dumps


class TestDataclassSerialization:
    """Regression tests for dataclass serialization via get_serializable_value."""

    def test_plain_dataclass_serializes(self) -> None:
        """Plain dataclasses must serialize without recursion errors."""

        @dataclass(frozen=True)
        class PlexSectionInfo:
            display_name: str
            section_title: str
            server_name: str
            section_type: str
            is_likely_audiobook: bool

        data = [PlexSectionInfo("foo", "bar", "baz", "music", False)]
        result = json_dumps(data)
        assert (
            result
            == '[{"display_name":"foo","section_title":"bar","server_name":"baz","section_type":"music","is_likely_audiobook":false}]'
        )

    def test_dataclass_with_lists_and_nesting(self) -> None:
        """Nested plain dataclasses and iterables must serialize correctly."""

        @dataclass
        class Inner:
            x: int

        @dataclass
        class Outer:
            inner: Inner
            tags: list[str]

        data = Outer(inner=Inner(42), tags=["a", "b"])
        result = json_dumps(data)
        assert result == '{"inner":{"x":42},"tags":["a","b"]}'

    def test_dataclass_with_to_dict_preferred(self) -> None:
        """Dataclasses that also have to_dict() must use to_dict, not asdict."""
        from music_assistant_models.media_items import Audiobook
        from music_assistant_models.media_items import ProviderMapping
        from music_assistant_models.unique_list import UniqueList

        audiobook = Audiobook(
            item_id="audiobook:123",
            provider="plex",
            name="Test Book",
            provider_mappings={
                ProviderMapping(
                    item_id="audiobook:123",
                    provider_domain="plex",
                    provider_instance="plex_instance",
                )
            },
            authors=UniqueList(["Author One"]),
        )
        result = json_dumps(audiobook)
        assert '"item_id":"audiobook:123"' in result
        assert '"name":"Test Book"' in result

    def test_plain_dataclass_with_uniquelist_of_strings(self) -> None:
        """asdict on plain dataclass with UniqueList[str] works (strings are hashable)."""
        from music_assistant_models.unique_list import UniqueList

        @dataclass
        class Container:
            items: UniqueList[str] = field(default_factory=UniqueList)

        data = Container(items=UniqueList(["a", "b", "c"]))
        result = json_dumps(data)
        assert result == '{"items":["a","b","c"]}'

    def test_nested_dataclass_mixed_to_dict(self) -> None:
        """Outer plain dataclass wrapping inner mashumaro dataclass."""
        from music_assistant_models.media_items import Audiobook
        from music_assistant_models.media_items import ProviderMapping
        from music_assistant_models.unique_list import UniqueList

        @dataclass
        class Wrapper:
            book: Audiobook
            count: int

        wrapper = Wrapper(
            book=Audiobook(
                item_id="audiobook:456",
                provider="plex",
                name="Wrapped Book",
                provider_mappings={
                    ProviderMapping(
                        item_id="audiobook:456",
                        provider_domain="plex",
                        provider_instance="plex_instance",
                    )
                },
                authors=UniqueList(["Author"]),
            ),
            count=1,
        )
        result = json_dumps(wrapper)
        assert '"count":1' in result
        assert '"item_id":"audiobook:456"' in result


class TestGetSerializableValue:
    """Unit tests for get_serializable_value edge cases."""

    def test_to_dict_takes_precedence_over_asdict(self) -> None:
        """If both dataclass and to_dict, to_dict must win."""
        from music_assistant_models.media_items import Audiobook
        from music_assistant_models.media_items import ProviderMapping
        from music_assistant_models.unique_list import UniqueList

        audiobook = Audiobook(
            item_id="test",
            provider="plex",
            name="Book",
            provider_mappings={
                ProviderMapping(
                    item_id="test",
                    provider_domain="plex",
                    provider_instance="plex_instance",
                )
            },
            authors=UniqueList(["A"]),
        )
        result = get_serializable_value(audiobook)
        assert isinstance(result, dict)
        assert result["item_id"] == "test"

    def test_plain_dataclass_without_to_dict_uses_asdict(self) -> None:
        """Plain dataclass falls back to asdict."""

        @dataclass(frozen=True)
        class Point:
            x: int
            y: int

        result = get_serializable_value(Point(1, 2))
        assert result == {"x": 1, "y": 2}

    def test_collection_of_dataclasses_with_to_dict(self) -> None:
        """Lists containing mashumaro dataclasses must serialize."""
        from music_assistant_models.media_items import Audiobook
        from music_assistant_models.media_items import ProviderMapping
        from music_assistant_models.unique_list import UniqueList

        books = [
            Audiobook(
                item_id=f"audiobook:{i}",
                provider="plex",
                name=f"Book {i}",
                provider_mappings={
                    ProviderMapping(
                        item_id=f"audiobook:{i}",
                        provider_domain="plex",
                        provider_instance="plex_instance",
                    )
                },
                authors=UniqueList([f"Author {i}"]),
            )
            for i in range(3)
        ]
        result = json_dumps(books)
        assert '"item_id":"audiobook:0"' in result
        assert '"item_id":"audiobook:2"' in result

    def test_non_serializable_raises(self) -> None:
        """Objects that are neither dataclasses nor have to_dict must raise."""
        with pytest.raises(TypeError):
            json_dumps(object())


class TestEdgeCases:
    """Regression tests for specific crash scenarios."""

    def test_empty_audiobook_serializes(self) -> None:
        """Audiobook with minimal fields must serialize."""
        from music_assistant_models.media_items import Audiobook
        from music_assistant_models.media_items import ProviderMapping
        from music_assistant_models.unique_list import UniqueList

        book = Audiobook(
            item_id="audiobook:minimal",
            provider="plex",
            name="Minimal",
            provider_mappings={
                ProviderMapping(
                    item_id="audiobook:minimal",
                    provider_domain="plex",
                    provider_instance="plex_instance",
                )
            },
        )
        result = json_dumps(book)
        assert '"item_id":"audiobook:minimal"' in result
        assert '"name":"Minimal"' in result


class TestJsonDumpsCachingRegression:
    """Regression: cached dataclass objects must serialize without crashing."""

    def test_cached_audiobook_list_serializes(self) -> None:
        """Simulate cache.set with list of Audiobooks (the real crash scenario)."""
        from music_assistant_models.media_items import Audiobook
        from music_assistant_models.media_items import ProviderMapping
        from music_assistant_models.unique_list import UniqueList

        books = [
            Audiobook(
                item_id="audiobook:cached",
                provider="plex",
                name="Cached Book",
                provider_mappings={
                    ProviderMapping(
                        item_id="audiobook:cached",
                        provider_domain="plex",
                        provider_instance="plex_instance",
                    )
                },
                authors=UniqueList(["Author"]),
                narrators=UniqueList(["Narrator"]),
                duration=3600,
            )
        ]
        # This mimics what cache.controller does before writing to cache
        result = json_dumps(books)
        assert "Cached Book" in result
        assert "3600" in result
