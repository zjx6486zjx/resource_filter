from __future__ import annotations

import unittest

from resource_filter.adapters.jimeng import JimengAdapter


class JimengAdapterTests(unittest.TestCase):
    def test_has_enough_likes_requires_at_least_10_when_verified(self) -> None:
        adapter = JimengAdapter()

        self.assertFalse(adapter._has_enough_likes(9, allow_unknown=False))
        self.assertTrue(adapter._has_enough_likes(10, allow_unknown=False))
        self.assertTrue(adapter._has_enough_likes(11, allow_unknown=False))

    def test_has_enough_likes_allows_unknown_only_before_detail_check(self) -> None:
        adapter = JimengAdapter()

        self.assertTrue(adapter._has_enough_likes(None, allow_unknown=True))
        self.assertFalse(adapter._has_enough_likes(None, allow_unknown=False))


if __name__ == "__main__":
    unittest.main()
