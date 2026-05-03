"""Several helpers/utils for the Plex Music Provider."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import requests
from plexapi.gdm import GDM
from plexapi.library import LibrarySection as PlexLibrarySection
from plexapi.library import MusicSection as PlexMusicSection
from plexapi.server import PlexServer

if TYPE_CHECKING:
    from music_assistant.mass import MusicAssistant


AUDIOBOOK_KEYWORDS = ("audiobook", "audio book", "audible", "hörbuch", "hoerbuch")


@dataclass(frozen=True)
class PlexSectionInfo:
    """Metadata about a Plex library section for config auto-detection."""

    display_name: str
    section_title: str
    server_name: str
    section_type: str
    is_likely_audiobook: bool


def _looks_like_audiobook(section: PlexLibrarySection) -> bool:
    """Heuristic: check if a music section likely contains audiobooks."""
    title_lower = section.title.lower()
    if any(keyword in title_lower for keyword in AUDIOBOOK_KEYWORDS):
        return True
    if hasattr(section, "locations") and section.locations:
        for location in section.locations:
            location_lower = location.lower()
            if any(keyword in location_lower for keyword in AUDIOBOOK_KEYWORDS):
                return True
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


async def get_libraries(
    mass: MusicAssistant,
    auth_token: str | None,
    local_server_ssl: bool,
    local_server_ip: str,
    local_server_port: str,
    local_server_verify_cert: bool,
    instance_id: str | None = None,
) -> list[str]:
    """
    Get all music libraries for all plex servers.

    Returns a list of Library names in format ['servername / library name', ...]

    :param mass: MusicAssistant instance.
    :param auth_token: Authentication token for Plex server.
    :param local_server_ssl: Whether to use SSL/HTTPS.
    :param local_server_ip: IP address of the Plex server.
    :param local_server_port: Port of the Plex server.
    :param local_server_verify_cert: Whether to verify SSL certificate.
    :param instance_id: Provider instance ID to use for cache isolation.
    """
    cache_key = "plex_libraries"

    def _get_libraries() -> list[str]:
        # create a listing of available music libraries on all servers
        all_libraries: list[str] = []
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
        for media_section in cast("list[PlexLibrarySection]", plex_server.library.sections()):
            if media_section.type != PlexMusicSection.TYPE:
                continue
            # TODO: figure out what plex uses as stable id and use that instead of names
            all_libraries.append(f"{plex_server.friendlyName} / {media_section.title}")
        return all_libraries

    if cache := await mass.cache.get(
        cache_key, checksum=auth_token, provider=instance_id or local_server_ip
    ):
        return cast("list[str]", cache)

    result = await asyncio.to_thread(_get_libraries)
    # use short expiration for in-memory cache
    await mass.cache.set(
        cache_key,
        result,
        checksum=auth_token,
        expiration=3600,
        provider=instance_id or "default",
    )
    return result


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
        if isinstance(cache, list) and cache:
            first_item = cache[0]
            if isinstance(first_item, dict):
                return [PlexSectionInfo(**item) for item in cache]
        return cast("list[PlexSectionInfo]", cache)

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
