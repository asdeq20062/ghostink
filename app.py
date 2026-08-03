#!/usr/bin/env python3
"""Local web interface for the robust image watermark tool."""

from __future__ import annotations

import io
from pathlib import Path
from tempfile import TemporaryDirectory

from flask import Flask, jsonify, render_template, request, send_file
from PIL import Image

from robust_steg import (
    DEFAULT_REDUNDANCY,
    DEFAULT_STRENGTH,
    StegError,
    embed_text,
    extract_text,
    image_capacity,
)


app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=30 * 1024 * 1024,
    JSON_AS_ASCII=False,
)

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
OUTPUT_FORMATS = {
    "png": (".png", "image/png"),
    "jpeg": (".jpg", "image/jpeg"),
    "webp": (".webp", "image/webp"),
}


def _number(name: str, default: float, cast: type[int] | type[float]) -> int | float:
    raw = request.form.get(name, str(default))
    try:
        return cast(raw)
    except (TypeError, ValueError) as exc:
        raise StegError(f"{name} 的數值無效") from exc


def _uploaded_image() -> tuple[bytes, str, str]:
    upload = request.files.get("image")
    if upload is None or not upload.filename:
        raise StegError("請選擇圖片")

    original_name = Path(upload.filename).name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise StegError("只支援 PNG、JPEG、WebP 或 BMP 圖片")
    data = upload.read()
    if not data:
        raise StegError("圖片檔案是空的")
    return data, original_name, suffix


def _save_upload(root: Path, data: bytes, name: str) -> Path:
    path = root / name
    path.write_bytes(data)
    return path


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/capacity")
def capacity():
    data, _, _ = _uploaded_image()
    redundancy = int(_number("redundancy", DEFAULT_REDUNDANCY, int))
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except Exception as exc:
        raise StegError("無法讀取這張圖片") from exc

    result = image_capacity(width, height, redundancy)
    return jsonify(
        width=result.width,
        height=result.height,
        carriers=result.carriers,
        max_payload_bytes=result.max_payload_bytes,
    )


@app.post("/api/embed")
def embed():
    data, original_name, suffix = _uploaded_image()
    text = request.form.get("text", "")
    if not text:
        raise StegError("請輸入要隱藏的文字")

    strength = float(_number("strength", DEFAULT_STRENGTH, float))
    redundancy = int(_number("redundancy", DEFAULT_REDUNDANCY, int))
    quality = int(_number("quality", 95, int))
    key = request.form.get("key", "")
    output_format = request.form.get("output_format", "png").lower()
    if output_format not in OUTPUT_FORMATS:
        raise StegError("輸出格式無效")

    output_suffix, mimetype = OUTPUT_FORMATS[output_format]
    with TemporaryDirectory(prefix="magic-image-") as directory:
        root = Path(directory)
        input_path = _save_upload(root, data, f"input{suffix}")
        output_path = root / f"output{output_suffix}"
        result = embed_text(
            input_path,
            output_path,
            text,
            key=key,
            strength=strength,
            redundancy=redundancy,
            quality=quality,
        )
        output = io.BytesIO(output_path.read_bytes())

    stem = Path(original_name).stem or "image"
    response = send_file(
        output,
        mimetype=mimetype,
        as_attachment=True,
        download_name=f"{stem}_watermarked{output_suffix}",
    )
    response.headers["X-Capacity-Bytes"] = str(result.max_payload_bytes)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/extract")
def extract():
    data, _, suffix = _uploaded_image()
    strength = float(_number("strength", DEFAULT_STRENGTH, float))
    key = request.form.get("key", "")

    with TemporaryDirectory(prefix="magic-image-") as directory:
        input_path = _save_upload(Path(directory), data, f"input{suffix}")
        text = extract_text(input_path, key=key, strength=strength)
    return jsonify(text=text, byte_count=len(text.encode("utf-8")))


@app.errorhandler(StegError)
def handle_steg_error(error: StegError):
    return jsonify(error=str(error)), 400


@app.errorhandler(413)
def handle_too_large(_error):
    return jsonify(error="圖片不可大於 30 MB"), 413


@app.errorhandler(500)
def handle_server_error(_error):
    return jsonify(error="處理圖片時發生錯誤"), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)
