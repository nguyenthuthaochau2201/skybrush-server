from dataclasses import dataclass
from typing import Sequence, Union

__all__ = (
    "Position",
    "PositionList",
)


@dataclass
class Position:
    x: float
    y: float
    z: float


class PositionList:
    def __init__(
        self, positions: Sequence[Union[Position, tuple[float, float, float]]] = []
    ):
        self.positions = [
            p if isinstance(p, Position) else Position(*p) for p in positions
        ]

    @classmethod
    def from_json(cls, data: dict):
        """Creates a PositionList from a JSON representation."""
        version = data.get("version")
        if version != 1:
            raise ValueError("Only version 1 is supported")

        positions_data = data.get("positions", [])
        if not isinstance(positions_data, list):
            raise ValueError("positions must be a list")

        positions = [tuple(p) for p in positions_data]
        for p in positions:
            if not (isinstance(p, (list, tuple)) and len(p) == 3):
                raise ValueError("Each position must be a list or tuple of length 3")

        return cls(positions=positions)
