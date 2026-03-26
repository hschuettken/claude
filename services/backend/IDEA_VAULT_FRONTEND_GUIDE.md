# Idea Vault Frontend Integration Guide

## Overview

The Idea Vault provides a **unified quick capture interface** for ideas, tasks, decisions, and routines. This guide shows how to integrate the frontend with the backend API.

---

## Quick Capture Widget (React/TypeScript)

### Basic Structure

```tsx
// QuickCaptureWidget.tsx
import React, { useState } from 'react'
import { api } from './api'

interface CaptureRequest {
  text: string
  title?: string
  source: 'web' | 'voice' | 'screenshot'
  voice_transcript?: string
  screenshot_ocr?: string
  current_url?: string
  current_project_id?: string
}

export function QuickCaptureWidget() {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<'note' | 'task' | 'voice'>('note')
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [captureId, setCaptureId] = useState<string | null>(null)
  const [status, setStatus] = useState('')

  // Keyboard shortcut: press 'q'
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'q' && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
        const target = e.target as HTMLElement
        if (target.tagName !== 'INPUT' && target.tagName !== 'TEXTAREA') {
          e.preventDefault()
          setOpen(v => !v)
        }
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const handleSubmit = async () => {
    if (!input.trim()) return
    
    setLoading(true)
    try {
      const req: CaptureRequest = {
        text: input.trim(),
        source: mode === 'voice' ? 'voice' : 'web',
        current_url: window.location.pathname,
      }

      const res = await api.post('/api/v1/capture', req)
      setCaptureId(res.data.capture_id)
      setStatus(`Captured as ${res.data.detected_type}`)
      
      // Auto-save to vault after a moment
      setTimeout(async () => {
        await api.post(`/api/v1/capture/${res.data.capture_id}/save`, {
          title: input.split('\n')[0].substring(0, 60),
        })
        setOpen(false)
        setInput('')
      }, 1000)
    } catch (error) {
      setStatus('Error: ' + error.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      {/* Floating Button */}
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          position: 'fixed',
          bottom: '2rem',
          right: '2rem',
          width: '56px',
          height: '56px',
          borderRadius: '50%',
          background: '#007bff',
          color: 'white',
          border: 'none',
          cursor: 'pointer',
          fontSize: '24px',
          zIndex: 1000,
        }}
      >
        💡
      </button>

      {/* Expanded Widget */}
      {open && (
        <div style={{
          position: 'fixed',
          bottom: '120px',
          right: '2rem',
          width: '400px',
          background: 'white',
          borderRadius: '8px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          padding: '1.5rem',
          zIndex: 999,
        }}>
          <h3>💡 Quick Capture</h3>
          
          {/* Mode Tabs */}
          <div style={{ marginBottom: '1rem', display: 'flex', gap: '0.5rem' }}>
            {['note', 'task', 'voice'].map(m => (
              <button
                key={m}
                onClick={() => setMode(m as any)}
                style={{
                  padding: '0.5rem 1rem',
                  background: mode === m ? '#007bff' : '#e9ecef',
                  color: mode === m ? 'white' : 'black',
                  border: 'none',
                  borderRadius: '4px',
                  cursor: 'pointer',
                }}
              >
                {m === 'note' && '📝'}
                {m === 'task' && '✅'}
                {m === 'voice' && '🎤'}
              </button>
            ))}
          </div>

          {/* Input */}
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Type or speak your idea..."
            style={{
              width: '100%',
              height: '120px',
              padding: '0.5rem',
              borderRadius: '4px',
              border: '1px solid #ccc',
              fontFamily: 'inherit',
              marginBottom: '1rem',
            }}
          />

          {/* Status */}
          {status && <div style={{ color: '#666', marginBottom: '0.5rem' }}>{status}</div>}

          {/* Buttons */}
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button
              onClick={handleSubmit}
              disabled={loading}
              style={{
                flex: 1,
                padding: '0.75rem',
                background: '#28a745',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: loading ? 'not-allowed' : 'pointer',
                opacity: loading ? 0.6 : 1,
              }}
            >
              {loading ? 'Saving...' : 'Save'}
            </button>
            <button
              onClick={() => setOpen(false)}
              style={{
                padding: '0.75rem 1rem',
                background: '#6c757d',
                color: 'white',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
              }}
            >
              Close
            </button>
          </div>
        </div>
      )}
    </>
  )
}
```

