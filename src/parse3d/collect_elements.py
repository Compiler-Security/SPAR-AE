from __future__ import annotations
from typing import TYPE_CHECKING

from src.parse3d.ast_visitor import AstVisitor

if TYPE_CHECKING:
  from src.parse3d.ast import (
    Module,
    Struct,
    FieldDecl,
    CaseType,
    CaseBranch,
    Entrypoint,
    PrimitiveType,
    ArrayType,
    StructNameType,
    StructType,
    EmptyType,
    Ident,
    ArithExpr,
    IntLiteral,
    ParenExpr,
  )
  from src.parse3d.ctx import ParserContext


class CollectElements3D(AstVisitor):
  def __init__(self):
    super().__init__()
    self.elements: dict[str, list[tuple[int, int]]] = {}  # name -> list of (line, col)

  def visit_Module(self, node: "Module", ctx: "ParserContext") -> None:
    for name, struct_or_case in node.definitions.items():
      self.elements.setdefault(name, []).append(struct_or_case.line_col())
      self.visit(struct_or_case, ctx)

  def visit_Struct(self, node: "Struct", ctx: "ParserContext") -> None:
    self.elements.setdefault(node.name, []).append(node.line_col())
    for field in node.fields:
      self.visit(field, ctx)

  def visit_CaseType(self, node: "CaseType", ctx: "ParserContext") -> None:
    self.elements.setdefault(node.name, []).append(node.line_col())
    self.elements.setdefault(node.switch_var.name.val, []).append(
      node.switch_var.line_col()
    )
    for variables in node.case_variables:
      self.visit(variables, ctx)
    for case_branch in node.cases.values():
      self.visit(case_branch, ctx)

  def visit_FieldDecl(self, node: "FieldDecl", ctx: "ParserContext") -> None:
    self.elements.setdefault(node.name, []).append(node.line_col())
    self.visit(node.typ, ctx)

  def visit_CaseBranch(self, node: "CaseBranch", ctx: "ParserContext") -> None:
    self.visit(node.field, ctx)

  def visit_Entrypoint(self, node: "Entrypoint", ctx: "ParserContext") -> None:
    self.elements.setdefault(node.struct.name, []).append(node.line_col())
    self.visit(node.struct, ctx)

  def visit_PrimitiveType(
    self, _node: "PrimitiveType", _ctx: "ParserContext"
  ) -> None: ...  # Primitive types do not add elements

  def visit_ArrayType(self, node: "ArrayType", ctx: "ParserContext") -> None:
    self.visit(node.elem_type, ctx)

  def visit_ArithExpr(self, node: "ArithExpr", ctx: "ParserContext") -> None:
    self.visit(node.left, ctx)
    self.visit(node.right, ctx)

  def visit_IntLiteral(
    self, _node: "IntLiteral", _ctx: "ParserContext"
  ) -> None: ...  # Int literals do not add elements

  def visit_StructNameType(self, node: "StructNameType", _ctx: "ParserContext") -> None:
    self.elements.setdefault(node.name, []).append(node.line_col())
    if node.args:
      for arg in node.args:
        self.visit(arg, _ctx)

  def visit_StructType(self, node: "StructType", ctx: "ParserContext") -> None:
    self.visit(node.struct, ctx)

  def visit_Ident(self, node: "Ident", _ctx: "ParserContext") -> None:
    self.elements.setdefault(node.name.val, []).append(node.line_col())

  def visit_EmptyType(
    self, _node: "EmptyType", _ctx: "ParserContext"
  ) -> None: ...  # Empty type does not add elements

  def get_elements_3d(self, code: str) -> dict[str, list[tuple[int, int]]]:
    if code.strip() == "":
      return dict()
    self.elements.clear()
    from src.parse3d.parse import Parse3D

    parser = Parse3D(code)
    module = parser.parse()
    ctx = parser.context
    self.visit(module, ctx)
    return self.elements

  def visit_ParenExpr(self, node: "ParenExpr", ctx: "ParserContext") -> None:
    self.visit(node.expr, ctx)
