"""Audio analysis result model."""

from pydantic import BaseModel


class AudioAnalysisResult(BaseModel):
    query: str
    caption: str | None = None
    source_url: str | None = None
    error: str | None = None
