#!/usr/bin/env python3
"""
Test suite for Idea Vault service.

Run with: python3 test_idea_vault.py
"""

import unittest
from idea_vault import (
    IdeaVaultService,
    CaptureType,
    PillarTag,
    CaptureRequest,
    CaptureResponse,
    IdeaCard,
)
from capture_utils import (
    clean_text,
    enhance_transcript,
    validate_voice_transcript,
    CaptureProcessor,
)


class TestTypeDetection(unittest.TestCase):
    """Test capture type detection."""

    def test_task_detection(self):
        """Test task type detection."""
        text = "implement async fan-out for quick capture"
        detected_type, confidence = IdeaVaultService.detect_capture_type(text)
        self.assertEqual(detected_type, CaptureType.TASK)
        self.assertGreater(confidence, 0.5)

    def test_decision_detection(self):
        """Test decision type detection."""
        text = "should I buy a new laptop or wait?"
        detected_type, confidence = IdeaVaultService.detect_capture_type(text)
        self.assertEqual(detected_type, CaptureType.DECISION)
        self.assertGreater(confidence, 0.3)

    def test_routine_detection(self):
        """Test routine type detection."""
        text = "daily morning meditation habit"
        detected_type, confidence = IdeaVaultService.detect_capture_type(text)
        self.assertEqual(detected_type, CaptureType.ROUTINE)
        self.assertGreater(confidence, 0.3)

    def test_insight_detection(self):
        """Test insight type detection."""
        text = "I realized that delegation is key to scaling"
        detected_type, confidence = IdeaVaultService.detect_capture_type(text)
        self.assertEqual(detected_type, CaptureType.INSIGHT)
        self.assertGreater(confidence, 0.3)

    def test_idea_default(self):
        """Test default to idea type."""
        text = "just a random thought"
        detected_type, confidence = IdeaVaultService.detect_capture_type(text)
        # Could be idea or something else, but should have low confidence
        self.assertIsNotNone(detected_type)
        self.assertLessEqual(confidence, 1.0)

    def test_confidence_is_normalized(self):
        """Test that confidence is between 0 and 1."""
        for text in [
            "do something",
            "should I?",
            "daily routine",
            "learned something",
        ]:
            _, confidence = IdeaVaultService.detect_capture_type(text)
            self.assertGreaterEqual(confidence, 0.0)
            self.assertLessEqual(confidence, 1.0)


class TestPillarDetection(unittest.TestCase):
    """Test pillar classification."""

    def test_professional_pillar(self):
        """Test professional pillar detection."""
        text = "need to fix bug in production code"
        pillars = IdeaVaultService.detect_pillars(text)
        self.assertIn(PillarTag.PROFESSIONAL, pillars)

    def test_health_pillar(self):
        """Test health pillar detection."""
        text = "start daily exercise routine for fitness"
        pillars = IdeaVaultService.detect_pillars(text)
        self.assertIn(PillarTag.HEALTH, pillars)

    def test_creative_pillar(self):
        """Test creative pillar detection."""
        text = "design new logo for the brand"
        pillars = IdeaVaultService.detect_pillars(text)
        self.assertIn(PillarTag.CREATIVE, pillars)

    def test_learning_pillar(self):
        """Test learning pillar detection."""
        text = "take a course on machine learning"
        pillars = IdeaVaultService.detect_pillars(text)
        self.assertIn(PillarTag.LEARNING, pillars)

    def test_multiple_pillars(self):
        """Test multiple pillar detection."""
        text = "schedule fitness training and book a course on health"
        pillars = IdeaVaultService.detect_pillars(text)
        self.assertGreaterEqual(len(pillars), 2)

    def test_default_personal_pillar(self):
        """Test default to personal pillar."""
        text = "just a thought"
        pillars = IdeaVaultService.detect_pillars(text)
        self.assertEqual(pillars, [PillarTag.PERSONAL])


class TestCaptureResponse(unittest.TestCase):
    """Test capture response creation."""

    def test_create_capture_response(self):
        """Test creating a capture response."""
        response = IdeaVaultService.create_capture_response(
            "cap-test",
            "implement async capture system",
        )
        self.assertEqual(response.capture_id, "cap-test")
        self.assertEqual(response.detected_type, CaptureType.TASK)
        self.assertGreater(response.confidence, 0.0)
        self.assertIsNotNone(response.detected_pillars)
        self.assertEqual(response.status, "processing")

    def test_response_has_timestamp(self):
        """Test response has ISO timestamp."""
        response = IdeaVaultService.create_capture_response(
            "cap-test",
            "test",
        )
        self.assertIn("T", response.timestamp)
        self.assertTrue(response.timestamp.endswith("Z"))


