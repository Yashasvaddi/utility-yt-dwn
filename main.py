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
DOWNLOAD_DIR.mkdir(exist_ok=True)

NODE_VERSION = "22.23.2"

NODE_BASE_DIR = Path.home() / ".local"
NODE_DIR = NODE_BASE_DIR / f"node-v{NODE_VERSION}"
NODE_BIN = NODE_DIR / "bin" / "node"


# ============================================================
# NODE.JS SETUP
# ============================================================

def ensure_node():
    """
    Ensure Node.js is available.

    Priority:
    1. Use system Node.js if available.
    2. Otherwise download the official Node.js 22 binary.
    """

    # Check if Node is already installed
    system_node = shutil.which("node")

    if system_node:
        return Path(system_node)

    # Check if we've already downloaded Node
    if NODE_BIN.exists():
        return NODE_BIN

    NODE_BASE_DIR.mkdir(parents=True, exist_ok=True)

    archive_name = f"node-v{NODE_VERSION}-linux-x64.tar.xz"
    archive_path = NODE_BASE_DIR / archive_name

    download_url = (
        f"https://nodejs.org/dist/v{NODE_VERSION}/{archive_name}"
    )

    # Download Node.js
    with st.spinner("Setting up Node.js..."):
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

        # Rename extracted directory to our predictable path
        if extracted_dir.exists() and not NODE_DIR.exists():
            extracted_dir.rename(NODE_DIR)

        # Remove archive
        archive_path.unlink(missing_ok=True)

    if not NODE_BIN.exists():
        raise RuntimeError(
            "Node.js installation failed."
        )

    return NODE_BIN


# Initialize Node before yt-dlp is used
NODE_PATH = ensure_node()

# Add Node to PATH
os.environ["PATH"] = (
    f"{NODE_PATH.parent}:{os.environ.get('PATH', '')}"
)


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

        if data["status"] == "downloading":

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

                # Download speed
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

                # Downloaded / total size
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

        elif data["status"] == "finished":

            progress_bar.progress(1.0)

            status_text.write(
                "Processing file..."
            )


    # --------------------------------------------------------
    # Common yt-dlp options
    # --------------------------------------------------------

    common_opts = {
        # IMPORTANT:
        # Use Node.js for YouTube JavaScript challenges
        "js_runtimes": {
            "node": {},
        },

        "outtmpl": str(
            DOWNLOAD_DIR
            / "%(title).80B.%(ext)s"
        ),

        "noplaylist": True,

        "progress_hooks": [
            progress_hook
        ],

        "quiet": True,

        "no_warnings": True,
    }


    # --------------------------------------------------------
    # MUSIC / MP3
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
    # VIDEO / MP4
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
    # Determine final filepath
    # --------------------------------------------------------

    if media_format == "MUSIC":

        filepath = original_filepath.with_suffix(
            ".mp3"
        )

    else:

        filepath = original_filepath.with_suffix(
            ".mp4"
        )

    return filepath


# ============================================================
# STREAMLIT UI
# ============================================================

st.set_page_config(
    page_title="YouTube Downloader",
    page_icon="🎵",
    layout="centered",
)


st.title("YouTube Downloader")

st.caption(
    "Download YouTube videos as MP3 or MP4."
)


# ------------------------------------------------------------
# URL
# ------------------------------------------------------------

url = st.text_input(
    "YouTube URL",
    placeholder=(
        "Paste a YouTube link here..."
    ),
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
# Download button
# ------------------------------------------------------------

if st.button(
    f"Download {format_choice}",
    type="primary",
    use_container_width=True,
):

    # --------------------------------------------------------
    # Validate URL
    # --------------------------------------------------------

    if not url.strip():

        st.error(
            "Please enter a YouTube URL."
        )

    elif (
        "youtube.com/" not in url
        and "youtu.be/" not in url
    ):

        st.error(
            "Please enter a valid YouTube URL."
        )

    else:

        try:

            # ------------------------------------------------
            # Progress UI
            # ------------------------------------------------

            progress_bar = st.progress(0)

            status_text = st.empty()


            # ------------------------------------------------
            # Download
            # ------------------------------------------------

            with st.spinner(
                f"Downloading {format_choice}..."
            ):

                filepath = download_media(
                    url.strip(),
                    format_choice,
                    progress_bar,
                    status_text,
                )


            # ------------------------------------------------
            # Check output
            # ------------------------------------------------

            if not filepath.exists():

                raise FileNotFoundError(
                    f"Downloaded file not found: "
                    f"{filepath}"
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

            with open(
                filepath,
                "rb",
            ) as file:

                st.download_button(
                    label=(
                        f"⬇️ Save "
                        f"{format_choice}"
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