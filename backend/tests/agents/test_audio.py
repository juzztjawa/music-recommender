"""Unit tests for app.agents.audio — FR-3.2/3.4 graceful-degradation behavior.

Download and captioning are mocked here: real yt-dlp/Music Flamingo calls
need network access and a deployed captioning endpoint, so those are
exercised via live testing per SETUP.md, not in this fast unit-test path.
"""

from pathlib import Path

from app.agents import audio
from app.clients.music_flamingo import MusicFlamingoNotConfigured
from app.clients.youtube_audio import DownloadedAudio, YoutubeAudioDownloadError


async def test_analyze_input_song_success_and_cleans_up_temp_dir(monkeypatch):
    seen_dest_dir: dict[str, Path] = {}

    async def fake_download(query: str, dest_dir: Path) -> DownloadedAudio:
        seen_dest_dir["path"] = dest_dir
        assert dest_dir.exists()
        audio_file = dest_dir / "fake.mp3"
        audio_file.write_bytes(b"fake-audio")
        return DownloadedAudio(
            path=audio_file, source_url="https://youtube.com/watch?v=abc", title="Fake Song"
        )

    async def fake_caption(path: Path) -> str:
        assert path.exists()
        return "an upbeat rock track with distorted guitars"

    monkeypatch.setattr(audio, "download_audio", fake_download)
    monkeypatch.setattr(audio, "caption_audio", fake_caption)

    result = await audio.analyze_input_song("Bohemian Rhapsody Queen")

    assert result.caption == "an upbeat rock track with distorted guitars"
    assert result.source_url == "https://youtube.com/watch?v=abc"
    assert result.error is None
    assert not seen_dest_dir["path"].exists()


async def test_analyze_input_song_download_failure_degrades_gracefully(monkeypatch):
    async def fake_download(query: str, dest_dir: Path) -> DownloadedAudio:
        raise YoutubeAudioDownloadError("no results")

    monkeypatch.setattr(audio, "download_audio", fake_download)

    result = await audio.analyze_input_song("some obscure query")

    assert result.caption is None
    assert result.error is not None
    assert "download failed" in result.error


async def test_analyze_input_song_captioning_not_configured_degrades_gracefully(monkeypatch):
    async def fake_download(query: str, dest_dir: Path) -> DownloadedAudio:
        audio_file = dest_dir / "fake.mp3"
        audio_file.write_bytes(b"fake-audio")
        return DownloadedAudio(
            path=audio_file, source_url="https://youtube.com/watch?v=xyz", title="Fake"
        )

    async def fake_caption(path: Path) -> str:
        raise MusicFlamingoNotConfigured("MUSIC_FLAMINGO_ENDPOINT_URL is not set")

    monkeypatch.setattr(audio, "download_audio", fake_download)
    monkeypatch.setattr(audio, "caption_audio", fake_caption)

    result = await audio.analyze_input_song("Bohemian Rhapsody Queen")

    assert result.caption is None
    assert result.source_url == "https://youtube.com/watch?v=xyz"
    assert result.error is not None
    assert "captioning failed" in result.error
