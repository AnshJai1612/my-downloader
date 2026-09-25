FROM python:3.11-slim

# Install system dependencies: FFmpeg and Node.js
RUN apt-get update && apt-get install -y \
    ffmpeg \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Render assigns its own port at runtime via the $PORT env var
EXPOSE 10000

# Run Gunicorn, binding to whatever port Render gives us (falls back to 10000 locally)
CMD gunicorn -w 2 -b 0.0.0.0:${PORT:-10000} --timeout 300 app:app
