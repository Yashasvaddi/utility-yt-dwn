from pathlib import Path
import os
import shutil
import tarfile
import urllib.request

import streamlit as st
import yt_dlp


# ============================================================
# CONFIG
# ============================================================

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

NODE_VERSION = "22.23.2"

NODE_BASE_DIR = Path.home() / ".local"
NODE_DIR = NODE_BASE_DIR / f"node-v{NODE_VERSION}"
NODE_BIN = NODE_DIR / "bin" / "node"

# Player clients to try, in order. Some clients need PO Tokens
# far less often than the default "web" client, so falling back
# through this list resolves a lot of 403s that aren't caused
# by an outright IP block.
PLAYER_CLIENT_FALLBACKS = [
    ["tv", "web_safari"],
    ["android", "web"],
    ["ios"],
    ["mweb"],
]


# ============================================================
# NODE.JS SETUP
# ============================================================

def ensure_node() -> Path:
    """
    Find an existing Node.js installation or install the
    official Node.js binary locally.
    """

    system_node = shutil.which("node")

    if system_node:
        return Path(system_node)

    if NODE_BIN.exists():
        return NODE_BIN

    NODE_BASE_DIR.mkdir(parents=True, exist_ok=True)

    archive_name = f"node-v{NODE_VERSION}-linux-x64.tar.xz"
    archive_path = NODE_BASE_DIR / archive_name

    download_url = (
        f"https://nodejs.org/dist/v{NODE_VERSION}/{archive_name}"
    )

    with st.spinner("Setting up Node.js..."):

        if not archive_path.exists():
            urllib.request.urlretrieve(download_url, archive_path)

        with tarfile.open(archive_path, "r:xz") as tar:
            tar.extractall(path=NODE_BASE_DIR, filter="data")

        extracted_dir = NODE_BASE_DIR / f"node-v{NODE_VERSION}-linux-x64"

        if extracted_dir.exists() and not NODE_DIR.exists():
            extracted_dir.rename(NODE_DIR)

        archive_path.unlink(missing_ok=True)

    if not NODE_BIN.exists():
        raise RuntimeError("Node.js installation failed.")

    return NODE_BIN


def setup_node():
    node_path = ensure_node()
    node_dir = str(node_path.parent)
    current_path = os.environ.get("PATH", "")

    if node_dir not in current_path.split(os.pathsep):
        os.environ["PATH"] = f"{node_dir}{os.pathsep}{current_path}"

    return node_path


# ============================================================
# OPTIONAL: COOKIES + PROXY (from Streamlit secrets)
# ============================================================
#
# Add these to .streamlit/secrets.toml if you have them:
#
#   YTDLP_COOKIES = """
#   # Netscape HTTP Cookie File contents here
#   """
#   YTDLP_PROXY = "http://user:pass@residential-proxy-host:port"
#
# Cookies help with "sign in to confirm you're not a bot" gating.
# A proxy is the only real fix if YouTube is blocking this app's
# IP outright (very common on shared cloud hosts).

def get_cookiefile() -> Path | None:
    cookies_text = st.secrets.get("YTDLP_COOKIES") if hasattr(st, "secrets") else None

    if not cookies_text:
        return None

    cookie_path = Path("cookies.txt")
    cookie_path.write_text(cookies_text)
    return cookie_path


def get_proxy() -> str | None:
    if hasattr(st, "secrets"):
        return st.secrets.get("YTDLP_PROXY")
    return None


# ============================================================
# DOWNLOAD FUNCTION
# ============================================================

