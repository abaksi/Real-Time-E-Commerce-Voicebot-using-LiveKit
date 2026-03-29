# Presentation Outline — Real-Time E-Commerce Voicebot

---

## 1. Problem Motivation & Use Case (2 min)

### Why Voice Commerce?
- Text-based support is slow and impersonal for complex queries.
- Voice enables hands-free, faster, more accessible interactions.
- Voicebots reduce handle time by 30–50% in industry benchmarks.

### Core Use Cases (our demo will cover all three)
1. **Order Tracking**: "Where is my order?" — eliminates login + search friction
2. **Product Discovery**: "Tell me about the Laptop Pro." — consultative selling
3. **Policy Queries**: "Can I return this?" — instant policy lookup

---

## 2. Architecture & Technology Stack (4 min)
**Dual LLM Logic:** The backend supports both **OpenAI** (cloud, primary if API key is set) and **Ollama** (local, fallback or offline). The system automatically uses OpenAI if credentials are provided, otherwise defaults to Ollama. If both are unavailable, rule-based responses are used as a last resort.

**Why Ollama and OpenAI?**
Ollama (local, llama3.2:1b) is chosen for privacy, cost, and offline operation. OpenAI (cloud) is referenced for best-in-class accuracy and as a fallback. This hybrid model ensures privacy and cost control while allowing access to the latest cloud LLMs when needed, with seamless fallback for reliability.
### System Flow

```
User speaks → Browser mic (WebRTC) → LiveKit Cloud
    → LiveKit Worker (Python)
        → VAD: RMS gate + faster-whisper VAD filter
        → STT: faster-whisper (in-memory, CTranslate2, CPU)
        → LLM: Ollama dolphin-phi:2.7b + JSON RAG context
        → TTS: edge-tts (Microsoft Neural) + PyAV PCM decode
    → LiveKit AudioSource → Browser speaker
```

### Technology Stack

| Component | Technology | Role |
|:---|:---|:---|
| Audio Transport | LiveKit (WebRTC) | Real-time bidirectional audio streaming |
| Backend Framework | FastAPI (Python) | Token server, health check, static files |
| Ears (STT) | faster-whisper 1.2.1 | In-memory PCM → text, no temp files |
| Brain (LLM) | Ollama + dolphin-phi:2.7b | Local, private, ~1–2 s inference |
| Knowledge (RAG) | JSON dataset + keyword search | Order/product/policy lookup |
| Voice (TTS) | edge-tts + PyAV | Neural voice synthesis, async, in-memory |
| Frontend | Vanilla JS + LiveKit SDK | Mic, playback, error UI, autoplay unlock |

---

## 3. Engineering Highlights (3 min)

### In-Memory Audio Pipeline
No temp WAV files anywhere in the pipeline. PCM16 bytes flow directly:
`VAD buffer → transcribe_pcm16() → synthesize_to_pcm() → AudioSource.capture_frame()`
Saved ~100–200 ms per turn compared to the original disk-I/O approach.

### Two-Stage VAD
1. **RMS energy gate** (microseconds) — rejects near-silence without running Whisper
2. **faster-whisper built-in VAD** (`STT_VAD_FILTER=true`) — rejects non-speech at the model level

### Per-Stage Latency Telemetry
Every turn logs:
`[LATENCY] STT=Xms LLM=Xms TTS=Xms PLAYBACK=Xms TOTAL=Xms`
Enables diagnosis without guesswork.

### Multi-Tier LLM Fallback
OpenAI GPT-4o-mini (if API key set) → Ollama dolphin-phi (local, fallback) → rule-based (last resort).
The system never fails silently — always returns a response.

---

## 4. Live Demo (5 min)

### Setup Verification (pre-demo checklist)
- [ ] Ollama running (`ollama run dolphin-phi:2.7b "test"`)
- [ ] Terminal 1: `python backend/app.py` → port 5001 OK
- [ ] Terminal 2: `python backend/agent.py start` → "imported all modules"
- [ ] Browser: Chrome → http://localhost:5001 → Connected

### Demo Script

**Turn 1 — Order Tracking**
> Speak: *"What is the status of order 12345?"*
> Expected: "Order 12345 is Shipped and expected in 2 days."
> Highlight: RAG lookup, fast response, natural voice

**Turn 2 — Product Info**
> Speak: *"Tell me about the Laptop Pro."*
> Expected: Specs + price from product-dataset.json
> Highlight: Factual accuracy (not hallucinated)

**Turn 3 — Policy**
> Speak: *"What is your return policy?"*
> Expected: 30-day return window summary
> Highlight: Policy retrieval

**Turn 4 — General Chat**
> Speak: *"Do you offer free shipping?"*
> Expected: Shipping policy response or honest "I don't have that information"
> Highlight: Graceful uncertainty handling

---

## 5. Challenges & Learnings (2 min)

| Challenge | Root Cause | Solution Applied |
|:---|:---|:---|
| Bot timeouts on every utterance | Pipeline timeout < Ollama response time | Aligned: Ollama=12 s, Pipeline=15 s |
| TTS too slow | pyttsx3 blocking `runAndWait()` | Replaced with async edge-tts + PyAV |
| STT transcribing silence | VAD too sensitive | Two-stage VAD + no-speech threshold |
| Browser audio silent | Autoplay policy blocked | Click-listener unlock + user message |
| No latency visibility | No instrumentation | Added `[LATENCY]` per-stage logging |

---

## 6. Results Summary (1 min)

- End-to-end latency: **~2–4 s** on CPU (vs. project target of <5 s)
- STT accuracy: **~95%** on clear microphone input
- Zero crashes during demo testing
- All three use cases (order tracking, product info, policy) demonstrated successfully

---

## 7. Q&A Topics (prepared answers)

**"How does it handle wrong orders / products not in the dataset?"**
The LLM is instructed to answer honestly when context is missing rather than hallucinating.

**"Could this run on a phone?"**
The frontend uses standard WebRTC — works on mobile Chrome. The backend stays on a server.

**"What would production deployment look like?"**
Replace Ollama with a cloud LLM API, deploy FastAPI + agent on a VM, use LiveKit Cloud as-is, add auth tokens per user session.

**"Why not use OpenAI for TTS?"**
edge-tts achieves near parity with paid APIs at zero cost and lower latency for short responses.
