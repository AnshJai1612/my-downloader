import os
import shutil
import tempfile
import threading
import uuid
import zipfile
from flask import Flask, render_template, request, send_file, after_this_request, jsonify
import yt_dlp

app = Flask(__name__)

# In-memory store for tracking single download task progress
progress_store = {}


def write_cookie_file():
    """Extracts YOUTUBE_COOKIES from environment variables and writes to a temp file."""
    cookies_env = os.environ.get('YOUTUBE_COOKIES')
    if not cookies_env:
        return None

    cookies_env = cookies_env.strip()
    # Add Netscape header if missing
    if not cookies_env.startswith('# Netscape'):
        cookies_env = "# Netscape HTTP Cookie File\n" + cookies_env

    cookie_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
    cookie_file.write(cookies_env)
    cookie_file.close()
    return cookie_file.name


@app.route('/')
def home():
    return render_template('index.html')


# ==========================================
# 1. PLAYLIST & METADATA EXTRACTION ROUTE
# ==========================================
@app.route('/parse', methods=['POST'])
def parse_url():
    data = request.get_json() or {}
    url = data.get('url')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    cookie_path = write_cookie_file()
    ydl_opts = {
        'extract_flat': 'in_playlist',
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
    }
    if cookie_path:
        ydl_opts['cookiefile'] = cookie_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            tracks = []
            if 'entries' in info:
                title = info.get('title', 'Custom Playlist')
                for idx, entry in enumerate(info['entries']):
                    if entry:
                        entry_url = entry.get('url') or ''
                        if not entry_url.startswith('http'):
                            entry_url = f"https://www.youtube.com/watch?v={entry.get('id')}"

                        tracks.append({
                            'id': entry.get('id'),
                            'url': entry_url,
                            'title': entry.get('title', f"Track {idx + 1}"),
                            'duration': entry.get('duration')
                        })
            else:
                title = info.get('title', 'Single Track')
                tracks.append({
                    'id': info.get('id'),
                    'url': info.get('webpage_url', url),
                    'title': title,
                    'duration': info.get('duration')
                })

            return jsonify({
                'playlist_title': title,
                'is_playlist': 'entries' in info,
                'tracks': tracks
            })

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cookie_path and os.path.exists(cookie_path):
            os.remove(cookie_path)


# ==========================================
# 2. BATCH PLAYLIST DOWNLOAD (ZIP / FILES)
# ==========================================
@app.route('/download_batch', methods=['POST'])
def download_batch():
    data = request.form
    urls = request.form.getlist('urls')
    fmt = data.get('format', 'mp3')
    custom_title = data.get('playlist_title', 'playlist').strip() or 'playlist'

    if not urls:
        return jsonify({'error': 'No tracks selected'}), 400

    temp_dir = tempfile.mkdtemp()
    cookie_path = write_cookie_file()

    if fmt == 'mp3':
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'},
                {'key': 'FFmpegMetadata', 'add_metadata': True},
            ],
            'restrictfilenames': True,
            'quiet': True,
        }
        target_ext = '.mp3'
    else:
        ydl_opts = {
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
            'restrictfilenames': True,
            'quiet': True,
        }
        target_ext = '.mp4'

    if cookie_path:
        ydl_opts['cookiefile'] = cookie_path

    try:
        downloaded_files = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for track_url in urls:
                try:
                    info = ydl.extract_info(track_url, download=True)
                    filename = ydl.prepare_filename(info)
                    base, _ = os.path.splitext(filename)
                    final_path = base + target_ext
                    
                    if os.path.exists(final_path):
                        downloaded_files.append(final_path)
                    elif os.path.exists(filename):
                        downloaded_files.append(filename)
                except Exception as inner_e:
                    app.logger.error(f"Failed track: {track_url} - {inner_e}")

        if not downloaded_files:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return jsonify({'error': 'Failed to process any of the selected tracks'}), 500

        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                app.logger.error(f"Error removing temp dir: {e}")
            return response

        # Deliver single file directly
        if len(downloaded_files) == 1:
            return send_file(
                downloaded_files[0],
                as_attachment=True,
                download_name=os.path.basename(downloaded_files[0])
            )

        # Zip multiple files
        zip_path = os.path.join(temp_dir, f"{custom_title}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file in downloaded_files:
                zipf.write(file, arcname=os.path.basename(file))

        return send_file(
            zip_path,
            as_attachment=True,
            download_name=f"{custom_title}.zip"
        )

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({'error': str(e)}), 500
    finally:
        if cookie_path and os.path.exists(cookie_path):
            os.remove(cookie_path)


# ==========================================
# 3. SINGLE MEDIA DOWNLOAD WITH PROGRESS TRACKING
# ==========================================
def process_download(task_id, url, quality):
    temp_dir = tempfile.mkdtemp()
    cookie_path = write_cookie_file()

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

    if cookie_path:
        ydl_opts['cookiefile'] = cookie_path

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
        if cookie_path and os.path.exists(cookie_path):
            os.remove(cookie_path)


@app.route('/api/start', methods=['POST'])
def start_download():
    data = request.get_json() or {}
    url = data.get('url')
    quality = data.get('quality', '720')
    
    if not url:
        return jsonify({'error': 'Please provide a valid video URL.'}), 400

    task_id = str(uuid.uuid4())
    progress_store[task_id] = {'status': 'starting', 'percent': 0}
    
    thread = threading.Thread(target=process_download, args=(task_id, url, quality))
    thread.daemon = True
    thread.start()

    return jsonify({'task_id': task_id})


@app.route('/api/progress/<task_id>')
def get_progress(task_id):
    task = progress_store.get(task_id)
    if not task:
        return jsonify({'status': 'error', 'error': 'Task expired or invalid.'})
    
    return jsonify({
        'status': task.get('status'),
        'percent': task.get('percent', 0),
        'error': task.get('error')
    })


@app.route('/api/get_file/<task_id>')
def get_file(task_id):
    task = progress_store.get(task_id)
    if not task or task.get('status') != 'ready':
        return jsonify({'error': 'File not ready.'}), 400

    filepath = task['filepath']
    temp_dir = task['temp_dir']
    mimetype = task['mimetype']
    download_name = task['download_name']

    @after_this_request
    def cleanup(response):
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as cleanup_err:
            app.logger.error(f"Cleanup error: {cleanup_err}")
        finally:
            if task_id in progress_store:
                del progress_store[task_id]
        return response

    return send_file(
        filepath,
        as_attachment=True,
        download_name=download_name,
        mimetype=mimetype
    )


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
