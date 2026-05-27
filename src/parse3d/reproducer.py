from __future__ import annotations
from typing import TYPE_CHECKING
from src.parse3d.ast_visitor import AstVisitor
from src.tool import todo

if TYPE_CHECKING:
  from src.parse3d.ast import ArithExpr
  from src.parse3d.ast import ArrayType
  from src.parse3d.ast import Ast
  from src.parse3d.ast import CaseBranch
  from src.parse3d.ast import CaseType
  from src.parse3d.ast import CmpExpr
  from src.parse3d.ast import Constraint
  from src.parse3d.ast import EmptyType
  from src.parse3d.ast import Entrypoint
  from src.parse3d.ast import Expr
  from src.parse3d.ast import FieldDecl
  from src.parse3d.ast import FunctionCall
  from src.parse3d.ast import Ident
  from src.parse3d.ast import IntLiteral
  from src.parse3d.ast import LogicalExpr
  from src.parse3d.ast import Module
  from src.parse3d.ast import Nop
  from src.parse3d.ast import ParenExpr
  from src.parse3d.ast import PrimitiveType
  from src.parse3d.ast import Struct
  from src.parse3d.ast import StructNameType
  from src.parse3d.ast import StructType
  from src.parse3d.ast import TypeExpr
  from src.parse3d.ctx import ParserContext


class ReproduceCode(AstVisitor):
  def __init__(self) -> None:
    self.code_lines: list[str] = []

  def reproduce(self, _module: Module, context: "ParserContext") -> str:
    reproduce_order = context.reproduce_order
    for name in reproduce_order:
      struct_or_case = context.defined_structs.get(
        name
      ) or context.defined_casetypes.get(name)
      if struct_or_case is None:
        raise ValueError(f"Definition {name} not found in context.")
      self.visit(struct_or_case, context)
    return "\n".join(self.code_lines)

  def visit_Struct(self, node: Struct, context: "ParserContext") -> str:
    lines: list[str] = []
    typedef_name = context.typedefs.get(node.name)
    definition_line = "typedef " if typedef_name else ""
    definition_line += f"struct {typedef_name}"
    if node.has_args():
      todo("Handle struct with arguments in reproducer.")

  def visit_Ident(self, node: Ident, context: "ParserContext") -> str:
    return node.name.val

  def visit_EmptyType(self, node: EmptyType, context: "ParserContext") -> str:
    return "unit"

  def visit_Nop(self, node: "Nop", context: "ParserContext") -> str:
    return ""

  def visit_IntLiteral(self, node: IntLiteral, context: "ParserContext") -> str:
    return str(node.value.val)

  def visit_ArithExpr(self, node: ArithExpr, context: "ParserContext") -> str:
    left = self.visit(node.left, context)
    right = self.visit(node.right, context)
    return f"{left} {node.op.val} {right}"

  def visit_ParenExpr(self, node: ParenExpr, context: "ParserContext") -> str:
    inner = self.visit(node.inner, context)
    return f"({inner})"

  def visit_LogicalExpr(self, node: LogicalExpr, context: "ParserContext") -> str:
    left = self.visit(node.left, context)
    right = self.visit(node.right, context)
    return f"{left} {node.op.val} {right}"

  def visit_CmpExpr(self, node: CmpExpr, context: "ParserContext") -> str:
    left = self.visit(node.left, context)
    right = self.visit(node.right, context)
    return f"{left} {node.op.val} {right}"

  def visit_Constraint(self, node: Constraint, context: "ParserContext") -> str:
    expr_str = self.visit(node.expr, context)
    return f"{expr_str}"

  def visit_PrimitiveType(self, node: "PrimitiveType", context: "ParserContext") -> str:
    return node.name
  
  def visit_StructType(self, node: StructType, context: "ParserContext") -> str:
    return self.visit_Struct(node.struct, context)
  
  def visit_StructNameType(self, node: StructNameType, context: "ParserContext") -> str:
    return node.name

  def visit_ArrayType(self, node: ArrayType, context: "ParserContext") -> str:
    ...

  def visit_CaseType(self, node: CaseType, context: "ParserContext") -> None:
    lines: list[str] = []
    lines.append(f"casetype {node.name}(")
    for case_variable in node.case_variables:
      ...
