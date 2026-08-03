#!/usr/bin/env python3
"""Robust, blind text watermarking for still images.

The payload is stored in quantized differences between pairs of mid-frequency
8x8 DCT coefficients.  A convolutional error-correcting code and repeated,
keyed carriers make the watermark survive ordinary lossy transcoding.

This is robust watermarking, not high-capacity lossless steganography.  It is
not designed to survive resizing, cropping, rotation, screenshots, or severe
filtering.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageOps


MAGIC = b"RSTG"
VERSION = 1
DEFAULT_STRENGTH = 56.0
DEFAULT_REDUNDANCY = 3
HEADER_REDUNDANCY = 3
HEADER = struct.Struct(">4sBBH")  # magic, version, payload redundancy, byte count
POLYNOMIALS = (0o133, 0o171)  # rate 1/2, constraint length 7
MEMORY = 6

# Each pair has coefficients with the same/similar JPEG quantization weight.
# Two independent carriers per 8x8 block improve useful capacity.
COEFFICIENT_PAIRS = (((2, 3), (3, 2)), ((1, 4), (4, 1)))


class StegError(Exception):
    """A user-facing watermark error."""


@dataclass(frozen=True)
class Capacity:
    width: int
    height: int
    carriers: int
    max_payload_bytes: int


def _dct_matrix(size: int = 8) -> np.ndarray:
    matrix = np.empty((size, size), dtype=np.float64)
    factor = math.pi / (2.0 * size)
    for k in range(size):
        scale = math.sqrt(1.0 / size) if k == 0 else math.sqrt(2.0 / size)
        for n in range(size):
            matrix[k, n] = scale * math.cos((2 * n + 1) * k * factor)
    return matrix


DCT = _dct_matrix()


def _bytes_to_bits(data: bytes) -> list[int]:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8)).astype(int).tolist()


def _bits_to_bytes(bits: Iterable[int]) -> bytes:
    values = np.asarray(list(bits), dtype=np.uint8)
    if len(values) % 8:
        raise ValueError("bit count must be a multiple of eight")
    return np.packbits(values).tobytes()


def _parity(value: int) -> int:
    return value.bit_count() & 1


def _convolutional_encode(bits: Iterable[int]) -> list[int]:
    state = 0
    output: list[int] = []
    for bit in list(bits) + [0] * MEMORY:
        register = (state << 1) | int(bit)
        output.extend(_parity(register & polynomial) for polynomial in POLYNOMIALS)
        state = register & ((1 << MEMORY) - 1)
    return output


def _viterbi_decode(soft_bits: list[float], data_bit_count: int) -> list[int]:
    """Decode soft bits; positive values favor one and negative favor zero."""
    steps = data_bit_count + MEMORY
    if len(soft_bits) != steps * len(POLYNOMIALS):
        raise ValueError("incorrect convolutional code length")

    state_count = 1 << MEMORY
    infinity = float("inf")
    costs = [infinity] * state_count
    costs[0] = 0.0
    previous_states: list[list[int]] = []
    previous_bits: list[list[int]] = []

    for step in range(steps):
        observations = soft_bits[step * 2 : step * 2 + 2]
        new_costs = [infinity] * state_count
        step_states = [-1] * state_count
        step_bits = [0] * state_count
        for state, old_cost in enumerate(costs):
            if old_cost == infinity:
                continue
            for bit in (0, 1):
                register = (state << 1) | bit
                next_state = register & (state_count - 1)
                expected = [_parity(register & p) for p in POLYNOMIALS]
                # Minimizing this correlation cost is equivalent to maximizing
                # agreement with the expected coded symbols.
                branch = sum(obs if exp == 0 else -obs for obs, exp in zip(observations, expected))
                candidate = old_cost + branch
                if candidate < new_costs[next_state]:
                    new_costs[next_state] = candidate
                    step_states[next_state] = state
                    step_bits[next_state] = bit
        costs = new_costs
        previous_states.append(step_states)
        previous_bits.append(step_bits)

    state = 0  # the encoder is terminated with MEMORY zero bits
    decoded_reversed: list[int] = []
    for step in range(steps - 1, -1, -1):
        decoded_reversed.append(previous_bits[step][state])
        state = previous_states[step][state]
        if state < 0:
            raise StegError("error-correcting decoder could not find a valid path")
    decoded_reversed.reverse()
    return decoded_reversed[:data_bit_count]


def _seed_from_key(key: str) -> int:
    digest = hashlib.sha256(("robust-steg-v1\0" + key).encode("utf-8")).digest()
    return int.from_bytes(digest[:16], "big")


def _carrier_order(width: int, height: int, key: str) -> np.ndarray:
    block_rows, block_cols = height // 8, width // 8
    count = block_rows * block_cols * len(COEFFICIENT_PAIRS)
    generator = np.random.Generator(np.random.PCG64(_seed_from_key(key)))
    return generator.permutation(count)


def _carrier_location(carrier: int, width: int) -> tuple[int, int, int]:
    block_cols = width // 8
    pair_index = carrier % len(COEFFICIENT_PAIRS)
    block_index = carrier // len(COEFFICIENT_PAIRS)
    return (block_index // block_cols) * 8, (block_index % block_cols) * 8, pair_index


def _nearest_lattice(value: float, wanted_parity: int) -> float:
    lower = math.floor(value)
    candidates = [n for n in range(lower - 2, lower + 4) if (n & 1) == wanted_parity]
    return float(min(candidates, key=lambda n: abs(value - n)))


def _embed_symbol(channel: np.ndarray, row: int, col: int, pair_index: int, bit: int, strength: float) -> None:
    block = channel[row : row + 8, col : col + 8]
    coefficients = DCT @ block @ DCT.T
    first, second = COEFFICIENT_PAIRS[pair_index]
    difference = coefficients[first] - coefficients[second]
    target = _nearest_lattice(difference / strength, bit) * strength
    adjustment = (target - difference) / 2.0
    coefficients[first] += adjustment
    coefficients[second] -= adjustment
    channel[row : row + 8, col : col + 8] = DCT.T @ coefficients @ DCT


def _extract_symbol(channel: np.ndarray, row: int, col: int, pair_index: int, strength: float) -> float:
    coefficients = DCT @ channel[row : row + 8, col : col + 8] @ DCT.T
    first, second = COEFFICIENT_PAIRS[pair_index]
    value = (coefficients[first] - coefficients[second]) / strength
    nearest_even = 2.0 * round(value / 2.0)
    nearest_odd = 2.0 * round((value - 1.0) / 2.0) + 1.0
    distance_even = abs(value - nearest_even)
    distance_odd = abs(value - nearest_odd)
    return distance_even - distance_odd  # positive favors one


def _coded_carrier_count(data_bytes: int, redundancy: int) -> int:
    return ((data_bytes * 8 + MEMORY) * 2) * redundancy


def image_capacity(width: int, height: int, redundancy: int = DEFAULT_REDUNDANCY) -> Capacity:
    if redundancy < 1 or redundancy > 15 or redundancy % 2 == 0:
        raise StegError("redundancy must be an odd number from 1 to 15")
    carriers = (width // 8) * (height // 8) * len(COEFFICIENT_PAIRS)
    header_carriers = _coded_carrier_count(HEADER.size, HEADER_REDUNDANCY)
    remaining = max(0, carriers - header_carriers)
    # Payload storage also includes a four-byte CRC and convolutional tail.
    source_bits = max(0, remaining // (2 * redundancy) - MEMORY)
    max_payload = max(0, source_bits // 8 - 4)
    return Capacity(width, height, carriers, min(max_payload, 65535))


def _open_image(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    try:
        with Image.open(path) as source:
            original = ImageOps.exif_transpose(source)
            original.load()
            alpha = np.asarray(original.getchannel("A")).copy() if "A" in original.getbands() else None
            ycbcr = np.asarray(original.convert("RGB").convert("YCbCr"), dtype=np.float64).copy()
            if original is not source:
                original.close()
    except Exception as exc:
        raise StegError(f"cannot open image '{path}': {exc}") from exc
    return ycbcr, alpha


def _save_image(ycbcr: np.ndarray, alpha: np.ndarray | None, output: Path, quality: int) -> None:
    clipped = np.clip(np.rint(ycbcr), 0, 255).astype(np.uint8)
    rgb = Image.fromarray(clipped, "YCbCr").convert("RGB")
    suffix = output.suffix.lower()
    if alpha is not None and suffix not in {".jpg", ".jpeg"}:
        rgb.putalpha(Image.fromarray(alpha, "L"))
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if suffix in {".jpg", ".jpeg"}:
            rgb.save(output, quality=quality, subsampling=0, optimize=True)
        elif suffix == ".webp":
            rgb.save(output, quality=quality, method=6)
        elif suffix == ".png":
            rgb.save(output, compress_level=6)
        else:
            rgb.save(output)
    except Exception as exc:
        raise StegError(f"cannot save image '{output}': {exc}") from exc


def _embed_stream(
    channel: np.ndarray,
    order: np.ndarray,
    offset: int,
    data: bytes,
    redundancy: int,
    strength: float,
    width: int,
) -> int:
    coded = _convolutional_encode(_bytes_to_bits(data))
    required = len(coded) * redundancy
    if offset + required > len(order):
        raise StegError("image does not have enough carrier capacity")
    position = offset
    for bit in coded:
        for _ in range(redundancy):
            row, col, pair_index = _carrier_location(int(order[position]), width)
            _embed_symbol(channel, row, col, pair_index, bit, strength)
            position += 1
    return position


def _extract_stream(
    channel: np.ndarray,
    order: np.ndarray,
    offset: int,
    data_bytes: int,
    redundancy: int,
    strength: float,
    width: int,
) -> tuple[bytes, int]:
    coded_bits = (data_bytes * 8 + MEMORY) * 2
    required = coded_bits * redundancy
    if offset + required > len(order):
        raise StegError("declared payload is larger than this image can hold")
    soft: list[float] = []
    position = offset
    for _ in range(coded_bits):
        votes = 0.0
        for _ in range(redundancy):
            row, col, pair_index = _carrier_location(int(order[position]), width)
            votes += _extract_symbol(channel, row, col, pair_index, strength)
            position += 1
        soft.append(votes)
    decoded = _viterbi_decode(soft, data_bytes * 8)
    return _bits_to_bytes(decoded), position


def embed_text(
    input_path: Path,
    output_path: Path,
    text: str,
    *,
    key: str = "",
    strength: float = DEFAULT_STRENGTH,
    redundancy: int = DEFAULT_REDUNDANCY,
    quality: int = 95,
) -> Capacity:
    payload = text.encode("utf-8")
    if len(payload) > 65535:
        raise StegError("UTF-8 payload is limited to 65,535 bytes")
    if strength < 8 or strength > 200:
        raise StegError("strength must be between 8 and 200")
    if not 1 <= quality <= 100:
        raise StegError("quality must be between 1 and 100")

    ycbcr, alpha = _open_image(input_path)
    height, width = ycbcr.shape[:2]
    capacity = image_capacity(width, height, redundancy)
    if len(payload) > capacity.max_payload_bytes:
        raise StegError(
            f"payload is {len(payload)} UTF-8 bytes, but this image holds at most "
            f"{capacity.max_payload_bytes} bytes at redundancy {redundancy}"
        )

    order = _carrier_order(width, height, key)
    header = HEADER.pack(MAGIC, VERSION, redundancy, len(payload))
    position = _embed_stream(ycbcr[:, :, 0], order, 0, header, HEADER_REDUNDANCY, strength, width)
    checksum = struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
    _embed_stream(ycbcr[:, :, 0], order, position, payload + checksum, redundancy, strength, width)
    _save_image(ycbcr, alpha, output_path, quality)
    return capacity


def extract_text(input_path: Path, *, key: str = "", strength: float = DEFAULT_STRENGTH) -> str:
    if strength < 8 or strength > 200:
        raise StegError("strength must be between 8 and 200")
    ycbcr, _ = _open_image(input_path)
    height, width = ycbcr.shape[:2]
    order = _carrier_order(width, height, key)
    header, position = _extract_stream(
        ycbcr[:, :, 0], order, 0, HEADER.size, HEADER_REDUNDANCY, strength, width
    )
    magic, version, redundancy, payload_length = HEADER.unpack(header)
    if magic != MAGIC or version != VERSION:
        raise StegError("watermark header not found (wrong key/strength, damaged image, or no watermark)")
    if redundancy < 1 or redundancy > 15 or redundancy % 2 == 0:
        raise StegError("watermark header is damaged (invalid redundancy)")

    packet, _ = _extract_stream(
        ycbcr[:, :, 0], order, position, payload_length + 4, redundancy, strength, width
    )
    payload, stored_checksum = packet[:-4], packet[-4:]
    actual_checksum = struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
    if stored_checksum != actual_checksum:
        raise StegError("watermark payload failed CRC (image is too damaged or settings are wrong)")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StegError("watermark passed CRC but is not valid UTF-8") from exc


def _positive_float(value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hide and recover UTF-8 text using a robust DCT image watermark."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    embed = subparsers.add_parser("embed", help="embed text in an image")
    embed.add_argument("input", type=Path)
    embed.add_argument("output", type=Path)
    text_group = embed.add_mutually_exclusive_group(required=True)
    text_group.add_argument("--text", help="text to embed")
    text_group.add_argument("--text-file", type=Path, help="read UTF-8 text from a file")
    embed.add_argument("--key", default="", help="secret carrier-order key")
    embed.add_argument("--strength", type=_positive_float, default=DEFAULT_STRENGTH)
    embed.add_argument("--redundancy", type=int, default=DEFAULT_REDUNDANCY)
    embed.add_argument("--quality", type=int, default=95, help="JPEG/WebP output quality")

    extract = subparsers.add_parser("extract", help="extract text from an image")
    extract.add_argument("input", type=Path)
    extract.add_argument("--key", default="")
    extract.add_argument("--strength", type=_positive_float, default=DEFAULT_STRENGTH)
    extract.add_argument("--output", type=Path, help="write recovered UTF-8 text to a file")

    capacity = subparsers.add_parser("capacity", help="show an image's payload capacity")
    capacity.add_argument("input", type=Path)
    capacity.add_argument("--redundancy", type=int, default=DEFAULT_REDUNDANCY)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "embed":
            text = args.text
            if args.text_file:
                text = args.text_file.read_text(encoding="utf-8")
            capacity = embed_text(
                args.input,
                args.output,
                text,
                key=args.key,
                strength=args.strength,
                redundancy=args.redundancy,
                quality=args.quality,
            )
            byte_count = len(text.encode("utf-8"))
            print(
                f"Embedded {byte_count} bytes in {args.output} "
                f"(capacity {capacity.max_payload_bytes} bytes)."
            )
        elif args.command == "extract":
            recovered = extract_text(args.input, key=args.key, strength=args.strength)
            if args.output:
                args.output.write_text(recovered, encoding="utf-8")
                print(f"Recovered text to {args.output}.")
            else:
                print(recovered)
        else:
            try:
                with Image.open(args.input) as image:
                    width, height = image.size
            except Exception as exc:
                raise StegError(f"cannot open image '{args.input}': {exc}") from exc
            result = image_capacity(width, height, args.redundancy)
            print(
                f"{width}x{height}: {result.max_payload_bytes} UTF-8 payload bytes "
                f"at redundancy {args.redundancy} ({result.carriers} carriers)."
            )
        return 0
    except (StegError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
