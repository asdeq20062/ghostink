import io
import unittest
import zlib

import numpy as np
from PIL import Image

from app import app
from lsb_steg import LEGACY_HEADER, LEGACY_VERSION, MAGIC


def sample_png() -> bytes:
    rng = np.random.default_rng(42)
    pixels = rng.integers(0, 256, (512, 512, 3), dtype=np.uint8)
    stream = io.BytesIO()
    Image.fromarray(pixels, "RGB").save(stream, format="PNG")
    return stream.getvalue()


def hidden_png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGBA", (12, 10), (23, 137, 114, 220)).save(stream, format="PNG")
    return stream.getvalue()


def hidden_image(image_format: str) -> bytes:
    stream = io.BytesIO()
    image = Image.new("RGB", (18, 14), (31, 142, 119))
    image.save(stream, format=image_format)
    return stream.getvalue()


def legacy_lsb_image(carrier_data: bytes, secret_data: bytes) -> bytes:
    with Image.open(io.BytesIO(carrier_data)) as carrier, Image.open(io.BytesIO(secret_data)) as secret:
        width, height = secret.size
        packet = LEGACY_HEADER.pack(
            MAGIC,
            LEGACY_VERSION,
            len(secret_data),
            width,
            height,
            zlib.crc32(secret_data) & 0xFFFFFFFF,
        ) + secret_data
        bits = np.unpackbits(np.frombuffer(packet, dtype=np.uint8))
        pixels = np.asarray(carrier.convert("RGB"), dtype=np.uint8).copy()
        flat = pixels.reshape(-1)
        flat[: len(bits)] = (flat[: len(bits)] & 0xFE) | bits
        stream = io.BytesIO()
        Image.fromarray(pixels).save(stream, format="PNG")
        return stream.getvalue()


class WebAppTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.image = sample_png()

    def image_upload(self, data: bytes | None = None):
        return io.BytesIO(data if data is not None else self.image), "sample.png"

    def test_home_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("影像隱寫浮水印".encode(), response.data)
        self.assertIn("貼上圖片".encode(), response.data)
        self.assertIn("要隱藏的圖片".encode(), response.data)
        self.assertIn("按一下選擇，或貼上圖片".encode(), response.data)
        self.assertIn("按右鍵使用瀏覽器選單下載".encode(), response.data)
        self.assertIn("文字隱寫".encode(), response.data)
        self.assertIn("LSB 隱寫".encode(), response.data)
        self.assertIn("請保留 PNG 格式".encode(), response.data)
        self.assertIn("U+200B".encode(), response.data)
        self.assertIn("U+200C".encode(), response.data)
        self.assertIn(">COPY<".encode(), response.data)

    def test_capacity(self):
        response = self.client.post(
            "/api/capacity",
            data={"image": self.image_upload(), "redundancy": "3"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["width"], 512)
        self.assertGreater(payload["max_payload_bytes"], 0)

    def test_embed_and_extract_without_key(self):
        text = "不用金鑰的測試文字"
        embedded = self.client.post(
            "/api/embed",
            data={
                "image": self.image_upload(),
                "text": text,
                "key": "",
                "strength": "56",
                "redundancy": "3",
                "quality": "95",
                "output_format": "png",
            },
        )
        self.assertEqual(embedded.status_code, 200)
        self.assertEqual(embedded.mimetype, "image/png")

        extracted = self.client.post(
            "/api/extract",
            data={
                "image": self.image_upload(embedded.data),
                "key": "",
                "strength": "56",
            },
        )
        self.assertEqual(extracted.status_code, 200)
        self.assertEqual(extracted.get_json()["text"], text)

    def test_embed_requires_text(self):
        response = self.client.post(
            "/api/embed",
            data={"image": self.image_upload(), "text": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("請輸入", response.get_json()["error"])

    def test_embed_and_extract_hidden_image(self):
        embedded = self.client.post(
            "/api/embed",
            data={
                "image": self.image_upload(),
                "payload_type": "image",
                "hidden_image": (io.BytesIO(hidden_png()), "secret.png"),
                "key": "image-key",
                "strength": "56",
                "redundancy": "3",
                "quality": "95",
                "output_format": "png",
            },
        )
        self.assertEqual(embedded.status_code, 200)
        self.assertEqual(embedded.headers["X-Payload-Type"], "image")

        extracted = self.client.post(
            "/api/extract",
            data={
                "image": self.image_upload(embedded.data),
                "key": "image-key",
                "strength": "56",
            },
        )
        self.assertEqual(extracted.status_code, 200)
        payload = extracted.get_json()
        self.assertEqual(payload["type"], "image")
        self.assertEqual(payload["mime_type"], "image/webp")
        self.assertEqual((payload["width"], payload["height"]), (12, 10))

    def test_lsb_capacity(self):
        response = self.client.post(
            "/api/lsb/capacity",
            data={"image": self.image_upload()},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual((payload["width"], payload["height"]), (512, 512))
        self.assertGreater(payload["max_payload_bytes"], 90_000)

    def test_lsb_embed_and_extract_hidden_image_losslessly(self):
        secret = hidden_png()
        embedded = self.client.post(
            "/api/lsb/embed",
            data={
                "image": self.image_upload(),
                "hidden_image": (io.BytesIO(secret), "secret.png"),
            },
        )
        self.assertEqual(embedded.status_code, 200)
        self.assertEqual(embedded.mimetype, "image/png")
        self.assertEqual(embedded.headers["X-Hidden-Image-Size"], "12x10")

        extracted = self.client.post(
            "/api/lsb/extract",
            data={"image": self.image_upload(embedded.data)},
        )
        self.assertEqual(extracted.status_code, 200)
        self.assertEqual(extracted.mimetype, "image/png")
        self.assertEqual(extracted.headers["X-Hidden-Image-Size"], "12x10")
        self.assertEqual(extracted.data, secret)
        with Image.open(io.BytesIO(secret)) as original, Image.open(io.BytesIO(extracted.data)) as restored:
            self.assertEqual(original.convert("RGBA").tobytes(), restored.convert("RGBA").tobytes())

    def test_lsb_preserves_multiple_secret_image_formats_exactly(self):
        formats = {
            "JPEG": ("secret.jpeg", "JPEG"),
            "PNG": ("secret.png", "PNG"),
            "WEBP": ("secret.webp", "WEBP"),
            "BMP": ("secret.bmp", "BMP"),
            "GIF": ("secret.gif", "GIF"),
            "TIFF": ("secret.tiff", "TIFF"),
        }
        for image_format, (filename, expected_format) in formats.items():
            with self.subTest(image_format=image_format):
                secret = hidden_image(image_format)
                embedded = self.client.post(
                    "/api/lsb/embed",
                    data={
                        "image": self.image_upload(),
                        "hidden_image": (io.BytesIO(secret), filename),
                    },
                )
                self.assertEqual(embedded.status_code, 200)
                self.assertEqual(embedded.headers["X-Hidden-Image-Bytes"], str(len(secret)))
                self.assertEqual(embedded.headers["X-Hidden-Image-Format"], expected_format)

                extracted = self.client.post(
                    "/api/lsb/extract",
                    data={"image": self.image_upload(embedded.data)},
                )
                self.assertEqual(extracted.status_code, 200)
                self.assertTrue(extracted.mimetype.startswith("image/"))
                self.assertEqual(extracted.headers["X-Hidden-Image-Format"], expected_format)
                self.assertEqual(extracted.data, secret)

    def test_lsb_extract_rejects_plain_image(self):
        response = self.client.post(
            "/api/lsb/extract",
            data={"image": self.image_upload()},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("LSB", response.get_json()["error"])

    def test_lsb_extract_reads_legacy_png_payload(self):
        secret = hidden_png()
        legacy = legacy_lsb_image(self.image, secret)
        response = self.client.post(
            "/api/lsb/extract",
            data={"image": self.image_upload(legacy)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        self.assertEqual(response.data, secret)


if __name__ == "__main__":
    unittest.main()
