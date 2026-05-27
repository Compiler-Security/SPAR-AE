from __future__ import annotations
from collections.abc import Generator
from copy import deepcopy
from typing import TYPE_CHECKING, final, override

from src.log import StepLogger

if TYPE_CHECKING:
  from src.parse3d.ast import (
    Module,
  )
  from src.parse3d.ctx import ParserContext
  from src.fsm import Path
  from src.parse3d.collect_path_condition import PathCondition


@final
class PathMutator(StepLogger):
  def __init__(
    self,
    path: "Path",
    module: "Module",
    ctx: "ParserContext",
    path_condition: "dict[str, dict[str, PathCondition]]",
    mute: bool = False,
    exhaustive: bool = False,
  ):
    super().__init__("PathMutator", mute=mute)
    self.path = path
    self.module = module
    self.ctx = ctx
    self.path_condition = path_condition
    self.exhaustive = exhaustive
    self._original_path_condition: dict[PathCondition, PathCondition] | None = None

  @override
  def run(self):
    pass

  @property
  def original_path_condition(self) -> dict[PathCondition, PathCondition]:
    if self._original_path_condition is not None:
      return self._original_path_condition
    raise ValueError("original_path_condition is not generated yet")

  @staticmethod
  def get_name_wo_prefix(full_name: str, fsm_stack: list[str]) -> str:
    existing_prefix = "_".join(fsm_stack) + ("_" if len(fsm_stack) > 0 else "")
    if not full_name.startswith(existing_prefix):
      raise ValueError("FSM nesting error: FSM started does not match existing prefix")
    name_without_prefix = full_name[len(existing_prefix) :]
    return name_without_prefix

  def mutate(self) -> "Generator[tuple[PathCondition, list[Path]], None, None]":
    with self.step("Path Mutation"):
      from src.fsm import PathNode, PathNodeKind

      # mutated_paths: "Generator[tuple[PathCondition, list[Path]], None, None]" = {}

      if len(self.path.nodes) == 0:
        raise ValueError("Path has no nodes")
      if self.path.nodes[0].fsm is None:
        raise ValueError("Path's first node has no associated FSM")

      fsm_stack: "list[str]" = []
      current_pc = {}
      fsm_skip = False
      for nid, pn in enumerate(self.path.nodes):
        match pn.kind:
          case PathNodeKind.FSM_START:
            if pn.fsm is None:
              raise ValueError("FSM_START node has no associated FSM")
            name_without_prefix = pn.fsm.name
            fsm_stack.append(name_without_prefix)
            fsm_skip = name_without_prefix not in self.path_condition
            if name_without_prefix in self.path_condition:
              current_pc = self.path_condition[name_without_prefix]
            else:
              current_pc = {}
          case PathNodeKind.FSM_END:
            if len(fsm_stack) == 0:
              raise ValueError("FSM_END node encountered with empty FSM stack")
            _ = fsm_stack.pop()
            fsm_skip = (
              fsm_stack[-1] not in self.path_condition if len(fsm_stack) > 0 else False
            )
            if not fsm_skip:
              current_pc = (
                self.path_condition[fsm_stack[-1]] if len(fsm_stack) > 0 else {}
              )
            else:
              current_pc = {}
          case PathNodeKind.NODE_W_CONDITION:
            if fsm_skip:
              continue
            if len(fsm_stack) == 0:
              raise ValueError("NODE_W_CONDITION node encountered with empty FSM stack")
            if pn.node is None:
              raise ValueError("NODE_W_CONDITION node has no associated node")
            name_without_prefix = pn.node.name
            if name_without_prefix not in current_pc:
              continue  # no path condition for this node
            pc: "PathCondition" = current_pc[name_without_prefix]
            # Determine which constraint indices to mutate
            n_constraints = len(pc.constraints)
            if self.exhaustive:
              # All non-empty combinations of constraint indices
              from itertools import combinations
              idx_combinations: list[tuple[int, ...]] = []
              for r in range(1, n_constraints + 1):
                idx_combinations.extend(combinations(range(n_constraints), r))
            else:
              # Mutate one constraint at a time (Optimization II)
              idx_combinations = [(i,) for i in range(n_constraints)]

            for idx_combo in idx_combinations:
              # Negate constraints at idx_combo, keep others as-is
              mutated_constraint_lists: list[list[str]] = [[]]
              for j in range(n_constraints):
                if j in idx_combo:
                  negated = pc.constraints[j].negate()
                  new_lists: list[list[str]] = []
                  for existing in mutated_constraint_lists:
                    for neg in negated:
                      new_lists.append(existing + [str(neg)])
                  mutated_constraint_lists = new_lists
                else:
                  for existing in mutated_constraint_lists:
                    existing.append(str(pc.constraints[j]))
              mutated_constraint_exprs = [
                " and ".join(lst) for lst in mutated_constraint_lists
              ]
              from src.parse3d.parse import Parse3D
              from src.fsm import Node
              from src.parse3d.ast import LogicalExpr, CmpExpr, ParenExpr

              for mutated_constraint_expr in mutated_constraint_exprs:
                parser = Parse3D(mutated_constraint_expr)
                mutated_constraint_ast = parser.handle_logical_expr()
                mutated_constraint_expr = str(mutated_constraint_ast)
                if not isinstance(
                  mutated_constraint_ast, (LogicalExpr, CmpExpr, ParenExpr)
                ):
                  raise ValueError("Mutated constraint is not a LogicalExpr")
                new_path = self.path.copy()
                new_current_node = Node(
                  name=pn.node.name,
                  parser_context=pn.node.parser_context,
                  kind=pn.node.kind,
                  type_expr=pn.node.type_expr,
                  _condition_ast=mutated_constraint_ast,
                )
                new_path.nodes[nid] = PathNode(
                  kind=pn.kind,
                  fsm=pn.fsm,
                  node=new_current_node,
                )
                yield pc, [new_path]
          case PathNodeKind.CONDITION:
            pass
          case PathNodeKind.NODE_WO_CONDITION:
            ...  # do nothing
      # self.log_info(
      #   f"Generated {sum(len(v) for v in mutated_paths.values())} mutated paths"
      # )
      # return mutated_paths
