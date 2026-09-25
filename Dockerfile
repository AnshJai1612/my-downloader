```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV DENO_INSTALL=/root/.deno
ENV PATH="/root/.deno/bin:$PATH"

# System packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
        unzip && \
    rm -rf /var/lib/apt/lists/*

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | sh

# App directory
WORKDIR /app

# Python dependencies
COPY requirements.txt .

RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

# Application
COPY . .

# Verify dependencies
RUN echo "===== DENO =====" && \
    deno --version

RUN echo "===== FFMPEG =====" && \
    ffmpeg -version | head -n 1

RUN echo "===== YT-DLP =====" && \
    python -c "import yt_dlp; print('yt-dlp:', yt_dlp.version.__version__)"

# IMPORTANT:
# Use a shell so $PORT is expanded by the container.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 1 --timeout 300 app:app"]
```
