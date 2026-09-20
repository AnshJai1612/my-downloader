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

# Hugging Face Spaces default port
EXPOSE 7860

# Run Gunicorn on port 7860 with a 5-minute timeout
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:7860", "--timeout", "300", "app:app"]