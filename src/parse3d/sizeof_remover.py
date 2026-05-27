from __future__ import annotations
from functools import reduce
from typing import TYPE_CHECKING
from src.parse3d import Constraint, Tok3D
from src.parse3d.ast_visitor import AstVisitor
from src.parse3d.tok import Tok3DType
from src.tool import todo

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
    CmpExpr,
    LogicalExpr,
  )
  from src.parse3d import ParserContext


class RemoveSizeof(AstVisitor):
  @staticmethod
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
        left_result = RemoveSizeof.split_and_constraint_into_parts(left)
      elif isinstance(left, CmpExpr):
        left_result = [deepcopy(left)]
      elif isinstance(left, ParenExpr):
        if not isinstance(left.inner, (LogicalExpr, CmpExpr, ParenExpr)):
          raise ValueError(
            f"Expected LogicalExpr or CmpExpr inside ParenExpr, got {type(left.inner)}"
          )
        left_result = RemoveSizeof.split_and_constraint_into_parts(left.inner)
      else:
        raise ValueError("Expected LogicalExpr or CmpExpr")
      right_result: list[CmpExpr | LogicalExpr] = []
      if isinstance(right, LogicalExpr):
        right_result = RemoveSizeof.split_and_constraint_into_parts(right)
      elif isinstance(right, CmpExpr):
        right_result = [deepcopy(right)]
      elif isinstance(right, ParenExpr):
        if not isinstance(right.inner, (LogicalExpr, CmpExpr, ParenExpr)):
          raise ValueError(
            f"Expected LogicalExpr or CmpExpr inside ParenExpr, got {type(right.inner)}"
          )
        right_result = RemoveSizeof.split_and_constraint_into_parts(right.inner)
      else:
        raise ValueError(f"Expected LogicalExpr or CmpExpr, Got {type(right)}")
      return left_result + right_result
    return [expr]

  def __init__(self):
    super().__init__()

  def remove_sizeof(self, code: str) -> str:
    if code.strip() == "":
      return code
    from src.parse3d import Parse3D

    parser = Parse3D(code)
    module = parser.parse()
    ctx = parser.context
    self.visit(module, ctx)
    todo(
      "Implemen reproducer to print the modified 3d code after removing sizeof constraints"
    )

  def visit_Module(self, node: "Module", ctx: "ParserContext"):
    for name, struct_or_case in node.definitions.items():
      self.visit(struct_or_case, ctx)

  def delete_sizeof_in_constraint(
    self, constraint: "Constraint"
  ) -> "Constraint | None":
    splited_parameter_constraints: list[CmpExpr | LogicalExpr] = (
      self.split_and_constraint_into_parts(constraint.expr)
    )
    new_constraints: list[CmpExpr | LogicalExpr] = []
    for c in splited_parameter_constraints:
      is_sizeof = False
      for var in c.get_vars():
        if "sizeof" in var:
          is_sizeof = True
          break
      if not is_sizeof:
        new_constraints.append(c)
    # merge back to LogicalExpr
    if not new_constraints:
      return None
    else:
      new_constraint = reduce(
        lambda a, b: LogicalExpr(
          Tok3D(Tok3DType.LOGOP, "&&", constraint.expr.line, constraint.expr.col), a, b
        ),
        new_constraints,
      )
      return Constraint(new_constraint)

  def visit_Struct(self, node: "Struct", ctx: "ParserContext"):
    if len(node.get_args_constraints()) == 1:
      result = self.delete_sizeof_in_constraint(node.get_args_constraints()[0])
      if result is None:
        node.parameter_constraints = []
      else:
        node.parameter_constraints = [result]
    for field in node.fields:
      self.visit(field, ctx)

  def visit_CaseType(self, node: "CaseType", ctx: "ParserContext"):
    # 😅3d would not allow casetype to have parameter constraints, so do nothing
    for variables in node.case_variables:
      self.visit(variables, ctx)
    for case_branch in node.cases.values():
      self.visit(case_branch, ctx)

  def visit_FieldDecl(self, node: "FieldDecl", ctx: "ParserContext"):
    if node.has_constraint():
      result = self.delete_sizeof_in_constraint(node.constraint)  # pyright: ignore[reportArgumentType]
      if result is None:
        node.constraint = None
      else:
        node.constraint = result
