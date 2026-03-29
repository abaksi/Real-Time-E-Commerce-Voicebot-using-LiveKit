# Real-Time E-Commerce Voicebot using LiveKit

**A real-time, AI-powered voice assistant for e-commerce, featuring natural conversation, product Q&A, and order support. Built with FastAPI, LiveKit, Ollama, and modern browser tech.**

---

eCommerce VoiceBot enables seamless, bi-directional voice conversations between users and an AI assistant for e-commerce scenarios. It leverages:

## Overview

eCommerce VoiceBot enables seamless, bi-directional voice conversations between users and an AI assistant for e-commerce scenarios. It leverages:
- **LiveKit** for real-time audio streaming (WebRTC)
- **FastAPI** for backend APIs and serving the frontend
- **Ollama** (local LLM) and **OpenAI** (cloud, optional) for language understanding and response
- **faster-whisper** for speech-to-text (STT)
- **edge-tts** for text-to-speech (TTS)
- **Modern frontend** (HTML/JS/CSS) for a responsive, accessible UI

---

## Why Ollama and OpenAI? (Model Justification)

This project uses a dual-LLM approach:
- **Ollama** (local, running llama3.2:1b) is the default for privacy, cost efficiency, and offline capability. It ensures that user data never leaves the local environment and that the system remains operational even without internet access or cloud API keys.
- **OpenAI** (cloud, GPT-4o-mini or similar) is referenced and supported as a primary/fallback for best-in-class accuracy, broader language support, and to demonstrate compatibility with industry-leading LLM APIs.

**Justification:**
- **Privacy & Control:** Ollama keeps all data local, which is critical for sensitive e-commerce scenarios and enterprise deployments.
- **Cost & Accessibility:** Running locally avoids API costs and rate limits, making the solution accessible for demos, research, and production.
- **Quality & Flexibility:** OpenAI is supported for scenarios where the highest accuracy or latest models are required, or when cloud resources are available.
- **Reliability:** The system automatically falls back to Ollama if OpenAI is unavailable, and to rule-based logic if neither LLM is accessible, ensuring uninterrupted service.

This hybrid approach provides the best balance of privacy, cost, and quality, and demonstrates real-world readiness for both enterprise and research use cases.



## Prerequisites

- Python 3.11+
- Ollama (recommended: v0.1.34+)
- FFmpeg (for audio processing)
- LiveKit Cloud account (for signaling)
- Chrome or Edge browser

---

## Local Setup

