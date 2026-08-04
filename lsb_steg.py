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
VERSION = 1
HEADER = struct.Struct(">4sBIIII")  # magic, version, payload bytes, width, height, crc32


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


@dataclass(frozen=True)
class LsbExtractResult:
    image_bytes: bytes
    width: int
    height: int


def _open_image(data: bytes, label: str) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return ImageOps.exif_transpose(image)
    except Exception as exc:
        raise StegError(f"無法讀取{label}") from exc


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


def _normalized_secret_png(image: Image.Image) -> tuple[bytes, int, int]:
    width, height = image.size
    has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
    normalized = image.convert("RGBA" if has_alpha else "RGB")
    output = io.BytesIO()
    normalized.save(output, format="PNG", optimize=True)
    return output.getvalue(), width, height


def _bits_from_bytes(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def _bytes_from_lsb(values: np.ndarray, byte_count: int) -> bytes:
    bit_count = byte_count * 8
    return np.packbits(values[:bit_count] & 1).tobytes()


def embed_image(carrier_data: bytes, secret_data: bytes) -> LsbEmbedResult:
    carrier = _open_image(carrier_data, "載體圖片")
    secret = _open_image(secret_data, "秘密圖片")
    secret_png, secret_width, secret_height = _normalized_secret_png(secret)
    capacity = image_capacity(*carrier.size)
    if len(secret_png) > capacity.max_payload_bytes:
        raise StegError(
            f"秘密圖片需要 {len(secret_png):,} bytes，"
            f"但這張載體圖片只有 {capacity.max_payload_bytes:,} bytes 容量"
        )

    checksum = zlib.crc32(secret_png) & 0xFFFFFFFF
    packet = HEADER.pack(
        MAGIC,
        VERSION,
        len(secret_png),
        secret_width,
        secret_height,
        checksum,
    ) + secret_png
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
        payload_bytes=len(secret_png),
        width=secret_width,
        height=secret_height,
    )


def extract_image(stego_data: bytes) -> LsbExtractResult:
    stego = _open_image(stego_data, "LSB 圖片")
    capacity = image_capacity(*stego.size)
    if capacity.channel_bits < HEADER.size * 8:
        raise StegError("這張圖片太小，無法包含 LSB 圖片資料")

    rgb = np.asarray(stego.convert("RGB"), dtype=np.uint8).reshape(-1)
    header_data = _bytes_from_lsb(rgb, HEADER.size)
    try:
        magic, version, payload_size, width, height, checksum = HEADER.unpack(header_data)
    except struct.error as exc:
        raise StegError("找不到有效的 LSB 圖片資料") from exc
    if magic != MAGIC or version != VERSION:
        raise StegError("找不到有效的 LSB 圖片資料")
    if payload_size < 1 or payload_size > capacity.max_payload_bytes:
        raise StegError("LSB 圖片資料長度無效，圖片可能已被改動")

    packet_size = HEADER.size + payload_size
    payload = _bytes_from_lsb(rgb, packet_size)[HEADER.size:]
    if zlib.crc32(payload) & 0xFFFFFFFF != checksum:
        raise StegError("LSB 圖片資料驗證失敗，圖片可能已經壓縮或修改")

    secret = _open_image(payload, "隱藏的圖片")
    if secret.size != (width, height):
        raise StegError("LSB 圖片尺寸驗證失敗")
    return LsbExtractResult(image_bytes=payload, width=width, height=height)
