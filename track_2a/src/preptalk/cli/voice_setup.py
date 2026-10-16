"""One-time, project-local build of whisper.cpp and download of its multilingual base model."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

from .voice import VOICE_HOME

WHISPER_TAG = "v1.8.7"
WHISPER_COMMIT = "48f628a84833905ee4a0658ee6d4a5c915ce1997"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
MODEL_SHA1 = "465707469ff3a37a2b9b8d8f89f2f99de7299dac"  # upstream models/README.md


def setup():
    if sys.platform != "darwin":
        raise SystemExit("Experimental voice mode currently runs locally on macOS.")
    missing = [tool for tool in ("git", "cmake", "ffmpeg", "say") if not shutil.which(tool)]
    if missing:
        raise SystemExit(f"Missing: {', '.join(missing)}. Install build tools/audio support: brew install cmake ffmpeg")
    VOICE_HOME.mkdir(exist_ok=True)
    source = VOICE_HOME / "whisper.cpp"
    if not source.exists():
        subprocess.run(["git", "clone", "--depth", "1", "--branch", WHISPER_TAG,
                        "https://github.com/ggml-org/whisper.cpp.git", str(source)], check=True)
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != WHISPER_COMMIT:
        raise SystemExit(f"Unexpected whisper.cpp revision in {source}; expected {WHISPER_COMMIT}.")
    subprocess.run(["cmake", "-S", str(source), "-B", str(source / "build"), "-DCMAKE_BUILD_TYPE=Release",
                    "-DWHISPER_BUILD_TESTS=OFF"], check=True)
    subprocess.run(["cmake", "--build", str(source / "build"), "--target", "whisper-cli",
                    "--parallel", str(min(os.cpu_count() or 2, 8))], check=True)
    model = VOICE_HOME / "ggml-base.bin"
    if not model.exists():
        pending = model.with_suffix(".part")
        print("Downloading multilingual Whisper base (~142 MiB); no account or API credits required.", flush=True)
        try:
            with urllib.request.urlopen(MODEL_URL, timeout=60) as response, pending.open("wb") as output:
                shutil.copyfileobj(response, output)
            if digest(pending) != MODEL_SHA1:
                raise SystemExit("Whisper model checksum does not match upstream; download discarded.")
            pending.replace(model)
        finally:
            pending.unlink(missing_ok=True)
    elif digest(model) != MODEL_SHA1:
        raise SystemExit(f"Whisper model checksum mismatch: {model}")
    print("Voice setup ready. Run make chat and choose Voice (experimental).")


def digest(path: Path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha1").hexdigest()


if __name__ == "__main__":
    setup()
