# Presentation Deck — eCommerce VoiceBot Capstone

---

## Slide 1: Problem & Motivation

**The Problem**
- E-commerce support is slow: customers type queries, navigate menus, wait for responses.
- 71% of customers prefer voice for complex support interactions.
- Existing voice bots use HTTP file uploads — high latency, no real streaming.

**Our Solution**
A voice-first AI assistant that:
- Streams audio in real-time via WebRTC
- Understands spoken queries (not just keywords)
- Responds with natural synthesized speech in ~2–4 seconds

---

## Slide 2: Architecture Overview
**Dual LLM Logic:** The backend supports both **OpenAI** (cloud, primary if API key is set) and **Ollama** (`llama3.2:1b`, local, fallback or offline). The system automatically uses OpenAI if credentials are provided, otherwise defaults to Ollama. If both are unavailable, rule-based responses are used as a last resort.

### Why Ollama and OpenAI?
**Ollama** is used for privacy, cost efficiency, and offline capability—keeping all data local and ensuring the system works even without internet or cloud API keys. **OpenAI** is referenced and supported for best-in-class accuracy, broader language support, and to demonstrate compatibility with industry-leading LLM APIs. This hybrid approach provides the best balance of privacy, cost, and quality, and ensures reliability by always falling back to a working model.
```
User's Browser
    │ WebRTC (LiveKit Cloud)
    ▼
LiveKit Worker (Python)
    │
    ├─ VAD:  faster-whisper built-in + RMS energy gate
    ├─ STT:  faster-whisper (hybrid: tiny for short utterances, base for long/product queries, in-memory, CPU, ~400 ms)
    ├─ LLM:  Ollama llama3.2:1b + RAG (~1.5 s)
    └─ TTS:  edge-tts → PyAV PCM decode (~300 ms)
                │
    LiveKit AudioSource → Browser Speaker
```

**Total round-trip: ~2–4 seconds on a laptop CPU**

---

## Slide 3: Tech Stack

| Layer | Technology | Key Benefit |
|:---|:---|:---|
| Audio Transport | LiveKit (WebRTC) | Real-time bidirectional streaming |
| Speech-to-Text | faster-whisper 1.2.1 (hybrid: tiny/base) | 4× faster than original Whisper, CPU-only |
| Language Model | Ollama + llama3.2:1b | Local, private, ~1 s inference |
| Language Model (fallback order) | OpenAI (cloud, if API key set) → Ollama (llama3.2:1b, local) → rule-based | Always responds, even if cloud/offline |
| Text-to-Speech | edge-tts + PyAV | Microsoft Neural voice, async, in-memory |
| Backend | FastAPI (Python) | Token server + static file serving |
| Frontend | Vanilla JS + LiveKit SDK | Browser mic, audio playback, error UI |
| Knowledge Base | JSON dataset + keyword RAG | Order/product/policy lookups |

---

## Slide 4: Key Engineering Challenges

**1. Latency**
- Root cause: pyttsx3 was synchronous/blocking; temp WAV files added disk I/O
- Fix: Replaced with async edge-tts + in-memory PyAV PCM decode

**2. STT Noise**
- Root cause: VAD was too sensitive — transcribing silence and short sounds
- Fix: faster-whisper's built-in VAD filter + RMS energy gate + `STT_NO_SPEECH_THRESHOLD=0.7`

**3. LLM Timeouts**
- Root cause: Pipeline timeout (20 s) exceeded Ollama's response window (25 s)
- Fix: Aligned timeouts — Ollama=12 s, Pipeline=15 s

**4. Browser Autoplay**
- Root cause: Chrome blocks audio playback without a user gesture
- Fix: Deferred autoplay with click-listener unlock (`pendingAudioUnlock`)

---

## Slide 5: Demo — Live Interaction

**Scenario 1: Order Tracking**
> User: *"What is the status of order 12345?"*
> Bot: *"Order 12345 is Shipped and expected to arrive in 2 days."*
*(RAG lookup from product-dataset.json)*

**Scenario 2: Product Info**
> User: *"Tell me about the Laptop Pro."*
> Bot: *"The Laptop Pro features an Intel i9 processor, 32 GB RAM, and 1 TB SSD, priced at $1,499."*

**Scenario 3: Policy**
> User: *"What is your return policy?"*
> Bot: *"You can return any item within 30 days of purchase for a full refund."*

---

## Slide 6: Results & Metrics

| Metric | Value |
|:---|:---|
| End-to-end latency (CPU) | 2–4 seconds |
| STT accuracy (tiny/base hybrid) | ~95% on clear speech |
| LLM response time (llama3.2:1b) | 1–2 seconds |
| TTS naturalness | Microsoft Neural (JennyNeural) |
| System uptime during testing | Stable, no crashes |

---

## Slide 7: Key Learnings

1. **Pipeline alignment matters** — timeouts at each stage must nest properly (Ollama < Pipeline < User wait)
2. **In-memory beats disk I/O** — removing temp WAV writes saved 50–200 ms per turn
3. **VAD is the "soul" of a voicebot** — too sensitive = noise; too strict = missed speech
4. **Async TTS is mandatory** — any blocking call in the audio path kills responsiveness
5. **Browser constraints are real** — autoplay policies, mic permissions, and WebRTC quirks need explicit handling

---

## Slide 8: Future Enhancements

| Enhancement | Impact |
|:---|:---|
| GPU inference (CUDA) | STT: 400 ms → 50 ms; Total: ~1 s |
| Streaming LLM + chunk TTS | First audio in <500 ms |
| Barge-in / interruption | Natural conversational feel |
| Vector RAG (chromadb) | Scalable to large product catalogs |
| Sentiment detection | Route frustrated users to human agents |
| Multi-language support | Swap voice + model per locale |
