from pathlib import Path

import streamlit as st
import yt_dlp


DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)


def download_media(url: str, media_format: str, progress_bar, status_text):
    def progress_hook(data):
        if data["status"] == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            downloaded = data.get("downloaded_bytes", 0)

            if total:
                progress = min(downloaded / total, 1.0)
                progress_bar.progress(progress)

                percentage = progress * 100

                speed = data.get("speed")
                if speed:
                    speed_mb = speed / (1024 * 1024)
                    speed_text = f"{speed_mb:.2f} MB/s"
                else:
                    speed_text = "calculating..."

                downloaded_mb = downloaded / (1024 * 1024)
                total_mb = total / (1024 * 1024)

                status_text.write(
                    f"**{percentage:.1f}%** • "
                    f"{downloaded_mb:.1f} / {total_mb:.1f} MB • "
                    f"{speed_text}"
                )

        elif data["status"] == "finished":
            progress_bar.progress(1.0)
            status_text.write("Processing file...")

    if media_format == "MUSIC":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(DOWNLOAD_DIR / "%(title).80B.%(ext)s"),
            "noplaylist": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }
            ],
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
        }

    else:
        ydl_opts = {
            "format": "bestvideo+bestaudio/best",
            "outtmpl": str(DOWNLOAD_DIR / "%(title).80B.%(ext)s"),
            "noplaylist": True,
            "merge_output_format": "mp4",
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

        if media_format == "MUSIC":
            filepath = Path(
                ydl.prepare_filename(info)
            ).with_suffix(".mp3")
        else:
            filepath = Path(
                ydl.prepare_filename(info)
            ).with_suffix(".mp4")

    return filepath


# ---------------- UI ----------------

st.set_page_config(
    page_title="YouTube Downloader",
    page_icon="🎵",
)

st.title("YouTube Downloader")

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
    if not url.strip():
        st.error("Please enter a YouTube URL.")

    elif "youtube.com/" not in url and "youtu.be/" not in url:
        st.error("Please enter a valid YouTube URL.")

    else:
        try:
            progress_bar = st.progress(0)
            status_text = st.empty()

            with st.spinner(f"Downloading {format_choice}..."):
                filepath = download_media(
                    url.strip(),
                    format_choice,
                    progress_bar,
                    status_text,
                )

            progress_bar.progress(1.0)
            status_text.success("Download ready!")

            with open(filepath, "rb") as file:
                st.download_button(
                    label=f"⬇️ Save {format_choice}",
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
            st.error(f"Download failed: {e}")