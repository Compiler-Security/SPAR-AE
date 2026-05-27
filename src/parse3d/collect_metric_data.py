from __future__ import annotations
from operator import is_
from typing import TYPE_CHECKING, TypedDict, override
from src.parse3d.ast_visitor import AstVisitor

if TYPE_CHECKING:
  from src.parse3d.ast import (
    Module,
    Struct,
    StructNameType,
    StructType,
    CaseType,
    CaseBranch,
    FieldDecl,
    Constraint,
    Ast,
  )
  from src.parse3d.ctx import ParserContext


class MetricDictType(TypedDict):
  msg_type_count: int
  field_count: int
  independent_constraint_count: int
  dependent_constraint_count: int
  line_of_code: int


class CollectMetricData(AstVisitor):
  def __init__(self, loc: int):
    self.metrics: MetricDictType = {
      "msg_type_count": 0,
      "field_count": 0,
      "independent_constraint_count": 0,
      "dependent_constraint_count": 0,
      "line_of_code": loc,
    }
    self.loc: int = loc
    self.types_visited: set[str] = set()
    self.dependent_constraints: set[Constraint] = set()
    self.independent_constraints: set[Constraint] = set()

  def reset_metrics(self):
    self.metrics = {
      "msg_type_count": 0,
      "field_count": 0,
      "independent_constraint_count": 0,
      "dependent_constraint_count": 0,
      "line_of_code": self.loc,
    }
    self.types_visited = set()
    self.independent_constraints = set()
    self.dependent_constraints = set()

  def get_metrics(self, module: Module, ctx: ParserContext) -> MetricDictType:
    self.reset_metrics()
    self.visit(module, ctx)
    return self.metrics

  def visit_Module(self, node: Module, ctx: ParserContext):
    for case_or_struct in node.definitions.values():
      self.visit(case_or_struct, ctx)

  def is_anonymous_struct(self, struct_name: str) -> bool:
    return struct_name.startswith("<") and struct_name.endswith(">")

  def visit_Struct(self, node: Struct, ctx: ParserContext):
    if node.name not in self.types_visited:
      self.metrics["msg_type_count"] += 1
      self.types_visited.add(node.name)
    # handle parameter constraint
    if node.parameter_constraints:
      for constraint in node.parameter_constraints:
        if len(list(constraint.get_expr().get_vars())) > 1:
          if constraint not in self.dependent_constraints:
            self.dependent_constraints.add(constraint)
            self.metrics["dependent_constraint_count"] += 1
        else:
          if constraint not in self.independent_constraints:
            self.independent_constraints.add(constraint)
            self.metrics["independent_constraint_count"] += 1
    for field in node.fields:
      self.metrics["field_count"] += 1
      self.visit(field, ctx)

  def visit_CaseType(self, node: CaseType, ctx: ParserContext):
    if node.name not in self.types_visited:
      self.metrics["msg_type_count"] += 1
      self.types_visited.add(node.name)
    for case in node.cases.values():
      self.metrics["field_count"] += 1
      self.visit(case, ctx)

  def visit_CaseBranch(self, node: CaseBranch, ctx: ParserContext):
    self.visit(node.field, ctx)

  def visit_FieldDecl(self, node: FieldDecl, ctx: ParserContext):
    self.visit(node.typ, ctx)

    if node.constraint_is_dependent():
      if node.constraint and node.constraint not in self.dependent_constraints:
        self.dependent_constraints.add(node.constraint)
        self.metrics["dependent_constraint_count"] += 1
    else:
      if node.constraint and node.constraint not in self.independent_constraints:
        self.independent_constraints.add(node.constraint)
        self.metrics["independent_constraint_count"] += 1

  def visit_StructType(self, node: StructType, ctx: ParserContext):
    self.visit(node.struct, ctx)

  @override
  def generic_visit(self, node: Ast, context: "ParserContext") -> None:
    pass
