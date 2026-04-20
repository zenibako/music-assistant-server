"""Tests for json helpers."""

from dataclasses import dataclass

import pytest

from music_assistant.helpers.json import json_dumps


def test_plain_dataclass_serializes() -> None:
    """Plain dataclasses must serialize without recursion errors.

    Regression for: plain dataclasses hitting orjson's recursion limit
    because OPT_PASSTHROUGH_DATACLASS delegates to the default callback,
    which previously did not handle plain dataclasses.
    """

    @dataclass(frozen=True)
    class PlexSectionInfo:
        display_name: str
        section_title: str
        server_name: str
        section_type: str
        is_likely_audiobook: bool

    data = [PlexSectionInfo("foo", "bar", "baz", "music", False)]
    result = json_dumps(data)
    assert result == '[{"display_name":"foo","section_title":"bar","server_name":"baz","section_type":"music","is_likely_audiobook":false}]'


def test_dataclass_with_lists_and_nesting() -> None:
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


def test_non_serializable_still_raises() -> None:
    """Objects that are neither dataclasses nor have to_dict must still raise."""
    with pytest.raises(TypeError):
        json_dumps(object())
