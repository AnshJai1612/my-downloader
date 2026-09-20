FROM python:3.10-slim

# Prevent interactive prompts (like tzdata) from hanging build execution
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install FFmpeg and clean up package caches to reduce image size
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run app binding to 0.0.0.0 and reading Render's dynamic PORT
CMD ["python", "app.py"]
