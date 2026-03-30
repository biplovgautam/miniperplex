import re
import tempfile
import os
import time
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import urlparse, parse_qs

import requests
from dotenv import load_dotenv
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from yt_dlp import YoutubeDL

ASSEMBLYAI_BASE_URL = "https://api.assemblyai.com"

load_dotenv()


def extract_video_id(url: str) -> str | None:
    parsed_url = urlparse(url)

    if parsed_url.hostname in ["www.youtube.com", "youtube.com"]:
        return parse_qs(parsed_url.query).get("v", [None])[0]

    if parsed_url.hostname == "youtu.be":
        return parsed_url.path[1:]

    return None


def extract_entry_value(entry, key: str, default):
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def is_valid_transcript(transcript_entries: list) -> bool:
    combined_text = " ".join(
        extract_entry_value(entry, "text", "") for entry in transcript_entries
    )
    return bool(re.search(r"[A-Za-z0-9]", combined_text))


def print_transcript(transcript_entries: list) -> None:
    print("\n✅ TRANSCRIPT WITH TIMESTAMPS:\n")
    for entry in transcript_entries:
        start = extract_entry_value(entry, "start", 0)
        duration = extract_entry_value(entry, "duration", 0)
        text = extract_entry_value(entry, "text", "")
        print(f"[{start:.2f}s - {start + duration:.2f}s] {text}")


def download_audio_to_temp(video_url: str, output_dir: str) -> str:
    output_template = f"{output_dir}/audio.%(ext)s"
    options = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(video_url, download=True)
        original_path = ydl.prepare_filename(info)

    audio_path = original_path.rsplit(".", 1)[0] + ".mp3"
    return audio_path


def transcribe_audio_with_assemblyai(audio_path: str) -> str:
    assembly_api_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not assembly_api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY is not set in your environment or .env")

    headers = {"authorization": assembly_api_key}

    upload_endpoint = f"{ASSEMBLYAI_BASE_URL}/v2/upload"
    with open(audio_path, "rb") as audio_file:
        upload_response = requests.post(
            upload_endpoint,
            headers=headers,
            data=audio_file,
            timeout=120,
        )
    upload_response.raise_for_status()
    upload_payload = upload_response.json()
    audio_url = upload_payload.get("upload_url")
    if not audio_url:
        raise RuntimeError(f"Unexpected AssemblyAI upload response: {upload_payload}")

    submit_endpoint = f"{ASSEMBLYAI_BASE_URL}/v2/transcript"
    request_data = {
        "audio_url": audio_url,
        "language_detection": True,
        "speech_models": ["universal-3-pro", "universal-2"],
    }
    submit_response = requests.post(
        submit_endpoint,
        json=request_data,
        headers=headers,
        timeout=60,
    )
    submit_response.raise_for_status()
    submit_payload = submit_response.json()
    transcript_id = submit_payload.get("id")
    if not transcript_id:
        raise RuntimeError(f"Unexpected AssemblyAI submit response: {submit_payload}")

    polling_endpoint = f"{ASSEMBLYAI_BASE_URL}/v2/transcript/{transcript_id}"
    for _ in range(120):
        polling_response = requests.get(polling_endpoint, headers=headers, timeout=30)
        polling_response.raise_for_status()
        polling_payload = polling_response.json()

        status = (polling_payload.get("status") or "").lower()
        if status == "completed":
            return str(polling_payload.get("text") or "")
        if status == "error":
            raise RuntimeError(f"AssemblyAI transcription failed: {polling_payload.get('error')}")

        time.sleep(3)

    raise TimeoutError("AssemblyAI transcription timed out while waiting for completion")


def transcribe_video_audio_with_assemblyai(video_url: str) -> str:
    with tempfile.TemporaryDirectory() as tmp_dir:
        audio_path = download_audio_to_temp(video_url, tmp_dir)
        transcript = transcribe_audio_with_assemblyai(audio_path)
        return transcript


def get_transcript(video_url: str) -> None:
    video_id = extract_video_id(video_url)

    if not video_id:
        print("❌ Invalid YouTube URL")
        return

    try:
        api = YouTubeTranscriptApi()
        try:
            api_version = version("youtube-transcript-api")
        except PackageNotFoundError:
            api_version = "0.0.0"

        if api_version.startswith("1") and hasattr(api, "fetch"):
            transcript = api.fetch(video_id)
        elif hasattr(YouTubeTranscriptApi, "get_transcript"):
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
        else:
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
            try:
                transcript = transcripts.find_manually_created_transcript(["en"]).fetch()
            except Exception:
                transcript = transcripts.find_generated_transcript(["en"]).fetch()
        if not transcript or not is_valid_transcript(transcript):
            print("No caption")
            return
        print_transcript(transcript)
    except (TranscriptsDisabled, NoTranscriptFound, CouldNotRetrieveTranscript):
        try:
            assembly_transcript = transcribe_video_audio_with_assemblyai(video_url)
            print("\n✅ TRANSCRIPT (ASSEMBLYAI):\n")
            print(assembly_transcript)
        except Exception as assembly_error:
            print("No caption")
            print(f"❌ AssemblyAI fallback failed: {assembly_error}")
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    url = input("Enter YouTube video URL: ")
    get_transcript(url)