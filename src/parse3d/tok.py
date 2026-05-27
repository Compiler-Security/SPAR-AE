from __future__ import annotations
from enum import Enum
from typing import Callable, final, override


class Tok3DType(Enum):
  KWD = 0
  IDENT = 1
  INT = 2
  ARITHOP = 3  # arithmetic operators: +, -, *, /, %
  LOGOP = 5  # logical operators: &&, ||
  CMPOP = 6  # comparison operators: ==, !=, <, <=, >, >=
  RBRACE = 7  # }
  LBRACE = 8  # {
  RPAREN = 9  # )
  LPAREN = 10  # (
  RBRACKET = 11  # ]
  LBRACKET = 12  # [
  SEMICOLON = 13  # ;
  COMMA = 14  # ,
  COLON = 15  # :
  BYTE_SIZE = 16  # byte-size

@final
class Tok3D:
  __slots__ = ("typ", "val", "line", "col")

  def __init__(self, typ: Tok3DType, val: str, line: int, col: int):
    if not isinstance(typ, Tok3DType):  # pyright: ignore[reportUnnecessaryIsInstance]
      raise TypeError(f"typ must be a Tok3DType, got {type(typ).__name__}")  # pyright: ignore[reportUnreachable]
    if not isinstance(val, str):  # pyright: ignore[reportUnnecessaryIsInstance]
      raise TypeError(f"val must be a str, got {type(val).__name__}")  # pyright: ignore[reportUnreachable]
    if not isinstance(line, int) or isinstance(line, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
      raise TypeError(f"line must be an int, got {type(line).__name__}")
    if not isinstance(col, int) or isinstance(col, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
      raise TypeError(f"col must be an int, got {type(col).__name__}")
    if line < 0:
      raise ValueError(f"line must be >= 0, got {line}")
    if col < 0:
      raise ValueError(f"col must be >= 0, got {col}")
    self.typ: Tok3DType = typ
    self.val: str = val
    self.line: int = line
    self.col: int = col

  @override
  def __repr__(self) -> str:
    return f"Tok3D({self.typ.name}, {self.val!r}, {self.line}, {self.col})"

  @override
  def __eq__(self, other: object) -> bool:
    if not isinstance(other, Tok3D):
      return False
    return self.typ == other.typ and self.val == other.val

  @override
  def __ne__(self, other: object) -> bool:
    if not isinstance(other, Tok3D):
      return True
    return self.typ != other.typ or self.val != other.val

  @override
  def __hash__(self) -> int:
    return hash((self.typ, self.val))


def _attach_is_methods(cls: type[Tok3D]) -> None:
  """Dynamically attaches `is_<type>` methods to the Tok3D class.
  This function iterates through all members of the `Tok3DType` enum. For each
  member (e.g., `KEYWORD`), it creates and attaches a corresponding method
  (e.g., `is_keyword`) to the provided class `cls`.
  Each generated method, when called on an instance of `cls`, returns `True` if
  the instance's `typ` attribute matches the enum member associated with that
  method, and `False` otherwise.
  For example, if `Tok3DType` has a member `IDENTIFIER`, this function will add
  a method `is_identifier` to `cls`. Calling `token.is_identifier()` will be
  equivalent to checking `token.typ == Tok3DType.IDENTIFIER`.
  This is a decorator-like function meant to be called once at class definition
  time, passing the class itself as the argument.
  Args:
    cls: The class (e.g., `Tok3D`) to which the methods will be attached.
  """

  for member in Tok3DType:
    # Create a closure to capture the member value
    def make_is_method(member_to_check: Tok3DType) -> Callable[[Tok3D], bool]:
      def is_method(self: Tok3D) -> bool:
        return self.typ == member_to_check

      return is_method

    method = make_is_method(member)
    setattr(cls, f"is_{member.name.lower()}", method)


_attach_is_methods(Tok3D)
