"""Configuration management for Music Search MCP."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")


def get_spotify_config() -> dict:
    """Return Spotify API configuration from environment variables."""
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

    if not client_id or not client_secret:
        raise ValueError(
            "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set. "
            "Copy .env.example to .env and fill in your credentials.\n"
            "Create an app at https://developer.spotify.com/dashboard"
        )

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }


def get_lastfm_config() -> dict:
    """Return Last.fm API configuration from environment variables."""
    api_key = os.getenv("LASTFM_API_KEY")
    username = os.getenv("LASTFM_USERNAME")

    if not api_key or not username:
        raise ValueError(
            "LASTFM_API_KEY and LASTFM_USERNAME must be set in .env\n"
            "Create an API account at https://www.last.fm/api/account/create"
        )

    return {
        "api_key": api_key,
        "username": username,
    }
