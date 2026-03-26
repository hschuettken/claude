"""
Capture Utilities — OCR and voice processing helpers.

Provides utilities for:
  - Screenshot OCR text extraction (client-side → server validation)
  - Voice transcript validation and enhancement
  - Image data handling (base64, data: URLs)
  - Text cleaning and normalization
"""

import base64
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Text Processing
# ============================================================================

def clean_text(text: str) -> str:
    """
    Clean and normalize text.
    
    Args:
        text: Raw text to clean
        
    Returns:
        Cleaned text
    """
    # Remove extra whitespace
    text = " ".join(text.split())
    # Remove control characters
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    return text.strip()


def enhance_transcript(transcript: str) -> str:
    """
    Enhance voice transcript (capitalize, add punctuation hints).
    
    Args:
        transcript: Raw voice transcript
        
    Returns:
        Enhanced transcript
    """
    # Clean first
    transcript = clean_text(transcript)
    
    # Capitalize first letter
    if transcript:
        transcript = transcript[0].upper() + transcript[1:]
    
    # Add period if missing
    if transcript and not transcript.endswith((".", "!", "?")):
        transcript += "."
    
    return transcript


# ============================================================================
# Image/Screenshot Handling
# ============================================================================

def parse_data_url(data_url: str) -> tuple[str, bytes]:
    """
    Parse a data: URL into MIME type and bytes.
    
    Args:
        data_url: Data URL (e.g., data:image/png;base64,...)
        
    Returns:
        (mime_type, image_bytes)
    """
    try:
        # Format: data:[<mediatype>][;base64],<data>
        if not data_url.startswith("data:"):
            raise ValueError("Not a data URL")
        
        # Split metadata and content
        header, content = data_url.split(",", 1)
        mime_type = "image/png"  # default
        
        # Extract MIME type if present
        if ";" in header:
            mime_type = header.split(";")[0].replace("data:", "")
        elif ":" in header:
            mime_type = header.split(":")[1]
        
        # Decode base64
        image_bytes = base64.b64decode(content)
        
        return mime_type, image_bytes
    except Exception as e:
        logger.error(f"Failed to parse data URL: {e}")
        raise


def validate_image_data(
    image_data: str,
    max_size_mb: int = 5,
) -> bool:
    """
    Validate image data (size, format, etc).
    
    Args:
        image_data: Base64-encoded or data: URL image
        max_size_mb: Max size in MB
        
    Returns:
        True if valid
    """
    try:
        # Decode if needed
        if image_data.startswith("data:"):
            _, image_bytes = parse_data_url(image_data)
        else:
            image_bytes = base64.b64decode(image_data)
        
        # Check size
        size_mb = len(image_bytes) / (1024 * 1024)
        if size_mb > max_size_mb:
            logger.warning(f"Image too large: {size_mb:.1f} MB (max {max_size_mb} MB)")
            return False
        
        return True
    except Exception as e:
        logger.error(f"Image validation failed: {e}")
        return False


# ============================================================================
# OCR Processing (stub for client-side integration)
# ============================================================================

def extract_ocr_text_hint(
    ocr_output: str,
    language: str = "en",
) -> str:
    """
    Enhance/clean OCR output.
    
    In practice, OCR (Tesseract, Paddle-OCR) runs client-side or in a dedicated
    service. This function cleans the output.
    
    Args:
        ocr_output: Raw OCR text
        language: Language (hint for post-processing)
        
    Returns:
        Cleaned OCR text
    """
    # Basic cleanup: remove isolated characters, fix spacing
    lines = ocr_output.split("\n")
    cleaned_lines = []
    
    for line in lines:
        line = clean_text(line)
        if len(line) > 2:  # Skip single-char lines (likely noise)
            cleaned_lines.append(line)
    
    return "\n".join(cleaned_lines).strip()


# ============================================================================
# Voice Processing (stub for client-side integration)
# ============================================================================

def validate_voice_transcript(
    transcript: str,
    min_length: int = 3,
    max_length: int = 5000,
) -> tuple[bool, Optional[str]]:
    """
    Validate voice transcript.
    
    Args:
        transcript: Transcribed text
        min_length: Minimum length
        max_length: Maximum length
        
    Returns:
        (is_valid, error_message)
    """
    if not transcript:
        return False, "Transcript is empty"
    
    transcript = clean_text(transcript)
    
    if len(transcript) < min_length:
        return False, f"Transcript too short (min {min_length} chars)"
    
    if len(transcript) > max_length:
        return False, f"Transcript too long (max {max_length} chars)"
    
    return True, None


def detect_language(transcript: str) -> str:
    """
    Detect language of transcript (stub).
    
    Args:
        transcript: Text to detect language of
        
    Returns:
        Language code (e.g., 'en', 'de')
    """
    # TODO: Use langdetect or textblob for real language detection
    # For now, default to 'en'
    return "en"


# ============================================================================
# Integration with OCR/Voice APIs
# ============================================================================

class CaptureProcessor:
    """High-level processor for captures with multiple sources."""
    
    @staticmethod
    def process_capture(
        text: Optional[str] = None,
        voice_transcript: Optional[str] = None,
        screenshot_ocr: Optional[str] = None,
    ) -> dict:
        """
        Process capture with multiple input sources.
        
        Validates and cleans all inputs, returns processing results.
        
        Args:
            text: Direct text input
            voice_transcript: Voice-to-text transcription
            screenshot_ocr: OCR from screenshot
            
        Returns:
            {
              'combined_text': combined text from all sources,
              'sources': list of sources used,
              'quality_score': 0.0-1.0 confidence,
              'warnings': list of warnings
            }
        """
        sources = []
        warnings = []
        parts = []
        
        # Process text
        if text:
            text = clean_text(text)
            if text:
                parts.append(text)
                sources.append("text")
        
        # Process voice
        if voice_transcript:
            is_valid, error = validate_voice_transcript(voice_transcript)
            if is_valid:
                transcript = enhance_transcript(voice_transcript)
                parts.append(transcript)
                sources.append("voice")
            else:
                warnings.append(f"Voice transcript invalid: {error}")
        
        # Process OCR
        if screenshot_ocr:
            ocr_text = extract_ocr_text_hint(screenshot_ocr)
            if ocr_text:
                parts.append(ocr_text)
                sources.append("screenshot_ocr")
            else:
                warnings.append("OCR text was empty after cleaning")
        
        # Combine all parts
        combined_text = " ".join(parts)
        
        # Quality score based on sources and text length
        quality = 0.8 if text else 0.6  # Text input is more reliable
        if len(sources) > 1:
            quality += 0.1  # Bonus for multiple sources
        quality = min(quality, 1.0)
        
        return {
            "combined_text": combined_text,
            "sources": sources,
            "quality_score": quality,
            "warnings": warnings,
        }


__all__ = [
    "clean_text",
    "enhance_transcript",
    "parse_data_url",
    "validate_image_data",
    "extract_ocr_text_hint",
    "validate_voice_transcript",
    "detect_language",
    "CaptureProcessor",
]
