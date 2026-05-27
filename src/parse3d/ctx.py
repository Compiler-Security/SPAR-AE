from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from src.parse3d.ast import Struct, CaseType


@dataclass
class ParserContext:
  def __init__(self):
    self.defined_structs: "dict[str, Struct]" = {}
    self.defined_casetypes: "dict[str, CaseType]" = {}
    self.entrypoint: "str | None" = None
    self.true_entrypoint: "str | None" = None # before typedef resolution
    self.reproduce_order: list[str] = []
    self.typedefs: dict[str, str] = {}  # typedef name -> actual type name
