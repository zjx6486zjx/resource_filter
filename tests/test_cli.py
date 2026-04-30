from __future__ import annotations

import os
import unittest
from unittest import mock

from resource_filter.cli import build_adapter, build_parser, normalize_cli_args


class CliTests(unittest.TestCase):
    def test_api_base_defaults_to_api_prefix(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            parser = build_parser()

        args = parser.parse_args(["inspiration", "--entry-url", "https://example.com"])

        self.assertEqual(args.api_base, "http://127.0.0.1:8000/api")

    def test_build_adapter_supports_mj(self) -> None:
        adapter = build_adapter("mj")

        self.assertEqual(adapter.site_name, "mj")

    def test_build_adapter_supports_taobao(self) -> None:
        adapter = build_adapter("taobao")

        self.assertEqual(adapter.site_name, "taobao")

    def test_build_adapter_supports_jingdong_aliases(self) -> None:
        adapter = build_adapter("jingdong")
        alias_adapter = build_adapter("jd")

        self.assertEqual(adapter.site_name, "jingdong")
        self.assertEqual(alias_adapter.site_name, "jingdong")

    def test_build_adapter_supports_baidu_aliases(self) -> None:
        adapter = build_adapter("baidu")
        alias_adapter = build_adapter("bd")

        self.assertEqual(adapter.site_name, "baidu")
        self.assertEqual(alias_adapter.site_name, "baidu")

    def test_normalize_cli_args_moves_cdp_url_before_subcommand(self) -> None:
        normalized = normalize_cli_args(
            [
                "inspiration",
                "--entry-url",
                "https://example.com",
                "--cdp-url",
                "http://127.0.0.1:9222",
            ]
        )

        self.assertEqual(
            normalized,
            [
                "--cdp-url",
                "http://127.0.0.1:9222",
                "inspiration",
                "--entry-url",
                "https://example.com",
            ],
        )

    def test_normalize_cli_args_moves_import_tuning_options(self) -> None:
        normalized = normalize_cli_args(
            [
                "inspiration",
                "--entry-url",
                "https://example.com",
                "--api-timeout",
                "180",
                "--api-retries=4",
                "--import-delay",
                "3",
            ]
        )

        self.assertEqual(
            normalized,
            [
                "--api-timeout",
                "180",
                "--api-retries=4",
                "--import-delay",
                "3",
                "inspiration",
                "--entry-url",
                "https://example.com",
            ],
        )


if __name__ == "__main__":
    unittest.main()
