from pathlib import Path
import os
import shutil
import socket
import subprocess
import tarfile
import time
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

# bgutil PO Token provider. The version here MUST match the
# `bgutil-ytdlp-pot-provider` pin in requirements.txt so the
# plugin and the server speak the same protocol.
BGUTIL_VERSION = "1.3.1"
BGUTIL_DIR = Path.home() / "bgutil-ytdlp-pot-provider"
BGUTIL_SERVER_DIR = BGUTIL_DIR / "server"
BGUTIL_BUILD_MAIN = BGUTIL_SERVER_DIR / "build" / "main.js"
POT_HOST = "127.0.0.1"
POT_PORT = 4416  # bgutil's default; the pip plugin auto-discovers this.

# Player clients to try, in order. With the PO Token server
# running, the web-family clients (web_safari / web / mweb) get
# their GVS tokens automatically and yield the best formats, so
# they go first. `tv` streams HLS that needs no GVS token, so it
# stays as a last-ditch fallback.
PLAYER_CLIENT_FALLBACKS = [
    ["web_safari", "web"],
    ["mweb"],
    ["android"],
    ["tv"],
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
# PO TOKEN PROVIDER (bgutil) SETUP
# ============================================================
#
# YouTube's newer clients require a GVS PO Token for their media
# (DASH) URLs. Without it, format listing succeeds but the actual
# byte download 403s. Tokens are now bound to the video id, so a
# provider that mints them on demand is the only workable path.
#
# We build bgutil's HTTP server once (cached), start it on port
# 4416 (cached), and the pip-installed `bgutil-ytdlp-pot-provider`
# plugin auto-discovers it there — no extractor-args needed.

def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


@st.cache_resource(show_spinner="Building PO Token provider (one-time, ~1-2 min)...")
def ensure_bgutil_built(node_bin_dir: str) -> str:
    """
    Clone + transpile the bgutil POT server. Cached, so it only
    runs once per app boot. Returns the path to build/main.js.
    """

    npm = str(Path(node_bin_dir) / "npm")
    npx = str(Path(node_bin_dir) / "npx")

    if not BGUTIL_BUILD_MAIN.exists():

        if not BGUTIL_DIR.exists():
            subprocess.run(
                [
                    "git", "clone", "--single-branch",
                    "--branch", BGUTIL_VERSION,
                    "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git",
                    str(BGUTIL_DIR),
                ],
                check=True, capture_output=True, text=True,
            )

        # npm ci installs devDependencies (incl. typescript) which
        # npx tsc then uses to transpile the server into build/.
        subprocess.run(
            [npm, "ci"],
            cwd=str(BGUTIL_SERVER_DIR),
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            [npx, "tsc"],
            cwd=str(BGUTIL_SERVER_DIR),
            check=True, capture_output=True, text=True,
        )

    if not BGUTIL_BUILD_MAIN.exists():
        raise RuntimeError("bgutil build did not produce server/build/main.js")

    return str(BGUTIL_BUILD_MAIN)


@st.cache_resource(show_spinner="Starting PO Token provider...")
def start_pot_server(node_bin: str, build_main: str) -> str:
    """
    Start the bgutil HTTP server once and keep it alive across
    Streamlit reruns. Returns the base URL. The child process
    survives even though we don't hold the handle; the port guard
    prevents duplicate starts on rerun.
    """

    if not _port_open(POT_HOST, POT_PORT):

        subprocess.Popen(
            [node_bin, build_main, "--port", str(POT_PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait up to ~10s for the server to accept connections.
        for _ in range(40):
            if _port_open(POT_HOST, POT_PORT):
                break
            time.sleep(0.25)
        else:
            raise RuntimeError(
                f"PO Token server did not come up on {POT_HOST}:{POT_PORT}"
            )

    return f"http://{POT_HOST}:{POT_PORT}"


def setup_pot_provider(node_path: Path) -> tuple[bool, str | None]:
    """
    Best-effort: build + start the POT provider. On failure the app
    still runs (client fallback + cookies only), just without GVS
    tokens. Returns (ready, error_message).
    """

    try:
        build_main = ensure_bgutil_built(str(node_path.parent))
        start_pot_server(str(node_path), build_main)
        return True, None
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()[-500:]
        return False, f"{e} :: {detail}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


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
# Cookies clear the "sign in to confirm you're not a bot" gate.
# A residential proxy is the only reliable fix when YouTube blocks
# the host's IP outright — the usual situation on Streamlit Cloud's
# shared datacenter IPs. Note that cookies exported from your home
# browser can get invalidated quickly when replayed from a
# datacenter IP, so treat the proxy as the durable fallback.

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

        except Exception as e:  # noqa: BLE001
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

            # Best-effort PO Token provider. If it fails to build or
            # start, we carry on without GVS tokens.
            pot_ready, pot_error = setup_pot_provider(node_path)

            if pot_ready:
                status_text.write("PO Token provider: **running** on port 4416")
                log_lines.append("PO Token provider: running on 127.0.0.1:4416")
            else:
                st.warning(
                    "PO Token provider could not start — continuing without GVS "
                    "tokens. web/mweb clients may 403 on media; the `tv` fallback "
                    "may still work at reduced quality. See the diagnostic log."
                )
                log_lines.append(f"PO Token provider FAILED: {pot_error}")

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

        except Exception as e:  # noqa: BLE001

            progress_bar.empty()
            status_text.empty()

            error_str = str(e)

            # Give a targeted hint based on what actually failed.
            if "Sign in to confirm" in error_str or "not a bot" in error_str:
                hint = (
                    "YouTube is asking for bot verification. Add a fresh "
                    "`YTDLP_COOKIES` secret (exported from a logged-in browser "
                    "session) and try again. On a datacenter IP these cookies can "
                    "expire fast — a residential `YTDLP_PROXY` is the durable fix."
                )
            elif "PO Token" in error_str or "po_token" in error_str.lower():
                hint = (
                    "A GVS PO Token was required but not supplied — the provider "
                    "likely isn't running. Check the diagnostic log for the bgutil "
                    "build/start error, and confirm `bgutil-ytdlp-pot-provider` is "
                    "in requirements.txt (version matching BGUTIL_VERSION)."
                )
            elif "403" in error_str:
                hint = (
                    "Every client 403'd even with the PO Token provider up. This is "
                    "the signature of a hard IP block on the media servers — common "
                    "on Streamlit Cloud's shared GCP IPs. A residential/rotating "
                    "proxy (`YTDLP_PROXY` secret) is the reliable fix here; cookies "
                    "and PO tokens alone won't clear a pure IP block."
                )
            else:
                hint = None

            st.error(f"Download failed: {e}")

            if hint:
                st.warning(hint)

            with st.expander("Show diagnostic log"):
                st.code("\n".join(log_lines[-200:]) or "No log captured.")