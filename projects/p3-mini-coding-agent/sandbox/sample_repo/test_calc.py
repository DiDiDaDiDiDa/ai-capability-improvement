"""Minimal tests (stdlib unittest). Agent must make these pass."""

import unittest

from calc import add, mul


class TestCalc(unittest.TestCase):
    def test_add(self) -> None:
        self.assertEqual(add(2, 2), 4)
        self.assertEqual(add(10, 5), 15)

    def test_mul(self) -> None:
        self.assertEqual(mul(3, 4), 12)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
