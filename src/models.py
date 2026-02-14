from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ZoomRecording:
    topic: str
    date: str
    duration: str
    file_size: str
    download_url: str


@dataclass
class UploadResult:
    video_id: str
    title: str

    @property
    def url(self) -> str:
        return f"https://youtu.be/{self.video_id}"
