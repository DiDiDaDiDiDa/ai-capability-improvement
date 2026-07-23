"""Geometry helpers — more symbols across a second module."""

import math


def circle_area(radius: float) -> float:
    """Area of a circle. Retrieval target for query 'area'."""
    return math.pi * radius * radius


def rectangle_area(width: float, height: float) -> float:
    """Area of a rectangle."""
    return width * height


class Point:
    """2D point with a distance method — class symbol for repo-map."""

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y

    def distance_to(self, other: "Point") -> float:
        """Euclidean distance between two points."""
        return math.hypot(self.x - other.x, self.y - other.y)
