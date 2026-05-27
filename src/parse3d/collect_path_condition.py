from __future__ import annotations
from collections.abc import Sequence, Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING, override
from src.parse3d.ast_visitor import AstVisitor

if TYPE_CHECKING:
  from src.parse3d.ast import (
    FieldDecl,
    CmpExpr,
    Module,
    Struct,
    CaseType,
    CaseBranch,
    LogicalExpr,
    ParenExpr,
  )
  from src.parse3d.ctx import ParserContext


@dataclass
class PathCondition:
  variable: "FieldDecl"
  constraints: "Sequence[CmpExpr | LogicalExpr | ParenExpr]"

  @override
  def __hash__(self) -> int:
    return hash((self.variable.name, tuple(str(c) for c in self.constraints)))

  def __iter__(self) -> Generator[CmpExpr | LogicalExpr | ParenExpr, None]:
    yield from self.constraints

  @override
  def __repr__(self) -> str:
    constraints_str = " && ".join(str(c) for c in self.constraints)
    return constraints_str


class CollectPathCondition(AstVisitor):
  def __init__(self):
    super().__init__()
    self.path_conditions: "dict[str, dict[str, PathCondition]]" = {}  # struct name -> field name -> PathCondition

  def collect(
    self, node: "Module", context: "ParserContext"
  ) -> "dict[str, dict[str, PathCondition]]":
    self.path_conditions = {}
    self.visit(node, context=context)
    return self.path_conditions

  def visit_Module(self, node: "Module", context: "ParserContext") -> None:
    from src.parse3d.ast import Struct, CaseType

    for definition in node.definitions.values():
      match definition:
        case Struct() as struct:
          self.visit_Struct(struct, context)
        case CaseType() as casetype:
          self.visit_CaseType(casetype, context)

  def visit_Struct(self, struct: "Struct", context: "ParserContext") -> None:
    self.path_conditions[struct.name] = self.path_conditions.get(struct.name, {})
    for field in struct.fields:
      self.visit_FieldDecl(field, context)

  def visit_FieldDecl(self, field: "FieldDecl", context: "ParserContext") -> None:
    from src.parse3d.ast import StructType

    match field.typ:
      case StructType() as st:
        self.visit_Struct(st.struct, context)
      case _:
        if field.has_constraint():
          if field.belongs_to is None:
            raise ValueError(
              f"Field must belong to a struct, got {field}, belongs_to is None"
            )
          assert field.name not in self.path_conditions[field.belongs_to.name], (
            f"Field {field.name} already has path condition {self.path_conditions[field.belongs_to.name]}, new one: {field.constraint}"
          )

          def split_and_constraint_into_parts(
            expr: "LogicalExpr | CmpExpr | ParenExpr",
          ) -> "list[CmpExpr | LogicalExpr]":
            from src.parse3d.ast import LogicalExpr, CmpExpr, ParenExpr
            from copy import deepcopy

            if isinstance(expr, CmpExpr):
              return [expr]
            if not isinstance(expr, LogicalExpr):
              raise ValueError(f"Expected LogicalExpr, got {type(expr)}")
            if expr.op.val == "&&":
              left, right = expr.left, expr.right
              left_result: list[CmpExpr | LogicalExpr] = []
              if isinstance(left, LogicalExpr):
                left_result = split_and_constraint_into_parts(left)
              elif isinstance(left, CmpExpr):
                left_result = [deepcopy(left)]
              elif isinstance(left, ParenExpr):
                if not isinstance(left.inner, (LogicalExpr, CmpExpr, ParenExpr)):
                  raise ValueError(
                    f"Expected LogicalExpr or CmpExpr inside ParenExpr, got {type(left.inner)}"
                  )
                left_result = split_and_constraint_into_parts(left.inner)
              else:
                raise ValueError("Expected LogicalExpr or CmpExpr")
              right_result: list[CmpExpr | LogicalExpr] = []
              if isinstance(right, LogicalExpr):
                right_result = split_and_constraint_into_parts(right)
              elif isinstance(right, CmpExpr):
                right_result = [deepcopy(right)]
              elif isinstance(right, ParenExpr):
                if not isinstance(right.inner, (LogicalExpr, CmpExpr, ParenExpr)):
                  raise ValueError(
                    f"Expected LogicalExpr or CmpExpr inside ParenExpr, got {type(right.inner)}"
                  )
                right_result = split_and_constraint_into_parts(right.inner)
              else:
                raise ValueError(f"Expected LogicalExpr or CmpExpr, Got {type(right)}")
              return left_result + right_result
            return [expr]

          constraints = split_and_constraint_into_parts(field.constraint.expr)  # pyright: ignore[ reportOptionalMemberAccess]
          assert field.belongs_to is not None, (
            f"Field must belong to a struct, got {field}, belongs_to is {field.belongs_to}"
          )
          self.path_conditions[field.belongs_to.name][field.name] = PathCondition(
            variable=field, constraints=constraints
          )

  def visit_CaseType(self, casetype: "CaseType", context: "ParserContext") -> None:
    self.path_conditions[casetype.name] = self.path_conditions.get(casetype.name, {})
    for branch in casetype.cases.values():
      self.visit_CaseBranch(branch, context)

  def visit_CaseBranch(self, branch: "CaseBranch", context: "ParserContext") -> None:
    self.visit_FieldDecl(branch.field, context)
