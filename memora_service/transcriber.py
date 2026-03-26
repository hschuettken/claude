"""
Faster-Whisper Transcriber Service.

Wraps faster-whisper library for efficient audio transcription.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Optional

try:
    from faster_whisper import WhisperModel
except ImportError:
    raise ImportError(
        "faster-whisper not installed. Install with: pip install faster-whisper"
    )

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    """Result of transcription operation."""
    text: str
    segments: list[dict]
    language: Optional[str]
    duration_seconds: Optional[float]


class TranscriberService:
    """
    Whisper transcription service using faster-whisper library.
    
    Provides efficient CPU/GPU transcription with support for:
    - Multiple model sizes (tiny, base, small, medium, large)
    - Auto language detection
    - GPU acceleration (if available)
    - Segment-level transcription
    """

    # Valid model names
    VALID_MODELS = {"tiny", "base", "small", "medium", "large"}

    def __init__(
        self,
        model_name: str = "base",
        device: str = "auto",
        compute_type: str = "default",
    ):
        """
        Initialize transcriber.
        
        Args:
            model_name: Whisper model size (tiny, base, small, medium, large)
            device: Device to use (auto, cpu, cuda). "auto" tries GPU, falls back to CPU.
            compute_type: Compute type (default, int8, float16, int8_float16, int8_float32, float32)
        """
        if model_name not in self.VALID_MODELS:
            raise ValueError(
                f"Invalid model: {model_name}. Must be one of {self.VALID_MODELS}"
            )

        self.model_name = model_name
        self.device = self._resolve_device(device)
        self.compute_type = compute_type

        logger.info(f"Loading Whisper model: {model_name}")
        self.model = WhisperModel(
            model_name,
            device=self.device,
            compute_type=self.compute_type,
            num_workers=2,
            download_root=None,  # Use default cache
        )
        logger.info(f"Model loaded successfully on device={self.device}")

    @staticmethod
    def _resolve_device(device: str) -> str:
        """Resolve device string to actual device."""
        if device == "auto":
            try:
                import torch
                return "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                return "cpu"
        return device

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio file.
        
        Args:
            audio_path: Path to audio file
            language: Optional language code (e.g., 'en', 'de'). Auto-detected if None.
        
        Returns:
            TranscriptionResult with transcription text and metadata
        
        Raises:
            Exception: If transcription fails
        """
        try:
            logger.info(f"Transcribing: {audio_path} (language={language})")

            segments, info = self.model.transcribe(
                audio_path,
                language=language,
                beam_size=5,
                best_of=5,
                condition_on_previous_text=True,
                temperature=0.0,  # Deterministic
                vad_filter=True,
                vad_parameters=dict(min_speech_duration_ms=250),
            )

            # Collect segments
            segment_list = []
            full_text_parts = []

            for segment in segments:
                seg_dict = {
                    "id": segment.id,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                }
                segment_list.append(seg_dict)
                full_text_parts.append(segment.text)

            full_text = "".join(full_text_parts).strip()

            logger.info(
                f"Transcription complete: {len(segment_list)} segments, "
                f"{len(full_text)} chars, language={info.language}"
            )

            return TranscriptionResult(
                text=full_text,
                segments=segment_list,
                language=info.language,
                duration_seconds=info.duration,
            )

        except Exception as e:
            logger.error(f"Transcription failed for {audio_path}: {e}", exc_info=True)
            raise

    def get_info(self) -> dict:
        """Get transcriber info."""
        return {
            "model": self.model_name,
            "device": self.device,
            "compute_type": self.compute_type,
        }
