"""Lossless image-in-image steganography using RGB least-significant bits."""

from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

from robust_steg import StegError


MAGIC = b"LSBI"
LEGACY_VERSION = 1
VERSION = 2
PREFIX = struct.Struct(">4sB")
LEGACY_HEADER = struct.Struct(">4sBIIII")
FORMAT_FIELD_BYTES = 32
HEADER = struct.Struct(f">4sBIIII{FORMAT_FIELD_BYTES}s")

PREFERRED_EXTENSIONS = {
    "AVIF": ".avif",
    "BMP": ".bmp",
    "GIF": ".gif",
    "ICO": ".ico",
    "JPEG": ".jpg",
    "JPEG2000": ".jp2",
    "PNG": ".png",
    "PPM": ".ppm",
    "TIFF": ".tiff",
    "WEBP": ".webp",
}


@dataclass(frozen=True)
class LsbCapacity:
    width: int
    height: int
    channel_bits: int
    max_payload_bytes: int


@dataclass(frozen=True)
class LsbEmbedResult:
    image_bytes: bytes
    capacity: LsbCapacity
    payload_bytes: int
    width: int
    height: int
    image_format: str


@dataclass(frozen=True)
class LsbExtractResult:
    image_bytes: bytes
    width: int
    height: int
    image_format: str
    media_type: str
    extension: str


def _open_image(data: bytes, label: str) -> Image.Image:
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            image.load()
            return image.copy()
    except Exception as exc:
        raise StegError(f"無法讀取{label}") from exc


def _inspect_image(data: bytes, label: str) -> tuple[int, int, str]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            image_format = (image.format or "").upper()
            width, height = image.size
    except Exception as exc:
        raise StegError(f"無法讀取{label}") from exc
    if not image_format:
        raise StegError(f"無法辨識{label}的檔案格式")
    try:
        encoded_format = image_format.encode("ascii")
    except UnicodeEncodeError as exc:
        raise StegError(f"{label}的檔案格式無效") from exc
    if len(encoded_format) > FORMAT_FIELD_BYTES:
        raise StegError(f"{label}的檔案名稱過長")
    return width, height, image_format


def _format_details(image_format: str) -> tuple[str, str]:
    media_type = Image.MIME.get(image_format) or f"image/{image_format.lower()}"
    extension = PREFERRED_EXTENSIONS.get(image_format)
    if extension is None:
        extension = next(
            (suffix for suffix, registered in Image.registered_extensions().items() if registered == image_format),
            ".img",
        )
    return media_type, extension


def image_capacity(width: int, height: int) -> LsbCapacity:
    if width < 1 or height < 1:
        raise StegError("圖片尺寸無效")
    channel_bits = width * height * 3
    return LsbCapacity(
        width=width,
        height=height,
        channel_bits=channel_bits,
        max_payload_bytes=max(0, channel_bits // 8 - HEADER.size),
    )


def capacity_from_image(data: bytes) -> LsbCapacity:
    image = _open_image(data, "載體圖片")
    return image_capacity(*image.size)


def _bits_from_bytes(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def _bytes_from_lsb(values: np.ndarray, byte_count: int) -> bytes:
    bit_count = byte_count * 8
    return np.packbits(values[:bit_count] & 1).tobytes()


def embed_image(carrier_data: bytes, secret_data: bytes) -> LsbEmbedResult:
    carrier = _open_image(carrier_data, "載體圖片")
    secret_width, secret_height, secret_format = _inspect_image(secret_data, "秘密圖片")
    capacity = image_capacity(*carrier.size)
    if len(secret_data) > capacity.max_payload_bytes:
        raise StegError(
            f"秘密圖片需要 {len(secret_data):,} bytes，"
            f"但這張載體圖片只有 {capacity.max_payload_bytes:,} bytes 容量"
        )

    checksum = zlib.crc32(secret_data) & 0xFFFFFFFF
    packet = HEADER.pack(
        MAGIC,
        VERSION,
        len(secret_data),
        secret_width,
        secret_height,
        checksum,
        secret_format.encode("ascii"),
    ) + secret_data
    bits = _bits_from_bytes(packet)

    rgb = np.asarray(carrier.convert("RGB"), dtype=np.uint8).copy()
    flat = rgb.reshape(-1)
    flat[: len(bits)] = (flat[: len(bits)] & 0xFE) | bits
    output_image = Image.fromarray(rgb, "RGB")

    has_alpha = carrier.mode in {"RGBA", "LA"} or "transparency" in carrier.info
    if has_alpha:
        alpha = carrier.convert("RGBA").getchannel("A")
        output_image = output_image.convert("RGBA")
        output_image.putalpha(alpha)

    output = io.BytesIO()
    output_image.save(output, format="PNG", optimize=True)
    return LsbEmbedResult(
        image_bytes=output.getvalue(),
        capacity=capacity,
        payload_bytes=len(secret_data),
        width=secret_width,
        height=secret_height,
        image_format=secret_format,
    )


def extract_image(stego_data: bytes) -> LsbExtractResult:
    stego = _open_image(stego_data, "LSB 圖片")
    capacity = image_capacity(*stego.size)
    if capacity.channel_bits < PREFIX.size * 8:
        raise StegError("這張圖片太小，無法包含 LSB 圖片資料")

    rgb = np.asarray(stego.convert("RGB"), dtype=np.uint8).reshape(-1)
    try:
        magic, version = PREFIX.unpack(_bytes_from_lsb(rgb, PREFIX.size))
    except struct.error as exc:
        raise StegError("找不到有效的 LSB 圖片資料") from exc
    if magic != MAGIC or version not in {LEGACY_VERSION, VERSION}:
        raise StegError("找不到有效的 LSB 圖片資料")

    header = LEGACY_HEADER if version == LEGACY_VERSION else HEADER
    if capacity.channel_bits < header.size * 8:
        raise StegError("這張圖片太小，無法包含 LSB 圖片資料")
    header_data = _bytes_from_lsb(rgb, header.size)
    if version == LEGACY_VERSION:
        _, _, payload_size, width, height, checksum = LEGACY_HEADER.unpack(header_data)
        declared_format = "PNG"
    else:
        _, _, payload_size, width, height, checksum, format_bytes = HEADER.unpack(header_data)
        try:
            declared_format = format_bytes.rstrip(b"\0").decode("ascii").upper()
        except UnicodeDecodeError as exc:
            raise StegError("LSB 圖片格式資料無效") from exc
        if not declared_format:
            raise StegError("LSB 圖片格式資料無效")

    max_payload_bytes = capacity.channel_bits // 8 - header.size
    if payload_size < 1 or payload_size > max_payload_bytes:
        raise StegError("LSB 圖片資料長度無效，圖片可能已被改動")

    packet_size = header.size + payload_size
    payload = _bytes_from_lsb(rgb, packet_size)[header.size:]
    if zlib.crc32(payload) & 0xFFFFFFFF != checksum:
        raise StegError("LSB 圖片資料驗證失敗，圖片可能已經壓縮或修改")

    actual_width, actual_height, actual_format = _inspect_image(payload, "隱藏的圖片")
    if (actual_width, actual_height) != (width, height):
        raise StegError("LSB 圖片尺寸驗證失敗")
    if actual_format != declared_format:
        raise StegError("LSB 圖片格式驗證失敗")
    media_type, extension = _format_details(actual_format)
    return LsbExtractResult(
        image_bytes=payload,
        width=width,
        height=height,
        image_format=actual_format,
        media_type=media_type,
        extension=extension,
    )
