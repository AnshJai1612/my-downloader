#!/usr/bin/env bash

set -e

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Installing Deno ==="
curl -fsSL https://deno.land/install.sh | sh

export DENO_INSTALL="$HOME/.deno"
export PATH="$DENO_INSTALL/bin:$PATH"

echo "=== Deno version ==="
deno --version

echo "=== yt-dlp version ==="
yt-dlp --version

echo "=== Testing yt-dlp EJS ==="
python -c "import yt_dlp; print('yt-dlp:', yt_dlp.version.__version__)"

echo "=== Build complete ==="
