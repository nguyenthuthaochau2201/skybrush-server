from dataclasses import dataclass
from typing import Sequence, Union

__all__ = (
    "Color",
    "ColorList",
)


@dataclass
class Color:
    r: int
    g: int
    b: int


class ColorList:
    def __init__(self, colors: Sequence[Union[Color, tuple[int, int, int]]] = []):
        self.colors = [c if isinstance(c, Color) else Color(*c) for c in colors]

    @classmethod
    def from_json(cls, data: dict):
        """Creates a ColorList from a JSON representation."""
        version = data.get("version")
        if version != 1:
            raise ValueError("Only version 1 is supported")

        colors_data = data.get("colors", [])
        if not isinstance(colors_data, list):
            raise ValueError("colors must be a list")

        colors = [tuple(c) for c in colors_data]
        for c in colors:
            if not (isinstance(c, (list, tuple)) and len(c) == 3):
                raise ValueError("Each color must be a list or tuple of length 3")

        return cls(colors=colors)
