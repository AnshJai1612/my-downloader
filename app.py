import os
import tempfile
import shutil
from flask import Flask, render_template, request, send_file, after_this_request, jsonify
import yt_dlp

app = Flask(__name__)

RENDER_COOKIE_PATH = '/etc/secrets/cookies.txt'
LOCAL_COOKIE_PATH = 'cookies.txt'

def get_cookie_file():
    if os.path.exists(RENDER_COOKIE_PATH):
        return RENDER_COOKIE_PATH
    elif os.path.exists(LOCAL_COOKIE_PATH):
        return LOCAL_COOKIE_PATH
    return None

@app.route('/download', methods=['GET'])
def download():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Please provide a valid video URL.'}), 400

    temp_dir = tempfile.mkdtemp()
    cookie_file = get_cookie_file()

    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'restrictfilenames': True,
        # Force player clients that bypass standard web bot detection
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'mweb'],
                'skip': ['hls', 'dash']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }

    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            base, _ = os.path.splitext(filename)
            filepath = base + '.mp4'

            if not os.path.exists(filepath):
                filepath = filename

        @after_this_request
        def cleanup(response):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                app.logger.error(f"Cleanup error: {e}")
            return response

        return send_file(
            filepath,
            as_attachment=True,
            download_name=os.path.basename(filepath),
            mimetype='video/mp4'
        )

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return jsonify({'error': str(e)}), 500
