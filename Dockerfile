FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV DENO_INSTALL=/root/.deno
ENV PATH="/root/.deno/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deno.land/install.sh | sh

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir "yt-dlp[default]" flask gunicorn

COPY . .

RUN python -c "import yt_dlp; print('yt-dlp:', yt_dlp.version.__version__)"
RUN deno --version
RUN ffmpeg -version

CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "app:app"]
