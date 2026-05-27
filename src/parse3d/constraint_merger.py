from __future__ import annotations
from functools import reduce
from typing import TYPE_CHECKING
from src.parse3d.ast_visitor import AstVisitor
from copy import deepcopy

if TYPE_CHECKING:
  from src.parse3d.ast import Module, Struct, CaseType, Constraint
  from src.parse3d.ctx import ParserContext


class MergeConstraints(AstVisitor):
  def __init__(self) -> None:
    self.ast_copy: Module | None = None

  def merge(self, ast: Module, context: "ParserContext") -> Module:
    self.ast_copy = deepcopy(ast)
    self.visit(self.ast_copy, context)
    return self.ast_copy

  def visit_Module(self, node: Module, context: "ParserContext") -> None:
    for _name, struct in node.definitions.items():
      self.visit(struct, context)

  def visit_Struct(self, node: Struct, _context: "ParserContext") -> None:
    constraints: list[Constraint] = []
    for field in node.fields:
      if field.constraint:
        _ = constraints.append(deepcopy(field.constraint))
        field.constraint = None
    from src.parse3d.ast import EmptyType, FieldDecl
    from src.parse3d.tok import Tok3D, Tok3DType
    from src.parse3d.ast import LogicalExpr

    last_field_location = node.fields[-1].line_col() if node.fields else node.line_col()
    if constraints:
      merged_constraint = reduce(
        lambda c1, c2: LogicalExpr(
          Tok3D(Tok3DType.LOGOP, "&&", c2.line, c2.col), c1, c2
        ),
        map(lambda c: c.expr, constraints),
      )
      node.fields.append(
        FieldDecl(
          name="__merged_constraint_field__",
          typ=EmptyType(last_field_location[0], last_field_location[1]),
          constraint=Constraint(merged_constraint),
          belongs_to=node,
        )
      )

  def visit_CaseType(self, _node: CaseType, _context: "ParserContext") -> None:
    pass
