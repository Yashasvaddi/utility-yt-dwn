from pathlib import Path
import streamlit as st
import yt_dlp

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)


def download_mp3(url: str):
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
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filepath = Path(ydl.prepare_filename(info)).with_suffix(".mp3")

    return filepath


# ---------------- UI ----------------

st.set_page_config(
    page_title="YouTube MP3 Downloader",
    page_icon="🎵",
)

st.title("🎵 YouTube MP3 Downloader")

url = st.text_input(
    "YouTube URL",
    placeholder="Paste a YouTube link here...",
)

if st.button("Download MP3", type="primary", use_container_width=True):

    if not url.strip():
        st.error("Please enter a YouTube URL.")

    elif "youtube.com/" not in url and "youtu.be/" not in url:
        st.error("Please enter a valid YouTube URL.")

    else:
        try:
            with st.spinner("Downloading and converting to MP3..."):
                filepath = download_mp3(url.strip())

            st.success("MP3 ready!")

            with open(filepath, "rb") as file:
                st.download_button(
                    label="⬇️ Save MP3",
                    data=file,
                    file_name=filepath.name,
                    mime="audio/mpeg",
                    use_container_width=True,
                )

        except Exception as e:
            st.error(f"Download failed: {e}")