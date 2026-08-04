import io
import unittest

import numpy as np
from PIL import Image

from app import app


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


if __name__ == "__main__":
    unittest.main()
