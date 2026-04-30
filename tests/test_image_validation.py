from __future__ import annotations

import struct
import unittest

from resource_filter.image_validation import (
    looks_like_thumbnail_url,
    promoted_image_url_candidates,
    read_image_size,
    validate_image_bytes,
)


class ImageValidationTests(unittest.TestCase):
    def test_validate_png_rejects_image_below_300_square(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 299, 300) + b"\x08\x02\x00\x00\x00"

        result = validate_image_bytes(png)

        self.assertFalse(result.ok)
        self.assertEqual(result.width, 299)
        self.assertEqual(result.height, 300)

    def test_validate_png_accepts_300_square(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 300, 300) + b"\x08\x02\x00\x00\x00"

        result = validate_image_bytes(png)

        self.assertTrue(result.ok)
        self.assertEqual((result.width, result.height), (300, 300))

    def test_validate_rejects_when_one_side_is_under_300(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 400, 200) + b"\x08\x02\x00\x00\x00"

        result = validate_image_bytes(png)

        self.assertFalse(result.ok)
        self.assertEqual((result.width, result.height), (400, 200))

    def test_read_webp_vp8x_size(self) -> None:
        webp = bytearray(b"RIFF\x16\x00\x00\x00WEBPVP8X\n\x00\x00\x00\x00\x00\x00\x00")
        webp.extend((639).to_bytes(3, "little"))
        webp.extend((479).to_bytes(3, "little"))

        self.assertEqual(read_image_size(bytes(webp)), (640, 480))

    def test_thumbnail_url_detection(self) -> None:
        self.assertTrue(looks_like_thumbnail_url("https://cdn.midjourney.com/demo/0_0_128_N.webp"))
        self.assertTrue(looks_like_thumbnail_url("https://example.com/path/thumb_240x240.jpg"))
        self.assertFalse(looks_like_thumbnail_url("https://example.com/path/full.jpg"))

    def test_promoted_image_url_candidates_include_original_forms(self) -> None:
        self.assertIn(
            "https://cdn.midjourney.com/demo/0_0.jpeg",
            promoted_image_url_candidates("https://cdn.midjourney.com/demo/0_0_128_N.webp"),
        )
        self.assertIn(
            "https://cdn.midjourney.com/demo/0_0.png",
            promoted_image_url_candidates("https://cdn.midjourney.com/demo/0_0_128_N.webp"),
        )
        self.assertIn(
            "https://sns-webpic-qc.xhscdn.com/path/image",
            promoted_image_url_candidates("https://sns-webpic-qc.xhscdn.com/path/image!nd_dft_wlteh_webp_3"),
        )
        self.assertIn(
            "https://img14.360buyimg.com/n0/jfs/t1/demo.jpg",
            promoted_image_url_candidates("https://m.360buyimg.com/mobilecms/s500x500_jfs/t1/demo.jpg!q70.dpg"),
        )


if __name__ == "__main__":
    unittest.main()
