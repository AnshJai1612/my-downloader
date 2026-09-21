import os
import tempfile
import shutil
from flask import Flask, render_template, request, send_file, after_this_request, jsonify
import yt_dlp

app = Flask(__name__)

# Render mounts Secret Files at /etc/secrets/
RENDER_COOKIE_PATH = '/etc/secrets/cookies.txt'
LOCAL_COOKIE_PATH = 'cookies.txt'

def get_cookie_file():
    if os.path.exists(RENDER_COOKIE_PATH):
        return RENDER_COOKIE_PATH
    elif os.path.exists(LOCAL_COOKIE_PATH):
        return LOCAL_COOKIE_PATH
    return None

@app.route('/')
def home():
    return render_template('index.html')

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
        'extractor_args': {
            'youtube': {
                'player_client': ['mweb', 'android']
            }
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

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
