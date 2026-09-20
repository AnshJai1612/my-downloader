import os
import tempfile
import shutil
import zipfile
from flask import Flask, render_template, request, send_file, after_this_request, jsonify
import yt_dlp

app = Flask(__name__)

# Performance & Anti-Throttle Configuration
FAST_YDL_OPTS = {
    'concurrent_fragment_downloads': 10,  # Downloads 10 stream chunks in parallel
    'http_chunk_size': 10485760,          # 10MB chunk size
    'restrictfilenames': True,
    'quiet': True,
    'noplaylist': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web']  # Bypasses YouTube web speed throttle
        }
    }
}

@app.route('/')
def home():
    return render_template('index.html')

# Single Link Downloader (1080p MP4 or MP3)
@app.route('/download', methods=['GET'])
def download_single():
    url = request.args.get('url')
    fmt = request.args.get('format', 'mp3')
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    temp_dir = tempfile.mkdtemp()

    if fmt == 'mp3':
        ydl_opts = {
            **FAST_YDL_OPTS,
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'},
                {'key': 'FFmpegMetadata', 'add_metadata': True},
            ],
            'postprocessor_args': {'FFmpegMetadata': ['-id3v2_version', '3']},
        }
        target_ext = '.mp3'
    else:
        # 1080p Video + Audio merging via FFmpeg
        ydl_opts = {
            **FAST_YDL_OPTS,
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'merge_output_format': 'mp4',
        }
        target_ext = '.mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            base, _ = os.path.splitext(filename)
            filepath = base + target_ext
            if not os.path.exists(filepath):
                filepath = filename

        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                print(f"Error removing temp dir: {e}")
            return response

        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({'error': str(e)}), 500

# Custom Queue / Playlist ZIP Downloader
@app.route('/download-custom', methods=['POST'])
def download_custom():
    data = request.get_json()
    songs = data.get('songs', [])
    
    if not songs:
        return jsonify({'error': 'No songs provided'}), 400

    temp_dir = tempfile.mkdtemp()
    music_folder = os.path.join(temp_dir, 'Custom_MP3s')
    os.makedirs(music_folder, exist_ok=True)

    ydl_opts = {
        **FAST_YDL_OPTS,
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(music_folder, '%(title)s.%(ext)s'),
        'postprocessors': [
            {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'},
            {'key': 'FFmpegMetadata', 'add_metadata': True},
        ],
        'postprocessor_args': {'FFmpegMetadata': ['-id3v2_version', '3']},
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            for idx, song in enumerate(songs, 1):
                print(f"[{idx}/{len(songs)}] Downloading: {song}")
                try:
                    ydl.download([f"ytsearch1:{song} Audio"])
                except Exception as e:
                    print(f"Failed to download '{song}': {e}")

        zip_path = os.path.join(temp_dir, 'Custom_Playlist.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(music_folder):
                for file in files:
                    if file.endswith('.mp3'):
                        zipf.write(os.path.join(root, file), file)

        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                print(f"Error cleaning temp folder: {e}")
            return response

        return send_file(zip_path, as_attachment=True, download_name='Custom_Playlist.zip')

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Binds dynamically to local port 5000 or Render's PORT environment variable
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
