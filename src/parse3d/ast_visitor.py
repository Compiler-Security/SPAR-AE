from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from src.parse3d.ast import Ast
  from src.parse3d.ctx import ParserContext


class AstVisitor:
  def visit(self, node: "Ast", context: "ParserContext") -> None:
    method_name = "visit_" + type(node).__name__
    visitor = getattr(self, method_name, self.generic_visit)
    return visitor(node, context)

  def generic_visit(self, node: "Ast", context: "ParserContext") -> None:  # pyright: ignore[reportUnusedParameter]
    raise Exception(f"No visit_{type(node).__name__} method")
