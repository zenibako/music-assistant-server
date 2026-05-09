"""Several helpers/utils for the Plex Music Provider."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import requests
from plexapi.gdm import GDM
from plexapi.library import LibrarySection as PlexLibrarySection
from plexapi.library import MusicSection as PlexMusicSection
from plexapi.server import PlexServer

if TYPE_CHECKING:
    from music_assistant.mass import MusicAssistant

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlexSectionInfo:
    """Metadata about a Plex library section for config auto-detection."""

    display_name: str
    section_title: str
    server_name: str
    section_type: str
    is_likely_audiobook: bool


def _looks_like_audiobook(section: PlexLibrarySection) -> bool:
    """Check if a music section likely contains audiobooks.

    Uses the ``enableTrackOffsets`` library preference ("Store track progress"
    advanced setting). When enabled, Plex treats tracks as resumable content,
    which is characteristic of audiobook libraries.
    """
    try:
        settings = section.settings()
        section_title = getattr(section, "title", "<unknown>")
        LOGGER.debug(
            "Library '%s' settings: %r",
            section_title,
            [{"id": s.id, "value": s.value, "type": getattr(s, "type", "?")} for s in settings],
        )
        for setting in settings:
            if setting.id == "enableTrackOffsets":
                # Plex may return the value as a bool or string.
                val = setting.value
                is_enabled = val is True or (isinstance(val, str) and val.lower() in ("true", "1"))
                if is_enabled:
                    LOGGER.debug(
                        "Library '%s' flagged as audiobook (enableTrackOffsets=%s)",
                        section_title,
                        val,
                    )
                    return True
        LOGGER.debug(
            "Library '%s' not flagged as audiobook (enableTrackOffsets absent or disabled)",
            section_title,
        )
    except Exception as err:
        LOGGER.warning(
            "Failed to read library settings for '%s': %s",
            getattr(section, "title", "<unknown>"),
            err,
        )
    return False


def extract_library_name(conf_value: str) -> str:
    """Extract the library name from a config value that may include server name.

    Config values from get_config_entries include the server prefix:
    '<server name> / <library name>'. When typed manually by the user,
    the value may just be '<library name>'.

    :param conf_value: The raw config value for a library setting.
    :return: The library name (without server prefix if present).
    """
    if " / " in conf_value:
        return conf_value.split(" / ", 1)[1].strip()
    return conf_value.strip()


async def get_section_info(
    mass: MusicAssistant,
    auth_token: str | None,
    local_server_ssl: bool,
    local_server_ip: str,
    local_server_port: str,
    local_server_verify_cert: bool,
    instance_id: str | None = None,
) -> list[PlexSectionInfo]:
    """
    Get metadata for all music library sections on the Plex server.

    Returns PlexSectionInfo objects including auto-detection hints for audiobooks.

    :param mass: MusicAssistant instance.
    :param auth_token: Authentication token for Plex server.
    :param local_server_ssl: Whether to use SSL/HTTPS.
    :param local_server_ip: IP address of the Plex server.
    :param local_server_port: Port of the Plex server.
    :param local_server_verify_cert: Whether to verify SSL certificate.
    :param instance_id: Provider instance ID to use for cache isolation.
    """
    cache_key = "plex_section_info"

    def _get_section_info() -> list[PlexSectionInfo]:
        session = requests.Session()
        session.verify = local_server_verify_cert
        local_server_protocol = "https" if local_server_ssl else "http"
        plex_server: PlexServer
        if auth_token is None:
            plex_server = PlexServer(
                f"{local_server_protocol}://{local_server_ip}:{local_server_port}"
            )
        else:
            plex_server = PlexServer(
                f"{local_server_protocol}://{local_server_ip}:{local_server_port}",
                auth_token,
                session=session,
            )
        results: list[PlexSectionInfo] = []
        for media_section in cast("list[PlexLibrarySection]", plex_server.library.sections()):
            if media_section.type != PlexMusicSection.TYPE:
                continue
            results.append(
                PlexSectionInfo(
                    display_name=f"{plex_server.friendlyName} / {media_section.title}",
                    section_title=media_section.title,
                    server_name=plex_server.friendlyName,
                    section_type=media_section.type,
                    is_likely_audiobook=_looks_like_audiobook(media_section),
                )
            )
        return results

    if cache := await mass.cache.get(
        cache_key, checksum=auth_token, provider=instance_id or local_server_ip
    ):
        if isinstance(cache, list) and cache and all(isinstance(item, dict) for item in cache):
            return [PlexSectionInfo(**item) for item in cache]
        # Treat non-list or corrupt cache as a miss.
        return []

    result = await asyncio.to_thread(_get_section_info)
    await mass.cache.set(
        cache_key,
        result,
        checksum=auth_token,
        expiration=3600,
        provider=instance_id or local_server_ip,
    )
    return result


async def discover_local_servers() -> tuple[str, int] | tuple[None, None]:
    """Discover all local plex servers on the network."""

    def _discover_local_servers() -> tuple[str, int] | tuple[None, None]:
        gdm = GDM()
        gdm.scan()
        if len(gdm.entries) > 0:
            entry = gdm.entries[0]
            data = entry.get("data")
            local_server_ip = entry.get("from")[0]
            local_server_port = data.get("Port")
            return local_server_ip, local_server_port
        return None, None

    return await asyncio.to_thread(_discover_local_servers)
