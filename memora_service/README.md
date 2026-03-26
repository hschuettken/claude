# Memora Transcription Service

Standalone microservice for real-time audio transcription using **faster-whisper**.

## Overview

The Memora Transcription Service provides HTTP endpoints for audio transcription with:
- **Faster-whisper** library for efficient CPU/GPU inference
- Multiple model sizes (tiny, base, small, medium, large)
- Auto language detection
- Segment-level transcription results
- Simple REST API

## Quick Start

### Docker Compose

```bash
cd memora_service
docker-compose up --build
```

Service will be available at `http://localhost:8071`

### Docker Run

```bash
docker build -t memora-transcription:latest .
docker run -p 8071:8071 memora-transcription:latest
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run service
python main.py
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `WHISPER_MODEL` | `base` | Model size: tiny, base, small, medium, large |
| `WHISPER_DEVICE` | `auto` | Device: auto, cpu, cuda |
| `WHISPER_COMPUTE_TYPE` | `default` | Compute type: default, int8, float16, etc. |
| `PORT` | `8071` | Server port |
| `HOST` | `0.0.0.0` | Server host |

## API Endpoints

### Health Check

```bash
curl http://localhost:8071/health
```

Response:
```json
{
  "status": "healthy",
  "service": "memora-transcription",
  "version": "1.0.0",
  "model_loaded": true
}
```

### Transcribe Audio

```bash
curl -X POST http://localhost:8071/transcribe \
  -F "file=@audio.mp3" \
  -F "language=en"
```

Parameters:
- `file` (required): Audio file (mp3, wav, flac, ogg, m4a, etc.)
- `language` (optional): Language code (e.g., 'en', 'de', 'fr'). Auto-detected if omitted.

Response:
```json
{
  "success": true,
  "text": "Hello, this is a test transcription.",
  "segments": [
    {
      "id": 0,
      "start": 0.0,
      "end": 2.5,
      "text": "Hello, this is a test transcription."
    }
  ],
  "language": "en",
  "duration_seconds": 2.5
}
```

## Features

- ✅ Fast transcription using faster-whisper
- ✅ Automatic language detection
- ✅ Multi-model support (tiny → large)
- ✅ Segment-level results
- ✅ GPU acceleration (when available)
- ✅ Health check endpoint
- ✅ Docker containerization
- ✅ OpenAPI documentation at `/docs`

## Performance

Model comparison (base model on CPU):

| Audio Length | Time | Notes |
|------------|------|-------|
| 1 minute | ~10-15s | CPU (Intel i7), base model |
| 10 minutes | ~90-120s | Typical meeting |

GPU (CUDA) speeds are 3-5x faster.

## Acceptance Criteria

- [x] FastAPI app on port 8071
- [x] faster-whisper integration with configurable models
- [x] POST /transcribe endpoint for async file upload
- [x] GET /health endpoint for health checks
- [x] Dockerfile for containerization
- [x] docker-compose.yml for service definition
- [x] Key dependencies in requirements.txt

## Testing

```bash
# Test health endpoint
curl http://localhost:8071/health

# Test transcription with sample audio
curl -X POST http://localhost:8071/transcribe \
  -F "file=@test_audio.mp3"
```

## Architecture

```
FastAPI Application (main.py)
    ↓
    ├─ /health → HealthResponse
    ├─ /transcribe → TranscribeResponse
    └─ / → Service info
    
    ↓
TranscriberService (transcriber.py)
    ↓
faster-whisper WhisperModel
    ↓
Audio Processing + Model Inference
```

## Dependencies

- FastAPI 0.109.0
- Uvicorn 0.27.0
- Pydantic 2.5.3
- faster-whisper 1.1.0
- Python 3.11+

## Notes

- Model files are cached in `$HOME/.cache/huggingface/` 
- First run downloads the selected model (~1-3GB depending on size)
- Uses VAD (Voice Activity Detection) to skip silence
- Deterministic output (temperature=0.0)

## Related

- NB9OS Memora integration
- Claude orchestrator EV/PV service
- Real-time transcription for meeting notes
