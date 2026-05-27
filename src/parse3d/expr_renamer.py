from __future__ import annotations
from typing import TYPE_CHECKING
from src.parse3d.ast_visitor import AstVisitor

if TYPE_CHECKING:
  from src.parse3d.ast import (
    Expr,
    LogicalExpr,
    CmpExpr,
    ArithExpr,
    Constraint,
    ParenExpr,
    Ident,
    IntLiteral,
    FunctionCall,
  )
  from src.parse3d.ctx import ParserContext


class ExprRenamer(AstVisitor):
  def __init__(self, prefix: str) -> None:
    self.prefix: str = prefix

  def rename(self, expr: Expr, context: "ParserContext") -> Expr:
    self.visit(expr, context)
    return expr

  def visit_Ident(self, node: Ident, _context: "ParserContext") -> None:
    if "@" in node.name.val or node.name.val == "this":
      return
    node.name.val = f"{self.prefix}{node.name.val}"

  def visit_ParenExpr(self, node: ParenExpr, context: "ParserContext") -> None:
    self.visit(node.expr, context)

  def visit_FunctionCall(self, node: FunctionCall, context: "ParserContext") -> None:
    for arg in node.args:
      self.visit(arg, context)

  def visit_LogicalExpr(self, node: LogicalExpr, context: "ParserContext") -> None:
    self.visit(node.left, context)
    self.visit(node.right, context)

  def visit_CmpExpr(self, node: CmpExpr, context: "ParserContext") -> None:
    self.visit(node.left, context)
    self.visit(node.right, context)

  def visit_ArithExpr(self, node: ArithExpr, context: "ParserContext") -> None:
    self.visit(node.left, context)
    self.visit(node.right, context)

  def visit_Constraint(self, node: Constraint, context: "ParserContext") -> None:
    self.visit(node.expr, context)

  def visit_IntLiteral(self, _node: "IntLiteral", _context: "ParserContext") -> None:
    pass
