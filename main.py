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


# ============================================================
# NODE.JS SETUP
# ============================================================

def ensure_node() -> Path:
    """
    Find an existing Node.js installation or install the
    official Node.js binary locally.
    """

    # 1. Check system Node.js
    system_node = shutil.which("node")

    if system_node:
        return Path(system_node)

    # 2. Check cached local installation
    if NODE_BIN.exists():
        return NODE_BIN

    NODE_BASE_DIR.mkdir(parents=True, exist_ok=True)

    archive_name = f"node-v{NODE_VERSION}-linux-x64.tar.xz"
    archive_path = NODE_BASE_DIR / archive_name

    download_url = (
        f"https://nodejs.org/dist/v{NODE_VERSION}/{archive_name}"
    )

    with st.spinner("Setting up Node.js..."):

        # Download
        if not archive_path.exists():
            urllib.request.urlretrieve(
                download_url,
                archive_path,
            )

        # Extract
        with tarfile.open(archive_path, "r:xz") as tar:
            tar.extractall(
                path=NODE_BASE_DIR,
                filter="data",
            )

        extracted_dir = (
            NODE_BASE_DIR
            / f"node-v{NODE_VERSION}-linux-x64"
        )

        # Rename to predictable directory
        if extracted_dir.exists() and not NODE_DIR.exists():
            extracted_dir.rename(NODE_DIR)

        # Remove archive
        archive_path.unlink(missing_ok=True)

    if not NODE_BIN.exists():
        raise RuntimeError(
            "Node.js installation failed."
        )

    return NODE_BIN


def setup_node():
    """
    Configure Node.js for yt-dlp.
    """

    node_path = ensure_node()

    node_dir = str(node_path.parent)

    current_path = os.environ.get("PATH", "")

    if node_dir not in current_path.split(os.pathsep):
        os.environ["PATH"] = (
            f"{node_dir}{os.pathsep}{current_path}"
        )

    return node_path


# ============================================================
# DOWNLOAD FUNCTION
# ============================================================

def download_media(
    url: str,
    media_format: str,
    progress_bar,
    status_text,
):
    """
    Download a YouTube video as MP3 or MP4.
    """

    # --------------------------------------------------------
    # Progress hook
    # --------------------------------------------------------

    def progress_hook(data):

        if data.get("status") == "downloading":

            total = (
                data.get("total_bytes")
                or data.get("total_bytes_estimate")
            )

            downloaded = data.get(
                "downloaded_bytes",
                0,
            )

            if total:

                progress = min(
                    downloaded / total,
                    1.0,
                )

                progress_bar.progress(progress)

                percentage = progress * 100

                # Speed
                speed = data.get("speed")

                if speed:
                    speed_mb = (
                        speed / (1024 * 1024)
                    )

                    speed_text = (
                        f"{speed_mb:.2f} MB/s"
                    )
                else:
                    speed_text = "Calculating..."

                # Size
                downloaded_mb = (
                    downloaded / (1024 * 1024)
                )

                total_mb = (
                    total / (1024 * 1024)
                )

                status_text.write(
                    f"**{percentage:.1f}%** • "
                    f"{downloaded_mb:.1f} / "
                    f"{total_mb:.1f} MB • "
                    f"{speed_text}"
                )

        elif data.get("status") == "finished":

            progress_bar.progress(1.0)

            status_text.write(
                "Processing file..."
            )

    # --------------------------------------------------------
    # yt-dlp options
    # --------------------------------------------------------

    common_opts = {

        # YouTube JS challenge solving
        "js_runtimes": {
            "node": {},
        },

        # Output
        "outtmpl": str(
            DOWNLOAD_DIR
            / "%(title).80B.%(ext)s"
        ),

        # Never download playlists
        "noplaylist": True,

        # Progress
        "progress_hooks": [
            progress_hook
        ],

        # Reduce console noise
        "quiet": True,
        "no_warnings": True,
    }

    # --------------------------------------------------------
    # MP3
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # MP4
    # --------------------------------------------------------

    else:

        ydl_opts = {
            **common_opts,

            "format": (
                "bestvideo+bestaudio/best"
            ),

            "merge_output_format": "mp4",
        }

    # --------------------------------------------------------
    # Download
    # --------------------------------------------------------

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:

        info = ydl.extract_info(
            url,
            download=True,
        )

        original_filepath = Path(
            ydl.prepare_filename(info)
        )

    # --------------------------------------------------------
    # Final file path
    # --------------------------------------------------------

    if media_format == "MUSIC":
        filepath = original_filepath.with_suffix(".mp3")
    else:
        filepath = original_filepath.with_suffix(".mp4")

    return filepath


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

st.caption(
    "Download YouTube videos as MP3 or MP4."
)


# ------------------------------------------------------------
# URL
# ------------------------------------------------------------

url = st.text_input(
    "YouTube URL",
    placeholder="Paste a YouTube link here...",
)


# ------------------------------------------------------------
# Format
# ------------------------------------------------------------

format_choice = st.radio(
    "Download as",
    ["MUSIC", "VIDEO"],
    horizontal=True,
)


# ------------------------------------------------------------
# Download
# ------------------------------------------------------------

if st.button(
    f"Download {format_choice}",
    type="primary",
    use_container_width=True,
):

    # --------------------------------------------------------
    # Validate URL
    # --------------------------------------------------------

    clean_url = url.strip()

    if not clean_url:

        st.error(
            "Please enter a YouTube URL."
        )

    elif (
        "youtube.com/" not in clean_url
        and "youtu.be/" not in clean_url
    ):

        st.error(
            "Please enter a valid YouTube URL."
        )

    else:

        progress_bar = st.progress(0)
        status_text = st.empty()

        try:

            # ------------------------------------------------
            # Node setup
            # ------------------------------------------------

            with st.spinner(
                "Preparing downloader..."
            ):
                node_path = setup_node()

            status_text.write(
                f"Using Node.js: `{node_path}`"
            )

            # ------------------------------------------------
            # Download
            # ------------------------------------------------

            with st.spinner(
                f"Downloading {format_choice}..."
            ):

                filepath = download_media(
                    clean_url,
                    format_choice,
                    progress_bar,
                    status_text,
                )

            # ------------------------------------------------
            # Validate output
            # ------------------------------------------------

            if not filepath.exists():

                raise FileNotFoundError(
                    "Downloaded file was not found: "
                    f"{filepath}"
                )

            if filepath.stat().st_size == 0:

                raise RuntimeError(
                    "Downloaded file is empty."
                )

            # ------------------------------------------------
            # Success
            # ------------------------------------------------

            progress_bar.progress(1.0)

            status_text.success(
                "Download ready!"
            )

            # ------------------------------------------------
            # Browser download
            # ------------------------------------------------

            with open(filepath, "rb") as file:

                st.download_button(
                    label=(
                        f"⬇️ Save {format_choice}"
                    ),
                    data=file,
                    file_name=filepath.name,
                    mime=(
                        "audio/mpeg"
                        if format_choice == "MUSIC"
                        else "video/mp4"
                    ),
                    use_container_width=True,
                )

        except Exception as e:

            progress_bar.empty()
            status_text.empty()

            st.error(
                f"Download failed: {e}"
            )