import unittest

from calculator import add


class CalculatorTests(unittest.TestCase):
    def test_adds_positive_and_negative_integers(self) -> None:
        self.assertEqual(add(7, -2), 5)


if __name__ == "__main__":
    unittest.main()
