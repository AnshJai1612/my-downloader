import os
import tempfile
import shutil
import threading
import uuid
from flask import Flask, render_template, request, send_file, after_this_request, jsonify
import yt_dlp

app = Flask(__name__)
progress_store = {}

@app.route('/')
def home():
    return render_template('index.html')

def process_download(task_id, url, quality):
    temp_dir = tempfile.mkdtemp()
    cookie_file_path = None

    # Write YOUTUBE_COOKIES env var to a temporary file if present
    cookies_env = os.environ.get('YOUTUBE_COOKIES')
    if cookies_env:
        # Ensure Netscape header exists if missing
        if not cookies_env.startswith('# Netscape'):
            cookies_env = "# Netscape HTTP Cookie File\n" + cookies_env

        cookie_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        cookie_file.write(cookies_env)
        cookie_file.close()
        cookie_file_path = cookie_file.name

    def progress_hook(d):
        if task_id not in progress_store:
            return
            
        if d['status'] == 'downloading':
            pct = 0
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes', 0)
            
            if total and total > 0:
                pct = int((downloaded / total) * 100)
            elif d.get('fragment_count') and d.get('fragment_index'):
                pct = int((d['fragment_index'] / d['fragment_count']) * 100)
            
            current_pct = progress_store[task_id].get('percent', 0)
            progress_store[task_id]['percent'] = max(current_pct, min(pct, 95))
            progress_store[task_id]['status'] = 'downloading'
            
        elif d['status'] == 'finished':
            progress_store[task_id]['status'] = 'processing'
            progress_store[task_id]['percent'] = 98

    if quality == 'mp3':
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'writethumbnail': True,
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
                {'key': 'FFmpegMetadata', 'add_metadata': True},
                {'key': 'EmbedThumbnail'},
            ],
            'concurrent_fragment_downloads': 5,
            'progress_hooks': [progress_hook],
            'quiet': True,
            'no_warnings': True,
            'restrictfilenames': True,
        }
        expected_ext = '.mp3'
        mimetype = 'audio/mpeg'
    else:
        ydl_opts = {
            'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'concurrent_fragment_downloads': 5,
            'progress_hooks': [progress_hook],
            'quiet': True,
            'no_warnings': True,
            'restrictfilenames': True,
        }
        expected_ext = '.mp4'
        mimetype = 'video/mp4'

    # Pass cookie file to yt-dlp if it exists
    if cookie_file_path:
        ydl_opts['cookiefile'] = cookie_file_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            base, _ = os.path.splitext(filename)
            filepath = base + expected_ext

            if not os.path.exists(filepath):
                filepath = filename

        progress_store[task_id].update({
            'status': 'ready',
            'percent': 100,
            'filepath': filepath,
            'temp_dir': temp_dir,
            'mimetype': mimetype,
            'download_name': os.path.basename(filepath)
        })

    except Exception as e:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        progress_store[task_id] = {
            'status': 'error',
            'error': str(e)
        }
    finally:
        # Clean up temporary cookie file after download finishes
        if cookie_file_path and os.path.exists(cookie_file_path):
            os.remove(cookie_file_path)

# (Keep the rest of your app.route definitions below unchanged...)
