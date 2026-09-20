import os
import tempfile
import shutil
import zipfile
from flask import Flask, render_template, request, send_file, after_this_request, jsonify
import yt_dlp

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

# Single Link Downloader (Video or MP3)
@app.route('/download', methods=['GET'])
def download_single():
    url = request.args.get('url')
    fmt = request.args.get('format', 'mp3')
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    temp_dir = tempfile.mkdtemp()

    # Base options with YouTube OAuth2 enabled
    ydl_opts = {
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'restrictfilenames': True,
        'quiet': False,  # Must stay False to see OAuth code in server logs
        'username': 'oauth2',
        'password': '',
    }

    if fmt == 'mp3':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'},
                {'key': 'FFmpegMetadata', 'add_metadata': True},
            ],
            'postprocessor_args': {'FFmpegMetadata': ['-id3v2_version', '3']},
        })
        target_ext = '.mp3'
    else:
        # 1080p Video + Audio merging
        ydl_opts.update({
            'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best',
            'merge_output_format': 'mp4',
        })
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

# Custom Queue Downloader
@app.route('/download-custom', methods=['POST'])
def download_custom():
    data = request.get_json() or {}
    songs = data.get('songs', [])

    if not songs:
        return jsonify({'error': 'No songs provided'}), 400

    temp_dir = tempfile.mkdtemp()
    music_folder = os.path.join(temp_dir, 'Custom_MP3s')
    os.makedirs(music_folder, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(music_folder, '%(title)s.%(ext)s'),
        'postprocessors': [
            {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'},
            {'key': 'FFmpegMetadata', 'add_metadata': True},
        ],
        'postprocessor_args': {'FFmpegMetadata': ['-id3v2_version', '3']},
        'restrictfilenames': True,
        'quiet': False,  # Must stay False to see OAuth code in server logs
        'username': 'oauth2',
        'password': '',
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
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
