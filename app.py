```python
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    send_file,
    after_this_request,
    jsonify,
)

import yt_dlp


# ============================================================
# APP
# ============================================================

app = Flask(__name__)

# Maximum number of songs allowed in a custom queue
MAX_SONGS = 25

# Maximum URL length accepted
MAX_URL_LENGTH = 2048


# ============================================================
# RUNTIME / DEPENDENCY DETECTION
# ============================================================

def find_deno():
    """
    Find Deno in common locations used by Render/Docker/Linux.

    Current yt-dlp recommends Deno for YouTube JavaScript
    challenge solving.
    """

    possible_paths = [
        os.environ.get("DENO_PATH"),
        os.environ.get("DENO_INSTALL", "") + "/bin/deno",
        "/root/.deno/bin/deno",
        "/opt/render/project/.deno/bin/deno",
        "/usr/local/bin/deno",
        "/usr/bin/deno",
    ]

    for path in possible_paths:
        if not path:
            continue

        path = os.path.expanduser(path)

        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    # If Deno is already in PATH, yt-dlp can use it automatically.
    return "deno"


DENO_PATH = find_deno()


# ============================================================
# LOGGING
# ============================================================

def yt_progress_hook(data):
    """
    Lightweight download progress logging.
    """

    status = data.get("status")

    if status == "downloading":
        filename = data.get("filename", "unknown")
        percent = data.get("_percent_str", "?")
        speed = data.get("_speed_str", "?")
        eta = data.get("_eta_str", "?")

        print(
            f"[yt-dlp] {percent} | "
            f"{speed} | ETA {eta} | "
            f"{os.path.basename(filename)}",
            flush=True,
        )

    elif status == "finished":
        filename = data.get("filename", "unknown")
        print(
            f"[yt-dlp] Download finished: {os.path.basename(filename)}",
            flush=True,
        )


# ============================================================
# COMMON YT-DLP OPTIONS
# ============================================================

def base_ydl_options():
    """
    Options shared by every yt-dlp request.

    IMPORTANT:
    Do not use cookies from your personal browser/account here.
    This service is designed to run without your personal session.
    """

    options = {
        # Current yt-dlp YouTube extraction uses EJS + JS runtime.
        "js_runtimes": {
            "deno": DENO_PATH,
        },

        # Networking
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,

        # Don't stop the entire download because one fragment failed.
        "skip_unavailable_fragments": True,

        # Safer filenames for Linux/Render.
        "restrictfilenames": True,

        # Don't create unnecessary playlists.
        "noplaylist": True,

        # Progress
        "progress_hooks": [yt_progress_hook],

        # Keep useful logs in Render.
        "quiet": False,
        "no_warnings": False,

        # Avoid interactive prompts on a server.
        "no_color": True,

        # HTTP headers that look like a normal browser request.
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },

        # Don't use a personal cookie file.
        "cookiefile": None,
    }

    return options


# ============================================================
# YOUTUBE OPTIONS
# ============================================================

def add_youtube_options(options):
    """
    Add YouTube-specific configuration.

    web_embedded is included as an additional client because
    current yt-dlp versions document it as a useful fallback
    for logged-out extraction.

    The normal/default client remains available.
    """

    options["extractor_args"] = {
        "youtube": {
            "player_client": ["default", "web_embedded"],
        }
    }

    return options


# ============================================================
# URL VALIDATION
# ============================================================

def is_youtube_url(url):
    """
    Basic YouTube URL validation.
    """

    if not url:
        return False

    url = url.strip()

    patterns = [
        r"^https?://(www\.)?youtube\.com/",
        r"^https?://youtu\.be/",
        r"^https?://(www\.)?youtube-nocookie\.com/",
    ]

    return any(re.match(pattern, url, re.IGNORECASE) for pattern in patterns)


def clean_url(url):
    """
    Remove accidental whitespace.
    """

    if not isinstance(url, str):
        return ""

    return url.strip()


# ============================================================
# TEMP DIRECTORY CLEANUP
# ============================================================

def cleanup_directory(path):
    """
    Safely remove a temporary directory.
    """

    if not path:
        return

    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception as exc:
        print(
            f"[cleanup] Failed to remove temporary directory: {exc}",
            flush=True,
        )


# ============================================================
# FILE FINDING
# ============================================================

def find_downloaded_file(directory, preferred_extension=None):
    """
    Find the actual file produced by yt-dlp/FFmpeg.

    yt-dlp's final extension may differ from prepare_filename()
    after post-processing, so we search the directory instead
    of assuming a filename.
    """

    directory = Path(directory)

    if not directory.exists():
        return None

    files = [
        path
        for path in directory.rglob("*")
        if path.is_file()
    ]

    if not files:
        return None

    if preferred_extension:
        preferred = [
            path
            for path in files
            if path.suffix.lower() == preferred_extension.lower()
        ]

        if preferred:
            return max(
                preferred,
                key=lambda p: p.stat().st_mtime,
            )

    return max(
        files,
        key=lambda p: p.stat().st_mtime,
    )


# ============================================================
# ERROR CLEANING
# ============================================================

def friendly_ytdlp_error(error):
    """
    Turn yt-dlp exceptions into something useful for the frontend
    without hiding the actual underlying problem.
    """

    message = str(error).strip()

    if not message:
        return "The download failed for an unknown reason."

    lower = message.lower()

    if "failed to extract any player response" in lower:
        return (
            "YouTube did not return a usable player response. "
            "The server may need the latest yt-dlp/EJS components, "
            "or YouTube may be temporarily blocking the server."
        )

    if "sign in to confirm you're not a bot" in lower:
        return (
            "YouTube is requiring bot verification for this request. "
            "Try another video or try again later."
        )

    if "po token" in lower:
        return (
            "YouTube required a Proof-of-Origin token for this video. "
            "The current server configuration could not obtain one."
        )

    if "http error 403" in lower:
        return (
            "YouTube rejected the media request with HTTP 403. "
            "The requested format may require additional YouTube "
            "verification."
        )

    if "video unavailable" in lower:
        return "This YouTube video is unavailable."

    if "private video" in lower:
        return "This video is private and cannot be downloaded."

    if "age-restricted" in lower or "sign in to confirm your age" in lower:
        return "This video requires age verification."

    if "members-only" in lower:
        return "This video is available to channel members only."

    return message


# ============================================================
# SINGLE DOWNLOAD
# ============================================================

@app.route("/download", methods=["GET"])
def download_single():

    url = clean_url(request.args.get("url", ""))
    fmt = clean_url(request.args.get("format", "mp3")).lower()

    if not url:
        return jsonify({
            "error": "No URL provided."
        }), 400

    if len(url) > MAX_URL_LENGTH:
        return jsonify({
            "error": "URL is too long."
        }), 400

    if not is_youtube_url(url):
        return jsonify({
            "error": "Please provide a valid YouTube URL."
        }), 400

    if fmt not in {"mp3", "mp4", "video"}:
        fmt = "mp3"

    temp_dir = tempfile.mkdtemp(prefix="media_dl_")

    try:

        # ----------------------------------------------------
        # MP3
        # ----------------------------------------------------

        if fmt == "mp3":

            ydl_opts = base_ydl_options()
            ydl_opts = add_youtube_options(ydl_opts)

            ydl_opts.update({
                "format": (
                    "bestaudio[ext=m4a]/"
                    "bestaudio/"
                    "best"
                ),

                "outtmpl": os.path.join(
                    temp_dir,
                    "%(title)s.%(ext)s",
                ),

                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "320",
                    },
                    {
                        "key": "FFmpegMetadata",
                        "add_metadata": True,
                    },
                ],

                "postprocessor_args": {
                    "FFmpegMetadata": [
                        "-id3v2_version",
                        "3",
                    ],
                },
            })

            target_extension = ".mp3"

        # ----------------------------------------------------
        # VIDEO
        # ----------------------------------------------------

        else:

            ydl_opts = base_ydl_options()
            ydl_opts = add_youtube_options(ydl_opts)

            ydl_opts.update({
                "format": (
                    "bestvideo[height<=1080][ext=mp4]+"
                    "bestaudio[ext=m4a]/"
                    "bestvideo[height<=1080]+"
                    "bestaudio/"
                    "best[height<=1080]/"
                    "best"
                ),

                "outtmpl": os.path.join(
                    temp_dir,
                    "%(title)s.%(ext)s",
                ),

                "merge_output_format": "mp4",

                "postprocessor_args": {
                    "Merger": [
                        "-movflags",
                        "+faststart",
                    ],
                },
            })

            target_extension = ".mp4"

        print(
            f"[download] Starting {fmt} download: {url}",
            flush=True,
        )

        # ----------------------------------------------------
        # DOWNLOAD
        # ----------------------------------------------------

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(
                url,
                download=True,
            )

            if not info:
                raise RuntimeError(
                    "yt-dlp returned no video information."
                )

        # ----------------------------------------------------
        # FIND FINAL FILE
        # ----------------------------------------------------

        filepath = find_downloaded_file(
            temp_dir,
            target_extension,
        )

        if not filepath:
            raise RuntimeError(
                "Download completed but no output file was found."
            )

        print(
            f"[download] Final file: {filepath}",
            flush=True,
        )

        # ----------------------------------------------------
        # CLEANUP AFTER RESPONSE
        # ----------------------------------------------------

        @after_this_request
        def cleanup(response):
            cleanup_directory(temp_dir)
            return response

        return send_file(
            str(filepath),
            as_attachment=True,
            download_name=filepath.name,
        )

    except Exception as exc:

        print(
            f"[download] ERROR: {exc}",
            flush=True,
        )

        cleanup_directory(temp_dir)

        return jsonify({
            "error": friendly_ytdlp_error(exc),
            "details": str(exc),
        }), 500


# ============================================================
# CUSTOM QUEUE DOWNLOADER
# ============================================================

@app.route("/download-custom", methods=["POST"])
def download_custom():

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "Invalid JSON request."
        }), 400

    songs = data.get("songs", [])

    if not isinstance(songs, list):
        return jsonify({
            "error": "songs must be an array."
        }), 400

    # Remove empty values and normalize strings.
    songs = [
        str(song).strip()
        for song in songs
        if str(song).strip()
    ]

    if not songs:
        return jsonify({
            "error": "No songs provided."
        }), 400

    if len(songs) > MAX_SONGS:
        return jsonify({
            "error": f"Maximum {MAX_SONGS} songs per request."
        }), 400

    temp_dir = tempfile.mkdtemp(prefix="custom_dl_")

    music_folder = os.path.join(
        temp_dir,
        "Custom_MP3s",
    )

    os.makedirs(
        music_folder,
        exist_ok=True,
    )

    ydl_opts = base_ydl_options()
    ydl_opts = add_youtube_options(ydl_opts)

    ydl_opts.update({
        "format": (
            "bestaudio[ext=m4a]/"
            "bestaudio/"
            "best"
        ),

        "outtmpl": os.path.join(
            music_folder,
            "%(title)s.%(ext)s",
        ),

        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            },
            {
                "key": "FFmpegMetadata",
                "add_metadata": True,
            },
        ],

        "postprocessor_args": {
            "FFmpegMetadata": [
                "-id3v2_version",
                "3",
            ],
        },
    })

    successful = []
    failed = []

    try:

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            for index, song in enumerate(songs, 1):

                print(
                    f"[queue] [{index}/{len(songs)}] "
                    f"Searching: {song}",
                    flush=True,
                )

                try:

                    # Search YouTube rather than assuming the
                    # user supplied a URL.
                    result = ydl.extract_info(
                        f"ytsearch1:{song} Audio",
                        download=True,
                    )

                    if not result:
                        raise RuntimeError(
                            "YouTube returned no result."
                        )

                    successful.append(song)

                    print(
                        f"[queue] Success: {song}",
                        flush=True,
                    )

                except Exception as exc:

                    failed.append({
                        "song": song,
                        "error": friendly_ytdlp_error(exc),
                    })

                    print(
                        f"[queue] Failed: {song} | {exc}",
                        flush=True,
                    )

        # ----------------------------------------------------
        # FIND MP3 FILES
        # ----------------------------------------------------

        mp3_files = []

        for root, _, files in os.walk(music_folder):

            for filename in files:

                if filename.lower().endswith(".mp3"):

                    mp3_files.append(
                        os.path.join(root, filename)
                    )

        if not mp3_files:

            return jsonify({
                "error": "None of the requested songs could be downloaded.",
                "failed": failed,
            }), 500

        # ----------------------------------------------------
        # CREATE ZIP
        # ----------------------------------------------------

        zip_path = os.path.join(
            temp_dir,
            "Custom_Playlist.zip",
        )

        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zipf:

            for filepath in mp3_files:

                zipf.write(
                    filepath,
                    arcname=os.path.basename(filepath),
                )

        print(
            f"[queue] ZIP created: {zip_path}",
            flush=True,
        )

        # ----------------------------------------------------
        # CLEANUP AFTER RESPONSE
        # ----------------------------------------------------

        @after_this_request
        def cleanup(response):
            cleanup_directory(temp_dir)
            return response

        return send_file(
            zip_path,
            as_attachment=True,
            download_name="Custom_Playlist.zip",
        )

    except Exception as exc:

        print(
            f"[queue] ERROR: {exc}",
            flush=True,
        )

        cleanup_directory(temp_dir)

        return jsonify({
            "error": friendly_ytdlp_error(exc),
            "details": str(exc),
            "successful": successful,
            "failed": failed,
        }), 500


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health", methods=["GET"])
def health():

    try:
        version = yt_dlp.version.__version__
    except Exception:
        version = "unknown"

    return jsonify({
        "status": "ok",
        "yt_dlp": version,
        "deno": DENO_PATH,
    })


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint not found."
    }), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({
        "error": "Method not allowed."
    }), 405


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "error": "Internal server error."
    }), 500


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000,
        )
    )

    app.run(
        debug=False,
        host="0.0.0.0",
        port=port,
    )
```
