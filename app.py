import os
import shutil
import tempfile
import zipfile
from flask import Flask, render_template, request, send_file, after_this_request, jsonify
import yt_dlp

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/parse', methods=['POST'])
def parse_url():
    data = request.get_json() or {}
    url = data.get('url')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    ydl_opts = {
        'extract_flat': 'in_playlist',
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            tracks = []
            if 'entries' in info:
                title = info.get('title', 'Custom Playlist')
                for idx, entry in enumerate(info['entries']):
                    if entry:
                        tracks.append({
                            'id': entry.get('id') or entry.get('url'),
                            'url': entry.get('url') if entry.get('url', '').startswith('http') else f"https://www.youtube.com/watch?v={entry.get('id')}",
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

@app.route('/download_batch', methods=['POST'])
def download_batch():
    data = request.form
    urls = request.form.getlist('urls')
    fmt = data.get('format', 'mp3')
    custom_title = data.get('playlist_title', 'playlist').strip() or 'playlist'

    if not urls:
        return jsonify({'error': 'No tracks selected'}), 400

    temp_dir = tempfile.mkdtemp()

    if fmt == 'mp3':
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                },
                {
                    'key': 'FFmpegMetadata',
                    'add_metadata': True,
                },
            ],
            'postprocessor_args': {
                'FFmpegMetadata': ['-id3v2_version', '3']
            },
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

        # If single item, deliver file directly
        if len(downloaded_files) == 1:
            return send_file(
                downloaded_files[0],
                as_attachment=True,
                download_name=os.path.basename(downloaded_files[0])
            )

        # If multiple items, package into a ZIP archive
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

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
