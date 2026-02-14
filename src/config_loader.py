from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class YouTubeConfig:
    playlist_name: str = ""
    thumbnail_file: str = ""


@dataclass
class DefaultsConfig:
    title_format: str = "Kubernetes SIG Windows {date}"
    description: str = "Kubernetes SIG Windows weekly meeting recording."
    privacy_status: str = "public"
    made_for_kids: bool = False


@dataclass
class AppConfig:
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)


def load_config(path: str = "config.yaml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        print(
            f"Config file '{path}' not found.\n"
            "Copy config.example.yaml to config.yaml and fill in your settings."
        )
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        print(f"Invalid config file: {path}")
        sys.exit(1)

    youtube_raw = raw.get("youtube", {})
    defaults_raw = raw.get("defaults", {})

    return AppConfig(
        youtube=YouTubeConfig(
            playlist_name=youtube_raw.get("playlist_name", ""),
            thumbnail_file=youtube_raw.get("thumbnail_file", ""),
        ),
        defaults=DefaultsConfig(
            title_format=defaults_raw.get(
                "title_format", "Kubernetes SIG Windows {date}"
            ),
            description=defaults_raw.get(
                "description",
                "Kubernetes SIG Windows weekly meeting recording.",
            ),
            privacy_status=defaults_raw.get("privacy_status", "public"),
            made_for_kids=defaults_raw.get("made_for_kids", False),
        ),
    )
