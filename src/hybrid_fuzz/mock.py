from collections.abc import Iterable
from typing import Any, Literal, override
from src.hybrid_fuzz.concolic import ConcolicByte, ConcolicList
import struct

from src.hybrid_fuzz import (
  ConcolicSlice,
)


def symbolic_join(
  separator: bytes,
  iterable: Iterable[
    ConcolicList | ConcolicSlice | ConcolicByte | bytes | list[int] | bytearray
  ],
) -> ConcolicList:
  """
  Drop-in replacement for bytes.join() that handles Concolic objects.
  Usage: symbolic_join(b'.', labels)
  """
  result_data: list[ConcolicByte] = []

  # 1. Convert separator to a list of ConcolicBytes once

  sep_list: list[ConcolicByte] = [
    ConcolicByte(b, f"sep_{idx}") for idx, b in enumerate[int](separator)
  ]

  first = True
  for item in iterable:
    if not first:
      # Add separator between items
      result_data.extend(sep_list)
    first = False

    # Add the item (handle Slice, List, Bytes, or Ints)
    if isinstance(item, ConcolicList):
      result_data.extend(item.data)
    elif isinstance(item, (bytes, list, bytearray)):
      for idx, b in enumerate(item):
        result_data.append(ConcolicByte(b, f"item_{idx}"))
    elif isinstance(item, ConcolicSlice):
      result_data.extend(item.data)
    elif isinstance(item, ConcolicByte):  # pyright: ignore[reportUnnecessaryIsInstance]
      result_data.append(item)
    else:
      raise TypeError(f"symbolic_join cannot handle type {type(item)}")

  return ConcolicList(result_data)  # pyright: ignore[reportArgumentType]


class MockFile:
  def __init__(self, data: ConcolicList):
    self.data: ConcolicList = data
    self._pointer: int = 0

  def read(self, size: int = -1):
    if size == -1:
      # Return everything from current pointer
      res = self.data[self._pointer :]
      self._pointer = len(self.data)
      return res
    else:
      # Return a slice (this uses your ConcolicList slice logic)
      # Note: handle out-of-bounds gracefully if needed
      end = self._pointer + size
      if end > len(self.data):
        end = len(self.data)
      res = self.data[self._pointer : end]
      self._pointer = end
      return res

  # Support 'with open(...) as f:'
  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    pass

  def close(self):
    pass


class MockInt(int):
  """A mock integer class to simulate int.from_bytes behavior for ConcolicList and ConcolicSlice and ConcolicByte."""

  @classmethod
  @override
  def from_bytes(  # pyright: ignore[reportIncompatibleMethodOverride]
    cls,
    bytes,  # pyright: ignore[reportMissingParameterType]
    byteorder: Literal["big", "little"] = "big",
    *,
    signed: bool = False,
  ):
    if isinstance(bytes, (ConcolicList, ConcolicSlice, ConcolicByte)):
      # Convert ConcolicList/Slice/Byte to integer by extracting concrete values
      return bytes.as_int(byteorder=byteorder, signed=signed)
      # Fallback to real behavior
    return super().from_bytes(bytes, byteorder=byteorder, signed=signed)


class MockSet(
  set  # pyright: ignore[reportMissingTypeArgument]
):  # to capture `in` operations on sets
  @override
  def __contains__(self, item: object) -> bool:
    # Force linear scan to trigger __eq__ on each element
    for elem in self:  # pyright: ignore[reportUnknownVariableType]
      if elem == item:
        return True
    return False


class MockRange:
  def __init__(self, *args):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    self._range: range = range(*args)  # pyright: ignore[reportUnknownArgumentType]

  def __contains__(self, item: object) -> bool:
    # 1. Capture the Symbolic Constraints (Low <= Item < High)
    # We assume 'item' is ConcolicValue/Byte
    # This comparison triggers the constraint recording:
    in_bounds: Any = (item >= self._range.start) and (item < self._range.stop)  # pyright: ignore[reportOperatorIssue, reportExplicitAny, reportUnknownVariableType]

    # 2. But we must still return a concrete bool for Python control flow
    return bool(in_bounds)  # pyright: ignore[reportUnknownArgumentType]

  def __iter__(self):
    return iter(self._range)

  def __len__(self) -> int:
    return len(self._range)

  def __getitem__(self, index: int) -> int:
    return self._range[index]

  @override
  def __repr__(self) -> str:
    return repr(self._range)


class MockDict(dict):  # pyright: ignore[reportMissingTypeArgument]
  """
  A dictionary that forces linear scans for lookups to capture symbolic constraints.
  Standard dict uses hash() which bypasses Concolic __eq__.
  """

  @override
  def __getitem__(self, key):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    # Scan all keys to allow ConcolicByte to register constraints against them
    for k in self:  # pyright: ignore[reportUnknownVariableType]
      if k == key:  # Triggers __eq__ -> records constraint
        # Return the value associated with the REAL key 'k'
        return super().__getitem__(k)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType, reportUnknownArgumentType]
    # If we finish the loop, we implicitly recorded "key != k1", "key != k2", ...
    raise KeyError(key)  # pyright: ignore[reportUnknownArgumentType]

  @override
  def __contains__(self, key):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    for k in self:  # pyright: ignore[reportUnknownVariableType]
      if k == key:
        return True
    return False

  @override
  def get(self, key, default=None):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    for k in self:  # pyright: ignore[reportUnknownVariableType]
      if k == key:
        return super().__getitem__(k)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType, reportUnknownVariableType]
    return default  # pyright: ignore[reportUnknownVariableType]


class MockStruct:
    """
    Mocks the 'struct' module to handle ConcolicSlice/List objects.
    Delegates to .as_int() for integer unpacking.
    """
    def __init__(self):
        self.error = struct.error
    
    def unpack(self, fmt, buffer):
        # 1. Handle Concolic objects
        if hasattr(buffer, 'as_int'):
            # Simple handling for common network types
            if fmt == '!H' or fmt == '>H': # Unsigned Short (2 bytes)
                return (buffer.as_int('big'), )
            elif fmt == '!I' or fmt == '>I': # Unsigned Int (4 bytes)
                return (buffer.as_int('big'), )
            elif fmt == '!B' or fmt == '>B': # Unsigned Byte (1 byte)
                return (buffer[0], )
            elif fmt == '!Q' or fmt == '>Q': # Unsigned Long Long (8 bytes)
                return (buffer.as_int('big'), )
            
            # If complex format, you might need to expand this logic
            # or convert buffer to concrete bytes (losing symbols) as fallback
            # but usually parsers just do simple int conversions.
            pass

        # 2. Fallback to real struct for standard bytes
        return struct.unpack(fmt, buffer)

    def pack(self, fmt, *args):
        return struct.pack(fmt, *args)
    
    def calcsize(self, fmt):
        return struct.calcsize(fmt)