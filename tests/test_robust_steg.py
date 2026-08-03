import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from robust_steg import StegError, embed_text, extract_text, image_capacity


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


if __name__ == "__main__":
    unittest.main()
