FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies (portaudio, ffmpeg, build tools)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        build-essential \
        libpq-dev \
        libportaudio2 \
        libportaudiocpp0 \
        portaudio19-dev \
        libasound-dev \
        libsndfile1-dev \
        ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install poetry-core build backend first
RUN pip install --no-cache-dir --upgrade pip poetry-core

# Install torch CPU first (avoids huge CUDA download on ARM64)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install Python dependencies
COPY pyproject.toml README.md ./
COPY vocode/ ./vocode/
RUN pip install --no-cache-dir -e ".[dev]" || pip install --no-cache-dir -e .
RUN pip install --no-cache-dir twilio google-api-python-client
RUN pip install --no-cache-dir langgraph langgraph-checkpoint-postgres
RUN python -m nltk.downloader -d /usr/local/share/nltk_data punkt punkt_tab

# Copy application code (mounted at runtime for dev, but copied for build)
COPY voice_platform/ ./voice_platform/

# Run migrations on startup, then start the server
CMD ["sh", "-c", "python -c 'import asyncio; from voice_platform.database import init_db; asyncio.run(init_db())' && python -m uvicorn voice_platform.main:app --host 0.0.0.0 --port 3000"]
