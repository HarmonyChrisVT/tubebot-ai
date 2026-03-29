"""TubeBot AI - Configuration"""
import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class OpenAIConfig:
    api_key: str = ""
    model: str = "gpt-4"
    image_model: str = "dall-e-3"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass
class YouTubeConfig:
    # OAuth2 credentials JSON (as string or file path)
    credentials_json: str = ""
    channel_id: str = ""
    # Default upload schedule: hours ahead to schedule
    schedule_hours_ahead: int = 24

    @property
    def is_configured(self) -> bool:
        return bool(self.credentials_json)


@dataclass
class PictoryConfig:
    api_key: str = ""
    api_base: str = "https://api.pictory.ai/pictoryapis/v1"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass
class TrendConfig:
    niches: List[str] = field(default_factory=lambda: [
        "Medicare benefits",
        "senior health tips",
        "retirement planning",
        "Social Security",
        "Medicare Advantage",
        "senior fitness",
        "Medicare Part D",
        "aging in place",
    ])
    scan_interval_hours: int = 24
    min_trend_score: float = 0.3


@dataclass
class VideoConfig:
    # edge-tts voice
    tts_voice: str = "en-US-JennyNeural"
    # Target script length in words (~130 wpm → 8-10 min = 1040-1300 words)
    script_min_words: int = 1100
    script_max_words: int = 1400
    # Output directories (relative to /app/data)
    audio_dir: str = "/app/data/audio"
    video_dir: str = "/app/data/videos"
    thumbnail_dir: str = "/app/data/thumbnails"
    script_dir: str = "/app/data/scripts"


@dataclass
class AppConfig:
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    pictory: PictoryConfig = field(default_factory=PictoryConfig)
    trend: TrendConfig = field(default_factory=TrendConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    database_path: str = "/app/data/tubebot.db"


config = AppConfig()


def load_config_from_env():
    config.openai.api_key = os.getenv("OPENAI_API_KEY", "")
    config.openai.model = os.getenv("OPENAI_MODEL", "gpt-4")

    config.youtube.credentials_json = os.getenv("YOUTUBE_CREDENTIALS_JSON", "")
    config.youtube.channel_id = os.getenv("YOUTUBE_CHANNEL_ID", "")
    config.youtube.schedule_hours_ahead = int(os.getenv("YOUTUBE_SCHEDULE_HOURS", "24"))

    config.pictory.api_key = os.getenv("PICTORY_API_KEY", "")

    config.database_path = os.getenv("DATABASE_PATH", config.database_path)

    niches_env = os.getenv("TREND_NICHES", "")
    if niches_env:
        config.trend.niches = [n.strip() for n in niches_env.split(",")]
