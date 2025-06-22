"""Classes representing various Skybrush show file formats."""

from contextlib import aclosing
from enum import IntEnum, IntFlag
from functools import partial
from io import BytesIO, SEEK_END
from itertools import count
from math import floor
from struct import Struct
from trio import wrap_file
from typing import (
    AsyncIterable,
    Awaitable,
    Callable,
    ClassVar,
    IO,
    Iterable,
    Optional,
    Sequence,
    Union,
    Tuple
)
from .position import PositionList
from .color import ColorList
import struct
from .trajectory import TrajectorySegment, TrajectorySpecification
from .utils import Point
from pyledctrl.executor import Color

_RESERVE_BYTE: bytes = b"\x00"
_ESSP_BINARY_FILE_MARKER: bytes = b"ESS"
_ESSP_FILE_HEADER: list[bytes] = [
    # Version 0 -- never existed
    b"",
    # Version 1 header
    b"ESS\x01",
]


async def _read_exactly(
    fp,
    length: int,
    offset: Optional[int] = None,
    *,
    message: str = "unexpected end of block in essp file",
):
    if offset is not None:
        await fp.seek(offset)
    data = await fp.read(length)
    if len(data) != length:
        raise IOError(message)
    return data


__all__ = ("EsspShowFile",)


class EsspFormatBlockType(IntEnum):
    """Enum representing the possible block types in a Essp binary file."""

    POSITION = 1
    COLOR = 2


class EsspFileBlock:
    """Class representing a single block in a Essp binary file."""

    def __init__(
        self,
        type: int,
        contents: Union[Optional[bytes], Callable[[], Awaitable[bytes]]],
    ):
        """Constructor.

        Parameters:
            type: type of the block
            contents: the contents of the block, or an async function that resolves
                to the contents of the block when invoked with no arguments
        """
        self.type = type

        if callable(contents):
            self._loader = contents
            self._contents = None
        else:
            self._loader = None
            self._contents = contents

    @property
    def consumed(self) -> bool:
        """Whether the block has already been consumed, i.e. loaded from the
        backing awaitable.

        Returns True if the block was constructed without an awaitable.
        """
        return self._loader is None

    async def read(self) -> bytes:
        """Reads the raw body of this block."""
        if self._contents is None and self._loader is not None:
            self._contents = await self._loader()
            self._loader = None
        return self._contents  # type: ignore


