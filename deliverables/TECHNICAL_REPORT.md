# Technical Report — eCommerce VoiceBot
---
## 1. Problem Overview
**Scope:** Build a real-time, browser-based e-commerce voice assistant with sub-5-second round-trips, natural conversation, and robust fallback logic. The system must support both cloud (OpenAI) and local (Ollama) LLMs, and handle real-world audio and product data.
Real-time voice commerce demands sub-5-second round-trips from speech capture to synthesized reply. Traditional voicebots use HTTP file uploads (high latency, no streaming). This project implements a **streaming WebRTC pipeline** that processes audio continuously, applies a fully in-memory STT→LLM→TTS chain, and streams synthesized speech back — all within a browser session.

---

## 2. System Architecture
**Dual LLM Logic:** The backend supports both **OpenAI** (cloud, primary if API key is set) and **Ollama** (`llama3.2:1b`, local, fallback or offline). The system automatically uses OpenAI if credentials are provided, otherwise defaults to Ollama. If both are unavailable, rule-based responses are used as a last resort.

**Why Ollama and OpenAI?**
Ollama (local, llama3.2:1b) is used for privacy, cost, and offline capability. OpenAI (cloud) is referenced for best-in-class accuracy and as a fallback. This hybrid approach ensures privacy and cost control, while providing access to the latest cloud LLMs when available, and always-on fallback for reliability.
### High-Level Component Map

```
┌─────────────────────────────────────────────────────┐
│ Browser (Chrome / Edge)                             │
│  getUserMedia → LiveKit Client SDK                  │
│  ← AudioTrack playback                              │
└──────────────────┬──────────────────────────────────┘
                   │  WebRTC (LiveKit Cloud relay)
┌──────────────────▼──────────────────────────────────┐
│ LiveKit Worker  (backend/agent.py)                  │
│                                                     │
│  AudioTrack frames (PCM16, 48 kHz, 20 ms chunks)   │
│        │                                            │
│   [VAD Gate] — RMS energy + faster-whisper VAD      │
│        │ utterance detected                         │
│   [STT] stt.transcribe_pcm16()                      │
│        │ text                                       │
│   [LLM] llm_client.chat()                           │
│        │ response text                              │
│   [TTS] tts.synthesize_to_pcm()                     │
│        │ PCM16 bytes @ 24 kHz                       │
│   [AudioSource] LiveKit AudioSource → WebRTC track  │
└─────────────────────────────────────────────────────┘
```

### Component Details

**FastAPI Backend (`app.py`)**
- Issues short-lived LiveKit JWT tokens to authenticated browsers
- Serves the frontend static files (HTML, CSS, JS)
- Runs on port 5001

**LiveKit Worker (`agent.py`)**
- Implemented using `livekit-agents` SDK
- Joins the LiveKit room as a participant named "assistant"
- Subscribes to the user's audio track and accumulates PCM16 frames
- Voice Activity Detection (VAD): two-stage
  1. RMS energy gate (rejects near-silence frames immediately)
  2. faster-whisper built-in VAD filter (`STT_VAD_FILTER=true`)
- Utterance queue (`asyncio.Queue(maxsize=2)`) ensures only the latest speech is processed under load
- Post-TTS cooldown (0.5 s) suppresses echo from the bot's own playback

**Speech-to-Text (`stt.py`)**
- Hybrid: `faster-whisper` (CTranslate2 backend, `int8` quantization on CPU). Uses `tiny` model for short utterances (<2s), `base` for longer/product queries. Fallback: `openai-whisper` (PyTorch, if CTranslate2 unavailable). API: `transcribe_pcm16(audio_bytes, sample_rate, channels)` — fully in-memory, no disk I/O. Preprocessing: PCM16 → float32 → resample to 16 kHz if needed.

**LLM Client (`llm_client.py`)**
- Multi-tier fallback: **OpenAI GPT-4o-mini** (if `OPENAI_API_KEY` is set) → **Ollama llama3.2:1b** (local, default if OpenAI not set) → **rule-based** (last resort)
- RAG: keyword-matches user query against `product-dataset.json`; injects matching records as JSON context into the system prompt
- Context window: trimmed to 3,000 characters before each call
- Ollama config: `num_predict=80`, `temperature=0.2`, timeout=12 s

