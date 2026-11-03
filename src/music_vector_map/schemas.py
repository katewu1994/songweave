"""Shared identifiers and invariants for SongWeave v1.2.

See docs/DATA_CONTRACTS.md for the meaning of each field.
"""

from __future__ import annotations

MANIFEST_SCHEMA = "songweave.manifest.v1"
EXPORT_SCHEMA = "songweave.export.v1.2"
INTERPRETATIONS_SCHEMA = "songweave.interpretations.v1.2"

AUDIO_VIEWS = ("overall_peav", "melody_merit", "rhythm_merit", "timbre_merit")
LYRICS_VIEWS = ("lyrics_sonar",)
PRIMARY_VIEWS = AUDIO_VIEWS + LYRICS_VIEWS

# Which embedding space each view lives in. Views are never compared across spaces.
VIEW_SPACE = {
    "overall_peav": "peav_audio",
    "melody_merit": "merit_melody",
    "rhythm_merit": "merit_rhythm",
    "timbre_merit": "merit_timbre",
    "lyrics_sonar": "sonar_text",
}

VIEW_LABELS_ZH = {
    "overall_peav": "整体声音",
    "melody_merit": "旋律",
    "rhythm_merit": "节奏",
    "timbre_merit": "音色",
    "lyrics_sonar": "歌词语义",
}

MERIT_HEADS = {"melody_merit": "head_mel", "rhythm_merit": "head_rhy", "timbre_merit": "head_tim"}

LYRICS_STATUSES = (
    "available",
    "not_provided",
    "instrumental_confirmed",
    "no_lyrics_confirmed",
    "unverified_transcript",
    "error",
)
# Only verified text is embedded. An unverified transcript is kept but excluded from the view.
LYRICS_EMBEDDABLE = ("available",)

COVERAGE_FULL = "full"
COVERAGE_PARTIAL = "partial"
COVERAGE_MISSING = "missing"
COVERAGE_NOT_APPLICABLE = "not_applicable"

AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".m4a")

REVIEW_STATUSES = ("unreviewed", "approved", "rejected")
