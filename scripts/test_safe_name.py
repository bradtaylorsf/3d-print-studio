#!/usr/bin/env python3
"""safe_name must reject a trailing newline (regex `$` matches before one).
Stdlib only: python scripts/test_safe_name.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "studio"))
import server  # noqa: E402


class SafeName(unittest.TestCase):
    def test_accepts_plain_names(self):
        for n in ("dragon", "my model.stl", "a-b_c.1"):
            self.assertTrue(server.safe_name(n), n)

    def test_rejects_trailing_newline(self):
        for n in ("dragon\n", "model.stl\n", "a b\n"):
            self.assertFalse(server.safe_name(n), repr(n))

    def test_rejects_traversal_and_hidden(self):
        for n in ("", "..", "a/../b", ".hidden", "a/b"):
            self.assertFalse(server.safe_name(n), repr(n))


if __name__ == "__main__":
    unittest.main()