def download_media(
    url: str,
    media_format: str,
    progress_bar,
    status_text,
    log_lines: list,
    player_clients: list[str],
):
    """
    Download a YouTube video as MP3 or MP4, trying a specific
    player client set. Raises on failure so the caller can try
    the next fallback.
    """

    def progress_hook(data):

        if data.get("status") == "downloading":

            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            downloaded = data.get("downloaded_bytes", 0)

            if total:
                progress = min(downloaded / total, 1.0)
                progress_bar.progress(progress)
                percentage = progress * 100

                speed = data.get("speed")
                speed_text = (
                    f"{speed / (1024 * 1024):.2f} MB/s" if speed else "Calculating..."
                )

                downloaded_mb = downloaded / (1024 * 1024)
                total_mb = total / (1024 * 1024)

                status_text.write(
                    f"**{percentage:.1f}%** • "
                    f"{downloaded_mb:.1f} / {total_mb:.1f} MB • "
                    f"{speed_text}"
                )

        elif data.get("status") == "finished":
            progress_bar.progress(1.0)
            status_text.write("Processing file...")

    def logger_debug(msg):
        log_lines.append(msg)

    class _Logger:
        def debug(self, msg):
            log_lines.append(msg)

        def warning(self, msg):
            log_lines.append(f"WARNING: {msg}")

        def error(self, msg):
            log_lines.append(f"ERROR: {msg}")

    common_opts = {
        "js_runtimes": {"node": {}},
        "outtmpl": str(DOWNLOAD_DIR / "%(title).80B.%(ext)s"),
        "noplaylist": True,
        "progress_hooks": [progress_hook],
        "logger": _Logger(),
        "quiet": True,
        "no_warnings": False,
        "extractor_args": {"youtube": {"player_client": player_clients}},
    }

    cookiefile = get_cookiefile()
    if cookiefile:
        common_opts["cookiefile"] = str(cookiefile)

    proxy = get_proxy()
    if proxy:
        common_opts["proxy"] = proxy

    if media_format == "MUSIC":
        ydl_opts = {
            **common_opts,
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }
            ],
        }
    else:
        ydl_opts = {
            **common_opts,
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        original_filepath = Path(ydl.prepare_filename(info))

    if media_format == "MUSIC":
        filepath = original_filepath.with_suffix(".mp3")
    else:
        filepath = original_filepath.with_suffix(".mp4")

    return filepath


def download_with_fallbacks(url, media_format, progress_bar, status_text, log_lines):
    """
    Try each player-client fallback in turn until one works.
    Returns (filepath, client_used) or raises the last error.
    """

    last_error = None

    for clients in PLAYER_CLIENT_FALLBACKS:

        status_text.write(f"Trying player client: `{', '.join(clients)}`...")
        log_lines.append(f"--- Attempting clients: {clients} ---")

        try:
            filepath = download_media(
                url, media_format, progress_bar, status_text, log_lines, clients
            )
            return filepath, clients

        except Exception as e:
            last_error = e
            log_lines.append(f"Failed with clients {clients}: {e}")
            continue

    raise last_error


# ============================================================
# STREAMLIT CONFIG
# ============================================================

st.set_page_config(
    page_title="YouTube Downloader",
    page_icon="🎵",
    layout="centered",
)


# ============================================================
# UI
# ============================================================

st.title("YouTube Downloader")
st.caption("Download YouTube videos as MP3 or MP4.")

url = st.text_input(
    "YouTube URL",
    placeholder="Paste a YouTube link here...",
)

format_choice = st.radio(
    "Download as",
    ["MUSIC", "VIDEO"],
    horizontal=True,
)

if st.button(
    f"Download {format_choice}",
    type="primary",
    use_container_width=True,
):

    clean_url = url.strip()

    if not clean_url:
        st.error("Please enter a YouTube URL.")

    elif "youtube.com/" not in clean_url and "youtu.be/" not in clean_url:
        st.error("Please enter a valid YouTube URL.")

    else:

        progress_bar = st.progress(0)
        status_text = st.empty()
        log_lines: list = []

        try:

            with st.spinner("Preparing downloader..."):
                node_path = setup_node()

            status_text.write(f"Using Node.js: `{node_path}`")

            with st.spinner(f"Downloading {format_choice}..."):
                filepath, client_used = download_with_fallbacks(
                    clean_url, format_choice, progress_bar, status_text, log_lines
                )

            if not filepath.exists():
                raise FileNotFoundError(f"Downloaded file was not found: {filepath}")

            if filepath.stat().st_size == 0:
                raise RuntimeError("Downloaded file is empty.")

            progress_bar.progress(1.0)
            status_text.success(f"Download ready! (client: {', '.join(client_used)})")

            with open(filepath, "rb") as file:
                st.download_button(
                    label=f"⬇️ Save {format_choice}",
                    data=file,
                    file_name=filepath.name,
                    mime="audio/mpeg" if format_choice == "MUSIC" else "video/mp4",
                    use_container_width=True,
                )

        except Exception as e:

            progress_bar.empty()
            status_text.empty()

            error_str = str(e)

            # Give a targeted hint based on what actually failed
            if "403" in error_str:
                hint = (
                    "All player clients returned 403. This usually means YouTube "
                    "is blocking this server's IP address outright (common on "
                    "shared cloud hosts). A residential/rotating proxy "
                    "(`YTDLP_PROXY` secret) is the most reliable fix. Cookies "
                    "alone will not resolve a pure IP block."
                )
            elif "Sign in to confirm" in error_str or "not a bot" in error_str:
                hint = (
                    "YouTube is asking for bot verification. Add a fresh "
                    "`YTDLP_COOKIES` secret (exported from a logged-in browser "
                    "session) and try again."
                )
            elif "PO Token" in error_str or "po_token" in error_str.lower():
                hint = (
                    "A PO Token is required for the clients that were tried. "
                    "Check the yt-dlp PO Token provider plugin docs, or rely on "
                    "the `tv`/`web_safari` clients which usually need it less."
                )
            else:
                hint = None

            st.error(f"Download failed: {e}")

            if hint:
                st.warning(hint)

            with st.expander("Show diagnostic log"):
                st.code("\n".join(log_lines[-200:]) or "No log captured.")