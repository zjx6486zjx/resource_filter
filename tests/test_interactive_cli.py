from __future__ import annotations

import os
import unittest
from unittest import mock

from resource_filter.interactive_cli import InteractiveAnswers, build_cli_args, resolve_user_data_dir


class InteractiveCliTests(unittest.TestCase):
    def test_build_cli_args_for_mj_inspiration(self) -> None:
        answers = InteractiveAnswers(
            site="mj",
            mode="inspiration",
            max_items=20,
            entry_url="https://www.midjourney.com/explore?tab=top",
            proxy_server="127.0.0.1:7890",
        )

        with mock.patch.dict(
            os.environ,
            {
                "LUNARSAND_API_BASE": "http://127.0.0.1:8000/api",
                "RESOURCE_FILTER_BROWSER_CHANNEL": "chrome",
                "RESOURCE_FILTER_HEADFUL": "1",
                "RESOURCE_FILTER_SLOW_MO": "200",
            },
            clear=True,
        ):
            args = build_cli_args(answers)

        self.assertEqual(
            args,
            [
                "--site",
                "mj",
                "--api-base",
                "http://127.0.0.1:8000/api",
                "--browser-channel",
                "chrome",
                "--proxy-server",
                "127.0.0.1:7890",
                "--headful",
                "--slow-mo",
                "200",
                "--max-items",
                "20",
                "inspiration",
                "--entry-url",
                "https://www.midjourney.com/explore?tab=top",
            ],
        )

    def test_resolve_user_data_dir_switches_to_matching_default_profile(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "RESOURCE_FILTER_USER_DATA_DIR": "/tmp/jimeng_profile",
                "RESOURCE_FILTER_DEFAULT_JIMENG_USER_DATA_DIR": "/tmp/jimeng_profile",
                "RESOURCE_FILTER_DEFAULT_XHS_USER_DATA_DIR": "/tmp/xhs_profile",
            },
            clear=True,
        ):
            self.assertEqual(resolve_user_data_dir("xhs"), "/tmp/xhs_profile")

    def test_build_cli_args_for_xhs_tabs(self) -> None:
        answers = InteractiveAnswers(
            site="xhs",
            mode="inspiration",
            max_items=30,
            entry_url="https://www.xiaohongshu.com/explore",
            keyword="古风汉服",
            tab_limit=4,
            tab_names="综合,仙侠风",
        )

        with mock.patch.dict(os.environ, {"LUNARSAND_API_BASE": "http://127.0.0.1:8000/api"}, clear=True):
            args = build_cli_args(answers)

        self.assertIn("--tab-limit", args)
        self.assertIn("4", args)
        self.assertIn("--tab-names", args)
        self.assertIn("综合,仙侠风", args)

    def test_build_cli_args_for_jingdong_inspiration(self) -> None:
        answers = InteractiveAnswers(
            site="jingdong",
            mode="inspiration",
            max_items=20,
            entry_url="https://re.jd.com/search",
            keyword="古风衣服 汉服",
        )

        with mock.patch.dict(os.environ, {"LUNARSAND_API_BASE": "http://127.0.0.1:8000/api"}, clear=True):
            args = build_cli_args(answers)

        self.assertIn("--site", args)
        self.assertIn("jingdong", args)
        self.assertIn("--entry-url", args)
        self.assertIn("https://re.jd.com/search", args)
        self.assertIn("--keyword", args)
        self.assertIn("古风衣服 汉服", args)


if __name__ == "__main__":
    unittest.main()
