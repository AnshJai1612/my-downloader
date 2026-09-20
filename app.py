import os
import tempfile
from flask import Flask, render_template, request, send_file, after_this_request, jsonify
import yt_dlp

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/download', methods=['GET'])
def download():
    url = request.args.get('url')
    
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    # Create temporary directory to hold file during processing
    temp_dir = tempfile.mkdtemp()

    # yt-dlp config: Fetch up to 1080p video + best audio, then merge using FFmpeg
    ydl_opts = {
        'format': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Ensure proper .mp4 output extension post-merge
            base, _ = os.path.splitext(filename)
            filepath = base + '.mp4'

            if not os.path.exists(filepath):
                filepath = filename

        # Clean up temporary server files after file transfer completes
        @after_this_request
        def remove_file(response):
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
            except Exception as e:
                app.logger.error(f"Error deleting temp files: {e}")
            return response

        return send_file(
            filepath,
            as_attachment=True,
            download_name=os.path.basename(filepath)
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Dynamically read PORT assigned by Render, default to 10000 for local testing
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
