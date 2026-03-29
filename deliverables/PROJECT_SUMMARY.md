# Project Summary — eCommerce VoiceBot (LiveKit Edition)

## Status: COMPLETE & DEMO-READY

---

## 1. Project Overview


A **real-time, bi-directional voice assistant** for e-commerce, built with **LiveKit WebRTC**. Unlike traditional record-and-upload bots, this system streams audio continuously, processes it locally, and streams synthesized speech back — all within a browser tab.

**Dual LLM Logic:** The backend supports both **OpenAI** (cloud, primary if API key is set) and **Ollama** (local, fallback or offline). The system automatically uses OpenAI if credentials are provided, otherwise defaults to Ollama. If both are unavailable, rule-based responses are used as a last resort.

**Why Ollama and OpenAI?**
Ollama (local, llama3.2:1b) is used for privacy, cost, and offline capability. OpenAI (cloud) is referenced for best-in-class accuracy and as a fallback. This hybrid approach ensures privacy and cost control, while providing access to the latest cloud LLMs when available, and always-on fallback for reliability.

### Architecture at a Glance


```
User Browser (Chrome/Edge)
  │  WebRTC audio stream (LiveKit Cloud)
  ▼
LiveKit Worker (agent.py)
  ├─ VAD: RMS energy gate + faster-whisper built-in VAD
  ├─ STT: faster-whisper (in-memory, no temp files)
  ├─ LLM: OpenAI (primary, if API key set) → Ollama (fallback/local) → rule-based (last resort)
  └─ TTS: edge-tts → PyAV PCM decode → LiveKit AudioSource
```

---

## 2. Tech Stack

| Layer | Technology | Why chosen |
|:---|:---|:---|
| **Transport** | LiveKit Cloud (WebRTC) | Sub-second audio streaming, NAT-traversal, no socket management |
| **STT** | faster-whisper 1.2.1 (CTranslate2) | 4× faster than original Whisper on CPU; in-memory transcription API |
| **LLM** | Ollama + llama3.2:1b | ~1–2 s local inference; GPT-4o-mini fallback for quality |
| **LLM Retrieval** | JSON RAG (keyword match) | Zero-latency product/order lookup without a vector DB |
| **TTS** | edge-tts 7.2.3 + PyAV | Microsoft Neural voices; async streaming; no blocking calls |
| **Backend** | FastAPI (uvicorn) | Token issuing, static file serving, health endpoint |
| **Frontend** | Vanilla JS + LiveKit SDK | Mic preflight, autoplay recovery, error bubble display |

---

## 3. Codebase Breakdown

### Backend (`backend/`)

| File | Role |
|:---|:---|
| `agent.py` | LiveKit Worker — VAD gate, utterance queue, STT→LLM→TTS pipeline, per-stage latency logging |
| `app.py` | FastAPI token server + frontend static file server (port 5001) |
| `llm_client.py` | LLM orchestration: OpenAI → Ollama → rule-based fallback; RAG context injection |
| `stt.py` | faster-whisper primary; openai-whisper fallback; `transcribe_pcm16()` in-memory API |
| `stt.py` | Hybrid faster-whisper: uses 'tiny' for short utterances, 'base' for longer/product queries; openai-whisper fallback; `transcribe_pcm16()` in-memory API |
| `tts.py` | edge-tts synthesis → PyAV PCM decode → `synthesize_to_pcm()` returns raw PCM bytes |

### Frontend (`frontend/`)

| File | Role |
|:---|:---|
| `index.html` | Single-page UI: status indicator, connect button, transcript chat |
| `app.js` | `getUserMedia` preflight, LiveKit connect, audio playback with autoplay unlock |
| `style.css` | Clean, minimal styling |

### Data (`data/`)

| File | Role |
|:---|:---|
| `product-dataset.json` | Mock catalog: orders (IDs, statuses), products (specs, prices), policies |

---

## 4. Key Features

### Real-Time WebRTC Transport
LiveKit streams audio bi-directionally at ~20 ms chunk intervals. No HTTP round-trips per utterance.

### Fully In-Memory Audio Pipeline
No temp WAV files. VAD buffers PCM16 frames → `stt.transcribe_pcm16(bytes)` → `tts.synthesize_to_pcm(text)` → `AudioSource.capture_frame()`.

### Per-Stage Latency Telemetry
Every utterance logs: `[LATENCY] STT=Xms LLM=Xms TTS=Xms PLAYBACK=Xms TOTAL=Xms`

### RAG Context Injection
`llm_client.py` keyword-matches the user query against the product dataset and injects matching JSON records into the system prompt before each LLM call.

### Multi-Tier LLM Fallback
1. **OpenAI GPT-4o-mini** (if `OPENAI_API_KEY` is set)
2. **Ollama llama3.2:1b** (local, default if OpenAI not set)
3. **Rule-based hard-coded responses** (last resort, always available)

### Frontend Hardening
- `getUserMedia` mic preflight before LiveKit connection
- Autoplay unlock on first user click
- Error bubbles in chat (⚠️) when backend pipeline fails

---

## 5. How to Run (Updated)

**Backend now uses relative imports for package compatibility.**

- **Start the backend agent as a module from the project root:**

```sh
python -m backend.agent
```

- **Do NOT run with:**

```sh
python backend/agent.py
```

This ensures all imports work correctly. Running as a script will cause import errors.

**Other improvements:**
- Improved logging and error handling
- UI is more compact and bot-like
- All backend files checked and fixed for import/runtime errors


See [README.md](../README.md) for full setup instructions and environment configuration details.

---

## 6. Performance (CPU, mid-range laptop)

| Stage | Latency |
|:---|:---|
| STT (faster-whisper base) | 300–700 ms |
| LLM (llama3.2:1b, Ollama) | 1,000–2,000 ms |
| STT (faster-whisper tiny/base) | 200–700 ms (tiny for short, base for long) |
| TTS (edge-tts + PyAV) | 200–500 ms |
| **Total end-to-end** | **~2–4 s** |

---

## 7. Future Roadmap

- **Barge-in / interruption**: Stop TTS mid-playback when user starts speaking
- **GPU acceleration**: `FASTER_WHISPER_DEVICE=cuda` reduces STT to ~50 ms
- **Streaming LLM + incremental TTS**: First audio chunk while LLM is still generating
- **Vector RAG**: Replace keyword match with semantic search for large catalogs
- **Multi-language**: Swap `EDGE_TTS_VOICE` and `WHISPER_MODEL` per locale