**Text-to-Speech (`tts.py`)**
- `edge-tts` generates compressed MP3/OPUS audio via Microsoft Neural TTS
- `PyAV` decodes compressed audio → PCM16 @ 24 kHz → returned as raw bytes
- API: `synthesize_to_pcm(text)` → `{"pcm_bytes": bytes, "sample_rate": 24000, "channels": 1}`
- Fully async, no blocking calls (replaced pyttsx3)

**Frontend (`app.js`)**
- `navigator.mediaDevices.getUserMedia({audio:true})` preflight before LiveKit connection
- Autoplay unlock: `pendingAudioUnlock` flag + click listener
- Error bubbles: `type:"error"` data messages from backend shown in chat (⚠️)

---

## 2.1 Backend Run Instructions (Update)

- The backend now uses **relative imports** for better package compatibility.
- **Always run the agent as a module from the project root:**

```sh
python -m backend.agent
```

- Do **not** run with `python backend/agent.py` (will cause import errors).

**Recent improvements:**
- Improved logging and error handling
- UI is more compact and responsive
- All backend files checked and fixed for import/runtime errors
- Documentation and code comments updated for maintainability

See [README.md](../README.md) for full setup and troubleshooting.

---

## 3. Prompt Design & RAG

The system prompt is concise (4 lines) to minimize token overhead:

```
You are a friendly and concise e-commerce assistant.
Answer in 1-2 sentences using only the context provided.
If you do not know the answer, say so honestly.
Never make up prices, order statuses, or policies.
```

RAG context is injected as a JSON block below the system prompt:

```
CONTEXT:
{"orders": [...], "products": [...], "policies": [...]}
```

Only records matching keywords in the user query are included (not the full dataset).

---

## 4. Latency Breakdown

Per-stage telemetry is logged on every utterance (`[LATENCY]` lines in `logs/agent.log`):

| Stage | CPU Baseline | GPU (CUDA) |
|:---|:---|:---|
| STT (faster-whisper tiny/base) | 200–700 ms (tiny for short, base for long) | ~50 ms |
| LLM (llama3.2:1b) | 1,000–2,000 ms | N/A (CPU only) |

---

---
| TTS (edge-tts + PyAV) | 200–500 ms | 200–500 ms |
| Playback buffering | 20–100 ms | 20–100 ms |
| **Total** | **~2–4 s** | **~1–2 s** |

Key optimizations applied:
- In-memory audio (no temp WAV files) — removed ~50–200 ms disk I/O per turn
- Tight pipeline timeout (15 s) aligned with Ollama timeout (12 s) — prevents hung turns
- Queue depth 2 — drops queued-up stale utterances instead of processing them late
- VAD filter rejects silence before STT — avoids wasted inference cycles

---

## 5. Data Layer

---

`data/product-dataset.json` contains three top-level keys:

| Key | Contents |
|:---|:---|
| `orders` | Order IDs, statuses, estimated delivery dates |
| `products` | Names, descriptions, prices, specs |
| `policies` | Return policy, warranty terms, shipping info |

The RAG engine uses simple keyword matching (case-insensitive substring search) to select relevant records. A vector-search upgrade (e.g., `chromadb`) would scale this to thousands of records.

---

## 6. Limitations & Future Improvements

---

| Limitation | Proposed Improvement |
|:---|:---|
| No barge-in (user cannot interrupt bot) | LiveKit server-side mute + agent-side playback cancel |
| CPU-only STT adds ~0.5 s | `FASTER_WHISPER_DEVICE=cuda` with NVIDIA GPU |
| LLM response length varies | Enforce JSON output schema + structured extraction |
| RAG is keyword-based | Replace with semantic vector search (chromadb / pgvector) |
| Single language (English) | Swap voice and model per locale via env vars |
| No auth / multi-user | Add room-scoped tokens per user session |
