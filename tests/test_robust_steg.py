import io
import math
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

from robust_steg import (
    StegError,
    embed_image,
    embed_text,
    extract_payload,
    extract_text,
    image_capacity,
)
import robust_steg as steg


class RobustStegTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        rng = np.random.default_rng(20260803)
        y, x = np.mgrid[:768, :768]
        base = np.stack(
            [
                (x / 3 + y / 5) % 256,
                (x / 7 + y / 2) % 256,
                (x / 2 + y / 11) % 256,
            ],
            axis=2,
        )
        noise = rng.normal(0, 18, base.shape)
        pixels = np.clip(base + noise, 0, 255).astype(np.uint8)
        self.source = self.root / "source.png"
        Image.fromarray(pixels, "RGB").save(self.source)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_png_round_trip_unicode(self):
        output = self.root / "marked.png"
        message = "香港測試：JPEG ⇄ PNG — robust watermark 🖼️"
        embed_text(self.source, output, message, key="correct horse")
        self.assertEqual(extract_text(output, key="correct horse"), message)

    def test_wrong_key_fails(self):
        output = self.root / "marked.png"
        embed_text(self.source, output, "secret", key="right")
        with self.assertRaises(StegError):
            extract_text(output, key="wrong")

    def test_image_payload_round_trip(self):
        hidden = self.root / "hidden.png"
        Image.new("RGBA", (16, 12), (190, 44, 72, 180)).save(hidden)
        output = self.root / "image-marked.png"
        result = embed_image(self.source, output, hidden, key="picture")
        recovered = extract_payload(output, key="picture")
        self.assertEqual(recovered.kind, "image")
        self.assertEqual(recovered.media_type, "image/webp")
        self.assertEqual((recovered.width, recovered.height), (16, 12))
        self.assertGreater(result.stored_bytes, 0)
        with Image.open(io.BytesIO(recovered.data)) as image:
            self.assertEqual(image.size, (16, 12))

    def test_jpeg_recompression(self):
        marked = self.root / "marked.png"
        recompressed = self.root / "recompressed.jpg"
        message = "This survives JPEG recompression. 這是中文。"
        embed_text(self.source, marked, message, key="jpeg-test", strength=64, redundancy=5)
        with Image.open(marked) as image:
            image.convert("RGB").save(recompressed, quality=70, subsampling=2)
        self.assertEqual(
            extract_text(recompressed, key="jpeg-test", strength=64),
            message,
        )

    def test_webp_transcode(self):
        marked = self.root / "marked.png"
        transcoded = self.root / "transcoded.webp"
        message = "WebP format conversion"
        embed_text(self.source, marked, message, key="webp-test", strength=64, redundancy=5)
        with Image.open(marked) as image:
            image.convert("RGB").save(transcoded, format="WEBP", quality=75, method=6)
        self.assertEqual(
            extract_text(transcoded, key="webp-test", strength=64),
            message,
        )

    def test_capacity_changes_with_redundancy(self):
        low = image_capacity(512, 512, 3).max_payload_bytes
        high = image_capacity(512, 512, 7).max_payload_bytes
        self.assertGreater(low, high)

    def test_bch_capacity_exceeds_legacy_convolutional_code(self):
        result = image_capacity(512, 512, 3)
        header_carriers = steg._coded_carrier_count(steg.HEADER.size, steg.HEADER_REDUNDANCY)
        remaining = result.carriers - header_carriers
        legacy_bits = max(0, remaining // 6 - steg.MEMORY)
        legacy_capacity = max(0, legacy_bits // 8 - 4)
        self.assertGreater(result.max_payload_bytes, legacy_capacity)
        self.assertGreaterEqual(result.max_payload_bytes, math.floor(legacy_capacity * 1.4))

    def test_bch_corrects_three_errors_in_each_codeword(self):
        data = [(index * 7 + 3) % 2 for index in range(steg.BCH_K)]
        encoded = steg._bch_encode_block(data)
        for position in (0, 17, 62):
            encoded[position] ^= 1
        self.assertEqual(steg._bch_decode_block(encoded), data)

    def test_bch_capacity_boundary_round_trip(self):
        output = self.root / "full.png"
        capacity = image_capacity(768, 768, 3).max_payload_bytes
        message = "x" * capacity
        embed_text(self.source, output, message)
        self.assertEqual(extract_text(output), message)

    def test_reads_legacy_v1_watermark(self):
        output = self.root / "legacy.png"
        message = "舊版卷積碼仍可讀取"
        payload = message.encode("utf-8")
        ycbcr, alpha = steg._open_image(self.source)
        height, width = ycbcr.shape[:2]
        order = steg._carrier_order(width, height, "legacy-key")
        header = steg.HEADER.pack(
            steg.MAGIC, steg.LEGACY_VERSION, steg.DEFAULT_REDUNDANCY, len(payload)
        )
        position = steg._embed_convolutional_stream(
            ycbcr[:, :, 0],
            order,
            0,
            header,
            steg.HEADER_REDUNDANCY,
            steg.DEFAULT_STRENGTH,
            width,
        )
        checksum = struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        steg._embed_convolutional_stream(
            ycbcr[:, :, 0],
            order,
            position,
            payload + checksum,
            steg.DEFAULT_REDUNDANCY,
            steg.DEFAULT_STRENGTH,
            width,
        )
        steg._save_image(ycbcr, alpha, output, 95)
        self.assertEqual(extract_text(output, key="legacy-key"), message)


if __name__ == "__main__":
    unittest.main()
