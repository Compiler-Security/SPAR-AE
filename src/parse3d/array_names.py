from __future__ import annotations
from typing import TYPE_CHECKING
from src.parse3d.ast_visitor import AstVisitor

if TYPE_CHECKING:
  from src.parse3d.ast import CaseType, Module, Struct
  from src.parse3d.ctx import ParserContext


class ArrayNames(AstVisitor):
  def __init__(self) -> None:
    super().__init__()
    self.array_names: set[str] = set()

  def get_array_names(self, node: "Module", context: "ParserContext") -> set[str]:
    self.array_names.clear()
    self.visit(node, context)
    return self.array_names

  def visit_Module(self, node: "Module", context: "ParserContext") -> None:
    from src.parse3d.ast import Struct, CaseType

    for definition in node.definitions.values():
      match definition:
        case Struct() as struct:
          self.visit_Struct(struct, context)
        case CaseType() as casetype:
          self.visit_CaseType(casetype, context)

  def visit_Struct(self, struct: "Struct", context: "ParserContext") -> None:
    from src.parse3d.ast import StructType, ArrayType

    for field in struct.fields:
      match field.typ:
        case StructType() as st:
          self.visit_Struct(st.struct, context)
        case ArrayType():
          self.array_names.add(field.name)
        case _:
          continue

  def visit_CaseType(self, casetype: "CaseType", context: "ParserContext") -> None:
    from src.parse3d.ast import StructType, ArrayType

    for _case_name, case_branch in casetype.cases.items():
      match case_branch.field.typ:
        case StructType() as st:
          self.visit_Struct(st.struct, context)
        case ArrayType():
          self.array_names.add(case_branch.field.name)
        case _:
          continue