---

## Voice Capture Integration

### Using Web Speech API

```tsx
const [recording, setRecording] = useState(false)

const handleVoiceCapture = async () => {
  const recognition = new (window.webkitSpeechRecognition || window.SpeechRecognition)()
  recognition.lang = 'en-US'
  
  recognition.onstart = () => setRecording(true)
  recognition.onend = () => setRecording(false)
  
  recognition.onresult = (event) => {
    const transcript = Array.from(event.results)
      .map(result => result[0].transcript)
      .join('')
    
    setInput(prev => prev + ' ' + transcript)
  }
  
  recognition.start()
}

// In JSX:
{mode === 'voice' && (
  <button onClick={handleVoiceCapture} disabled={recording}>
    {recording ? 'Recording...' : 'Start Recording'}
  </button>
)}
```

---

## Screenshot OCR Integration

### Client-Side OCR with Tesseract.js

```tsx
import Tesseract from 'tesseract.js'

const handleScreenshotCapture = async () => {
  const canvas = await html2canvas(document.body)
  const imageData = canvas.toDataURL('image/png')
  
  const result = await Tesseract.recognize(imageData, 'eng')
  const ocrText = result.data.text
  
  // Send to backend
  const res = await api.post('/api/v1/capture', {
    screenshot_ocr: ocrText,
    source: 'screenshot',
    current_url: window.location.pathname,
  })
  
  setCaptureId(res.data.capture_id)
}
```

---

## Idea Vault Browser

```tsx
export function IdeaVaultBrowser() {
  const [cards, setCards] = useState([])
  const [filter, setFilter] = useState<'all' | 'idea' | 'task' | 'decision'>('all')

  React.useEffect(() => {
    const loadCards = async () => {
      const res = await api.get('/api/v1/cards', {
        params: {
          capture_type: filter === 'all' ? undefined : filter,
          limit: 50,
        }
      })
      setCards(res.data.cards)
    }
    loadCards()
  }, [filter])

  return (
    <div>
      <h2>💡 Idea Vault</h2>
      
      {/* Filter Tabs */}
      <div style={{ marginBottom: '1.5rem', display: 'flex', gap: '0.5rem' }}>
        {['all', 'idea', 'task', 'decision'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f as any)}
            style={{
              padding: '0.5rem 1rem',
              background: filter === f ? '#007bff' : '#e9ecef',
              color: filter === f ? 'white' : 'black',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Cards Grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
        gap: '1rem',
      }}>
        {cards.map(card => (
          <div
            key={card.card_id}
            style={{
              padding: '1rem',
              background: '#f8f9fa',
              borderRadius: '8px',
              border: '1px solid #dee2e6',
            }}
          >
            <h3>{card.title}</h3>
            <p style={{ color: '#666', marginBottom: '0.5rem' }}>{card.content.substring(0, 150)}...</p>
            <div style={{ fontSize: '0.85rem', color: '#999' }}>
              Type: {card.capture_type} | Pillars: {card.pillars.join(', ')}
            </div>
            {card.tags.length > 0 && (
              <div style={{ marginTop: '0.5rem' }}>
                {card.tags.map(tag => (
                  <span
                    key={tag}
                    style={{
                      display: 'inline-block',
                      background: '#e3f2fd',
                      color: '#1976d2',
                      padding: '0.25rem 0.5rem',
                      borderRadius: '4px',
                      marginRight: '0.25rem',
                      fontSize: '0.8rem',
                    }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
```

---

## API Examples

### Create Capture (Text)