class EsspShowFile:
    """Class representing a Essp binary show file, backed by a
    file-like object.
    """

    _checksum_validated: bool = False
    """Whether the checksum of the file has already been validated."""

    _start_of_crc_bytes: Optional[int] = None
    """Byte index of the CRC bytes in the show file, `None` if not known yet
    or if the show has no CRC bytes.
    """

    _start_of_first_block: Optional[int] = None
    """Byte index of the first block in the show file, `None` if not known yet."""

    _header_section_struct: ClassVar[Struct] = Struct("<BBHI")

    @classmethod
    def create_in_memory(cls, version: int = 1):
        return cls.from_bytes(data=None, version=version)

    @classmethod
    def from_bytes(cls, data: Optional[bytes] = None, *, version: int = 2):
        """Creates an in-memory Skybrush binary show file.

        Parameters:
            data: the show file data; `None` means to create a new show file
                with a header but no blocks yet
            version: the version number of the binary show file when it is
                created anew; ignored when `data` is not `None`
        """
        if not data:
            if version >= 1 and version < len(_ESSP_FILE_HEADER):
                data = _ESSP_FILE_HEADER[version]
                # header size 1
                data += struct.pack("B", 15)
                # path to crc 4
                data += _RESERVE_BYTE * 4
                # 2 reserve
                data += _RESERVE_BYTE * 2
                # 2 unit millimeter factor
                data += Struct("e").pack(1.0)
                # 1 section count
                data += struct.pack("B", 2)
                # 1 section header size
                data += struct.pack("B", 5)
            else:
                raise RuntimeError(f"Unsupported version number: {version}")
        return cls(BytesIO(data))

    def __init__(self, fp: IO[bytes]):
        """Constructor.

        Parameters:
            fp: the file-like object that stores the show data
        """
        if isinstance(fp, BytesIO):
            self._buffer = fp

        self._checksum_validated = False
        self._fp = wrap_file(fp)
        self._version = None
        self._start_of_first_block = None

    async def __aenter__(self):
        await self._fp.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_value, tb):
        return await self._fp.__aexit__(exc_type, exc_value, tb)

    # look later
    async def _rewind(self) -> None:
        """Rewinds the internal read/write pointer of the underlying file-like
        object to the start of the first block in the file.
        """
        if self._start_of_first_block is None:
            await self._fp.seek(0)

            self._version = await self._expect_header()
            if self._version != 1:
                raise RuntimeError("only version 1 files are supported")

            # if self._features & SkybrushBinaryFileFeatures.CRC32:
            #     self._start_of_crc_bytes = await self._fp.tell()
            #     await self._fp.read(4)
            # else:
            #     self._start_of_crc_bytes = None

            self._start_of_first_block = await self._fp.tell()
        else:
            await self._fp.seek(self._start_of_first_block)

    async def _expect_header(self) -> int:
        """Reads the beginning of the buffer to check whether the ESSP binary
        file header is to be found there. Throws a RuntimeError if the file
        header is invalid.

        Returns:
            the ESSP file schema version
        """
        header = await self._fp.read(3)
        if header != _ESSP_BINARY_FILE_MARKER:
            raise RuntimeError(f"expected Essp file header, got {header!r}")

        version = await self._fp.read(1)
        return ord(version)

    async def add_header_section_block(
        self, type: EsspFormatBlockType, section_fps: int, section_size: int
    ):
        """Adds header section to the end of the ESSP File"""
        seekable = self._fp.seekable()
        if seekable:
            await self._fp.seek(0, SEEK_END)
        # Change the maximum size to be compatible with the real header
        # header = self._header_section_struct.pack(
        #     type, _RESERVE_BYTE, section_fps, section_size
        # )
        header = struct.pack("B", type) + _RESERVE_BYTE + struct.pack("HI",section_fps, section_size )
        await self._fp.write(header)

    async def add_block(self, body: bytes) -> None:
        """Adds a new block to the end of the ESSP file."""
        seekable = self._fp.seekable()

        if seekable:
            await self._fp.seek(0, SEEK_END)

        if len(body) >= 65536:
            raise ValueError(
                f"body too large; maximum allowed length is 65535 bytes, got {len(body)}"
            )
        await self._fp.write(body)

    def get_trajectory(self, trajectory: TrajectorySpecification):
        encoded = PositionOnlyEncoder().encode(trajectory)
        return encoded, len(encoded)

    def get_colors(self, color_tuple: Tuple[float, Color]):
        encoded = bytearray()
        for _, color in color_tuple:
            r, g, b = color
            encoded.extend(struct.pack("BBB", r, g, b))  # 1 byte each
        return bytes(encoded), len(bytes(encoded))

    def get_buffer(self) -> IO[bytes]:
        """Returns the underlying buffer of the file if it is backed by an
        in-memory buffer.
        """
        if self._buffer:
            return self._buffer

        raise RuntimeError("file is not backed by an in-memory buffer")

    def get_contents(self) -> bytes:
        """Returns the contents of the underlying in-memory buffer of the file
        if it is backed by an in-memory buffer.

        Parameters:
            finalize: whether to finalize the contents before returning the
                result
        """
        if not self._buffer:
            raise RuntimeError("file is not backed by an in-memory buffer")
        return self._buffer.getvalue()

    # async def validate_checksum(self) -> None:
    #     """Validates the checksum of the file. Assumes that the file is
    #     seekable.

    #     No-op if the file header declares that the file has no checksum.

    #     Raises:
    #         RuntimeError: if the checksum of the file does not match the
    #             expected value
    #     """
    #     if not self.features & SkybrushBinaryFileFeatures.CRC32:
    #         return

    #     expected_crc = await self._get_expected_crc32()

    #     assert self._start_of_crc_bytes is not None

    #     position: int = await self._fp.tell()
    #     try:
    #         await self._fp.seek(self._start_of_crc_bytes)
    #         observed_crc: bytes = await _read_exactly(self._fp, 4)
    #     finally:
    #         await self._fp.seek(position)

    #     if observed_crc != expected_crc:
    #         expected = expected_crc.hex()
    #         observed = observed_crc.hex()
    #         raise RuntimeError(f"CRC error, expected {expected}, got {observed}")

    #     self._checksum_validated = True

    @property
    def version(self) -> int:
        """Returns the version number of the file."""
        if self._version is None:
            raise RuntimeError("version header was not read yet")
        return self._version

    async def add_position(self, pos_list: PositionList) -> None:
        encoder = PositionListEncoder()
        return await self.add_block(encoder.encode(pos_list))

    async def add_color(self, colors: ColorList) -> None:
        encoder = ColorListEncoder()
        return await self.add_block(encoder.encode(colors))


class PositionListEncoder:

    _pos_struct: ClassVar[Struct] = Struct("<eee")  # x, y, z: 3 float

    def encode(self, positions: PositionList) -> bytes:
        chunks: list[bytes] = []

        # Encode all positions
        for pos in positions.positions:
            chunks.append(self._pos_struct.pack(pos.x, pos.y, pos.z))

        return b"".join(chunks)


class ColorListEncoder:

    _color_struct: ClassVar[Struct] = Struct("<BBB")

    def encode(self, colors: ColorList) -> bytes:
        chunks: list[bytes] = []
        for color in colors.colors:
            chunks.append(self._color_struct.pack(color.r, color.g, color.b))

        return b"".join(chunks)



class PositionOnlyEncoder:
    """Encodes positions (x, y, z) into binary format."""
    _point_struct: ClassVar[Struct] = Struct("<hhh")

    def __init__(self, scale: float = 1.0):
        self._scale = 1000 / scale

    def _scale_point(self, point: Point) -> Tuple[int, int, int]:
        return (
            int(point[0] * self._scale),
            int(point[1] * self._scale),
            int(point[2] * self._scale),
        )

    def encode(self, spec: TrajectorySpecification) -> bytes:
        """Encodes only the position part of the trajectory."""
        encoded = bytearray()
        for point in spec.iter_positions():
            x, y, z = self._scale_point(point)
            encoded.extend(self._point_struct.pack(x, y, z))
        return bytes(encoded)