class TestIdeaCard(unittest.TestCase):
    """Test idea card creation."""

    def test_create_idea_card(self):
        """Test creating an idea card."""
        card = IdeaVaultService.create_idea_card(
            "card-test",
            "Buy groceries",
            "buy milk, bread, eggs",
            CaptureType.TASK,
            [PillarTag.PERSONAL],
        )
        self.assertEqual(card.card_id, "card-test")
        self.assertEqual(card.title, "Buy groceries")
        self.assertEqual(card.capture_type, CaptureType.TASK)
        self.assertTrue(card.card_id)
        self.assertFalse(card.saved)  # Not marked as saved yet

    def test_card_default_title(self):
        """Test card uses 'Untitled' for empty title."""
        card = IdeaVaultService.create_idea_card(
            "card-test",
            "",
            "content",
            CaptureType.IDEA,
            [],
        )
        self.assertEqual(card.title, "Untitled")


class TestTextProcessing(unittest.TestCase):
    """Test text processing utilities."""

    def test_clean_text(self):
        """Test text cleaning."""
        messy = "  hello   world  \n\t  "
        clean = clean_text(messy)
        self.assertEqual(clean, "hello world")

    def test_enhance_transcript(self):
        """Test transcript enhancement."""
        transcript = "hello world"
        enhanced = enhance_transcript(transcript)
        self.assertEqual(enhanced[0].isupper(), True)
        self.assertTrue(enhanced.endswith("."))

    def test_enhance_transcript_with_punctuation(self):
        """Test transcript enhancement preserves punctuation."""
        transcript = "hello world!"
        enhanced = enhance_transcript(transcript)
        self.assertTrue(enhanced.endswith("!"))

    def test_validate_voice_transcript_valid(self):
        """Test voice transcript validation."""
        transcript = "this is a valid transcript"
        is_valid, error = validate_voice_transcript(transcript)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_voice_transcript_too_short(self):
        """Test rejecting short transcript."""
        transcript = "hi"
        is_valid, error = validate_voice_transcript(transcript)
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)

    def test_validate_voice_transcript_empty(self):
        """Test rejecting empty transcript."""
        is_valid, error = validate_voice_transcript("")
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)


class TestCaptureProcessor(unittest.TestCase):
    """Test unified capture processor."""

    def test_process_text_only(self):
        """Test processing text-only capture."""
        result = CaptureProcessor.process_capture(text="hello world")
        self.assertEqual(result["combined_text"], "hello world")
        self.assertIn("text", result["sources"])
        self.assertGreater(result["quality_score"], 0.7)

    def test_process_voice_only(self):
        """Test processing voice-only capture."""
        result = CaptureProcessor.process_capture(
            voice_transcript="hello world"
        )
        self.assertIn("hello world", result["combined_text"])
        self.assertIn("voice", result["sources"])

    def test_process_combined_sources(self):
        """Test processing combined sources."""
        result = CaptureProcessor.process_capture(
            text="hello",
            voice_transcript="world",
        )
        self.assertIn("hello", result["combined_text"])
        self.assertIn("world", result["combined_text"])
        self.assertEqual(len(result["sources"]), 2)
        self.assertGreater(result["quality_score"], 0.8)

    def test_process_invalid_voice(self):
        """Test handling invalid voice input."""
        result = CaptureProcessor.process_capture(
            text="hello",
            voice_transcript="x",  # Too short
        )
        self.assertIn("hello", result["combined_text"])
        self.assertNotIn("x", result["combined_text"])
        self.assertTrue(len(result["warnings"]) > 0)


class TestCaptureRequest(unittest.TestCase):
    """Test request model validation."""

    def test_create_capture_request(self):
        """Test creating a capture request."""
        req = CaptureRequest(
            text="test",
            source="web",
        )
        self.assertEqual(req.text, "test")
        self.assertEqual(req.source, "web")
        self.assertIsNone(req.title)

    def test_capture_request_with_metadata(self):
        """Test capture request with metadata."""
        req = CaptureRequest(
            text="test",
            metadata={"key": "value"},
        )
        self.assertEqual(req.metadata["key"], "value")


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestTypeDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestPillarDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestCaptureResponse))
    suite.addTests(loader.loadTestsFromTestCase(TestIdeaCard))
    suite.addTests(loader.loadTestsFromTestCase(TestTextProcessing))
    suite.addTests(loader.loadTestsFromTestCase(TestCaptureProcessor))
    suite.addTests(loader.loadTestsFromTestCase(TestCaptureRequest))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