```bash
curl -X POST http://localhost:8000/api/v1/capture \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Build async capture system",
    "source": "web",
    "current_url": "/dashboard"
  }'
```

**Response (202 Accepted):**
```json
{
  "capture_id": "cap-abc12345",
  "detected_type": "task",
  "detected_pillars": ["professional", "learning"],
  "status": "processing",
  "timestamp": "2026-03-26T12:34:56.789Z",
  "confidence": 0.85
}
```

### Create Capture (Voice)

```bash
curl -X POST http://localhost:8000/api/v1/capture \
  -H "Content-Type: application/json" \
  -d '{
    "voice_transcript": "remind me to buy milk tomorrow morning",
    "source": "voice",
    "current_url": "/dashboard"
  }'
```

### Save as Card

```bash
curl -X POST http://localhost:8000/api/v1/capture/cap-abc12345/save \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Buy milk",
    "tags": ["shopping", "urgent"]
  }'
```

### List Cards

```bash
curl http://localhost:8000/api/v1/cards?capture_type=task&limit=10
```

### Get Statistics

```bash
curl http://localhost:8000/api/v1/stats
```

Response:
```json
{
  "total_captures": 42,
  "saved_cards": 28,
  "by_type": {
    "idea": 12,
    "task": 10,
    "decision": 4,
    "routine": 2
  },
  "by_pillar": {
    "professional": 18,
    "personal": 8,
    "creative": 2
  },
  "this_week": 7,
  "timestamp": "2026-03-26T12:34:56.789Z"
}
```

---

## Configuration

### Environment Variables

Add to backend `.env`:

```env
# Idea Vault settings
VAULT_MAX_CARD_SIZE_MB=10
VAULT_OCR_ENABLED=true
VAULT_VOICE_ENHANCEMENT=true
VAULT_AUTO_CLASSIFY=true
```

### Database Integration (Future)

The current implementation uses in-memory storage. For production, migrate to PostgreSQL:

```python
# Schema
CREATE TABLE captures (
  id SERIAL PRIMARY KEY,
  capture_id VARCHAR(16) UNIQUE,
  user_id UUID,
  text TEXT,
  source VARCHAR(20),
  detected_type VARCHAR(20),
  detected_pillars TEXT[],
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE idea_cards (
  id SERIAL PRIMARY KEY,
  card_id VARCHAR(16) UNIQUE,
  user_id UUID,
  title VARCHAR(255),
  content TEXT,
  capture_type VARCHAR(20),
  pillars TEXT[],
  tags TEXT[],
  saved BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

---

## Testing

### Test Capture Type Detection

```python
from idea_vault import IdeaVaultService

# Test task detection
text = "I need to implement the capture widget"
detected_type, confidence = IdeaVaultService.detect_capture_type(text)
print(f"Type: {detected_type}, Confidence: {confidence:.2f}")
# Output: Type: task, Confidence: 0.85

# Test pillar detection
pillars = IdeaVaultService.detect_pillars(text)
print(f"Pillars: {pillars}")
# Output: Pillars: [PillarTag.PROFESSIONAL]
```

### Test Voice Processing

```python
from capture_utils import CaptureProcessor

result = CaptureProcessor.process_capture(
    text="buy groceries",
    voice_transcript="remind me to call mom tomorrow",
)
print(result)
# {
#   'combined_text': 'buy groceries remind me to call mom tomorrow.',
#   'sources': ['text', 'voice'],
#   'quality_score': 0.9,
#   'warnings': []
# }
```

---

## Next Steps

1. **Database Integration**: Replace in-memory storage with PostgreSQL
2. **WebSocket Support**: Add real-time capture status updates
3. **Advanced OCR**: Integrate server-side OCR (Tesseract, Paddle-OCR)
4. **LLM Classification**: Use Ollama for improved type/pillar detection
5. **Search & Tags**: Full-text search on captured content
6. **Sharing**: Export cards as markdown, share with team
7. **Analytics**: Trending topics, productivity insights

---

_Last updated: 2026-03-26_