1. **Clone the repository**
2. **Install prerequisites:**
        - [Install Ollama](https://ollama.com/download) and run `ollama serve` (host, not in Docker)
        - [Install FFmpeg](https://ffmpeg.org/download.html)
        - [Install Python 3.11+](https://www.python.org/downloads/)
3. **Create and activate a virtual environment:**
        ```sh
        python -m venv .venv
        # Windows:
        .\.venv\Scripts\activate
        # macOS/Linux:
        source .venv/bin/activate
        ```
4. **Install dependencies:**
        ```sh
        pip install --upgrade pip
        pip install -r requirements.txt
        ```
5. **Configure environment:**
        - Copy `.env.example` to `.env` and update with your LiveKit and API credentials
6. **Start backend and agent:**
        ```sh
        python backend/app.py
        python backend/agent.py start
        ```
7. **Open the app:**
        - Go to [http://localhost:5001](http://localhost:5001) in Chrome or Edge

---

## Docker Setup

1. Ensure `.env` is configured with your LiveKit credentials
2. Start Ollama on the host: `ollama serve`
3. Build and launch the app:
        ```sh
        docker compose up --build
        ```
4. Open [http://localhost:5001](http://localhost:5001) in your browser

> **Note:** Ollama is not included in the Docker image. The containers connect to `http://host.docker.internal:11434`.

---


## Example Phrases

- "What is the status of order 12345?"
- "Tell me about the Laptop Pro."
- "What is your return policy?"
- "Do you sell smartphones?"

---


## Environment Variables

See `.env.example` for all configuration options and descriptions. Key variables:
- `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_URL` (LiveKit Cloud)
- `OLLAMA_BASE_URL` (default: `http://host.docker.internal:11434`)
- `WHISPER_MODEL`, `FASTER_WHISPER_DEVICE`, `FASTER_WHISPER_COMPUTE_TYPE` (STT)
- `OPENAI_API_KEY` (optional, for OpenAI fallback)

---

---


## Architecture & Flow

The following diagram and steps illustrate the real-time flow of a user voice interaction through the system:

```mermaid
flowchart TD
        User[User]
        Browser[Browser UI]
        Backend[FastAPI Backend]
        Agent[Voice Agent]
        STT[STT (faster-whisper)]
        TTS[TTS (edge-tts)]
        LLM[LLM (Ollama/OpenAI)]
        RAG[RAG (Product Data)]
        LiveKit[LiveKit Cloud]

        User --> Browser
        Browser -->|Audio/WebRTC| Backend
        Backend -->|Token/API| LiveKit
        Backend -->|Audio| Agent
        Agent --> Backend
        Backend --> Browser
        Browser --> User

        Agent -- Speech-to-Text --> STT
        Agent -- Text-to-Speech --> TTS
        Agent -- LLM Query --> LLM
        Agent -- RAG Lookup --> RAG
```

**Flow Description:**
1. **User** speaks or interacts with the browser UI.
2. **Browser** captures audio and streams it to the backend via WebRTC (LiveKit).
3. **Backend** (FastAPI) manages signaling, authentication, and routes audio to the agent.
4. **Voice Agent** processes the audio:
        - Converts speech to text (faster-whisper)
        - Optionally retrieves product/context data (RAG)
        - Sends text to LLM (Ollama/OpenAI) for response
        - Converts response text to speech (edge-tts)
5. **Backend** receives the synthesized audio and streams it back to the browser.
6. **Browser** plays the audio response to the user, completing the loop.

All communication is real-time, enabling natural, conversational voice experiences.

---

## Project Structure

```
├── backend/
│   ├── agent.py          # LiveKit agent: VAD, STT→LLM→TTS pipeline
│   ├── app.py            # FastAPI backend: token generation, serves frontend
│   ├── llm_client.py     # LLM integration (OpenAI, Ollama, fallback logic)
│   ├── stt.py            # Speech-to-text (faster-whisper)
│   ├── tts.py            # Text-to-speech (edge-tts + PyAV)
├── frontend/
│   ├── index.html        # Main UI (single page)
│   ├── app.js            # LiveKit client logic (browser)
│   └── style.css         # UI styles (modern purple/white theme)
├── data/
│   └── product-dataset.json   # Mock orders, products, policies (RAG source)
├── deliverables/         # Academic/project deliverable documents
├── logs/                 # Runtime logs (agent.log, backend.log)
├── requirements.txt      # Pinned Python dependencies
├── .env.example          # Environment variable template
├── Dockerfile
└── docker-compose.yml
```

## Frontend Launch

The backend serves the frontend at [http://localhost:5001](http://localhost:5001). Open this URL in Chrome or Edge to use the bot UI.

---



## License

Add your license information here if you plan to share this project publicly.

---

---


## Deliverables

| Document | File |
|:---|:---|
| Technical Report | [deliverables/TECHNICAL_REPORT.md](deliverables/TECHNICAL_REPORT.md) |
| Project Summary | [deliverables/PROJECT_SUMMARY.md](deliverables/PROJECT_SUMMARY.md) |
| Presentation Deck | [deliverables/Presentation_Deck.md](deliverables/Presentation_Deck.md) |
| Presentation Outline | [deliverables/PRESENTATION_OUTLINE.md](deliverables/PRESENTATION_OUTLINE.md) |

---



---



