from __future__ import annotations
from typing import TYPE_CHECKING
from src.parse3d.ast_visitor import AstVisitor

if TYPE_CHECKING:
  from src.parse3d.ast import Struct, CaseType, ArrayType, Module, StructNameType
  from src.parse3d.ctx import ParserContext


class Resolver(AstVisitor):
  @staticmethod
  def resolve_struct(
    struct_name_type: "StructNameType", context: "ParserContext"
  ) -> None:
    if struct_name_type.name not in (
      list(context.defined_structs.keys()) + list(context.defined_casetypes.keys())
    ):
      raise ValueError(f"Undefined struct {struct_name_type.name}")
    struct_name_type.add_struct(
      context.defined_structs.get(struct_name_type.name)
      or context.defined_casetypes[struct_name_type.name]
    )

  def visit_Module(self, node: "Module", context: "ParserContext") -> None:
    from src.parse3d.ast import Struct, CaseType

    for definition in node.definitions.values():
      match definition:
        case Struct() as struct:
          self.visit_Struct(struct, context)
        case CaseType() as casetype:
          self.visit_CaseType(casetype, context)

  def visit_Struct(self, struct: "Struct", context: "ParserContext") -> None:
    from src.parse3d.ast import StructNameType, StructType, ArrayType

    for field in struct.fields:
      match field.typ:
        case StructNameType() as snt:
          self.resolve_struct(snt, context)
        case StructType() as st:
          self.visit_Struct(st.struct, context)
        case ArrayType() as at:
          self.visit_ArrayType(at, context)
        case _:
          continue

  def visit_ArrayType(self, array_type: "ArrayType", context: "ParserContext") -> None:
    from src.parse3d.ast import StructNameType, ArrayType, StructType

    match array_type.elem_type:
      case StructNameType() as snt:
        self.resolve_struct(snt, context)
      case ArrayType() as at:
        self.visit_ArrayType(at, context)
      case StructType() as st:
        self.visit_Struct(st.struct, context)
      case _:
        return

  def visit_CaseType(self, casetype: "CaseType", context: "ParserContext") -> None:
    from src.parse3d.ast import StructNameType, StructType, ArrayType

    for field in casetype.case_variables:
      match field.typ:
        case StructNameType() as snt:
          self.resolve_struct(snt, context)
        case StructType() as st:
          self.visit_Struct(st.struct, context)
        case ArrayType() as at:
          self.visit_ArrayType(at, context)
        case _:
          continue
    for case in casetype.cases.values():
      match case.field.typ:
        case StructNameType() as snt:
          self.resolve_struct(snt, context)
        case StructType() as st:
          self.visit_Struct(st.struct, context)
        case ArrayType() as at:
          self.visit_ArrayType(at, context)
        case _:
          continue
