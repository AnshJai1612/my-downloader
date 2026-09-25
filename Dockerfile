```dockerfile
FROM python:3.12-slim

# ------------------------------------------------------------
# Environment
# ------------------------------------------------------------

ENV PYTHONUNBUFFERED=1
ENV DENO_INSTALL=/root/.deno
ENV PATH="/root/.deno/bin:$PATH"

# ------------------------------------------------------------
# System dependencies
# ------------------------------------------------------------

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        unzip && \
    rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# Install Deno
# ------------------------------------------------------------

RUN curl -fsSL https://deno.land/install.sh | sh

# ------------------------------------------------------------
# Application
# ------------------------------------------------------------

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

COPY . .

# ------------------------------------------------------------
# Verify installation
# ------------------------------------------------------------

RUN echo "===== DENO =====" && \
    deno --version

RUN echo "===== FFMPEG =====" && \
    ffmpeg -version | head -n 1

RUN echo "===== YT-DLP =====" && \
    python -c "import yt_dlp; print('yt-dlp:', yt_dlp.version.__version__)"

# ------------------------------------------------------------
# Start
# ------------------------------------------------------------

CMD ["sh", "-c", "PORT=${PORT:-10000}; echo \"Starting server on port ${PORT}\"; exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --timeout 300 app:app"]
```
