# Dockerfile for eCommerce VoiceBot
FROM python:3.11-slim

ENV HF_HOME=/root/.cache/huggingface
ENV WHISPER_MODEL=base
ENV FASTER_WHISPER_DEVICE=cpu
ENV FASTER_WHISPER_COMPUTE_TYPE=int8

# Install system dependencies for audio and LLM clients
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the default Whisper model so LiveKit worker prewarm does not
# spend its entire init window fetching model files at runtime.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"

# Copy the rest of the application
COPY . .

# Expose the backend port
EXPOSE 5001

# Default command (can be overridden in docker-compose)
CMD ["python", "backend/app.py"]
