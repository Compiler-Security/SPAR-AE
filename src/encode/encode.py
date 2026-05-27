from __future__ import annotations
from typing import TYPE_CHECKING, final, override
import re

from z3.z3 import Int, IntVal, Solver  # pyright: ignore[reportUnknownVariableType]

from src.tool import todo
from src.log import StepLogger

if TYPE_CHECKING:
  from src.parse3d import Module
  from src.parse3d import ParserContext
  from src.parse3d import PathCondition
  from src.fsm.fsm import Path
  from z3 import BoolRef, ArithRef


class EncoderError(Exception):
  def __init__(self, *args, unsat_core=None) -> None:  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    super().__init__(*args)  # pyright: ignore[reportUnknownArgumentType]
    self.unsat_core = unsat_core  # pyright: ignore[reportUnknownMemberType, reportUnannotatedClassAttribute]


@final
class Encoder(StepLogger):
  """
  Encoder generate testcase for one path. It do one thing and must do it well. It does not mutate paths or path conditions.
  """

  def __init__(
    self,
    path: "Path",
    path_conditions: "dict[str, dict[str, PathCondition]]",
    context: "ParserContext",
    module: "Module",
    count: int = 1,
    target_mutate_var: str | None = None,
    mute: bool = False,
  ):
    super().__init__("Encoder_legacy", mute)
    self.path: "Path" = path
    self.path_condition: "dict[str, dict[str, PathCondition]]" = path_conditions
    self.context: "ParserContext" = context
    self.module: "Module" = module
    self.vars: "dict[str, ArithRef]" = {}
    self.vars_bit_size: "dict[str, int]" = {}
    self.fill_self_vars()
    self.list_of_var_value_map: "list[dict[str, int]]" = []
    self.var_to_special_handling: "dict[str, tuple[str, str, str]]" = {}
    self._list_of_case_table: list[dict[str, int]] | None = None
    self.encode_count: int = count
    self.target_mutate_var: str | None = target_mutate_var
    self.max_muate_attempt_for_one_variable: int = 20
    from z3 import Solver

    self.solver = Solver()

  @override
  def run(self) -> None:
    pass  # dummy implementation

  def fill_self_vars(self):
    from z3 import Int  # pyright: ignore[reportUnknownVariableType]
    from src.fsm.fsm import PathNodeKind

    # Collect bit size of all variables in the path
    for pn in self.path.nodes:
      match pn.kind:
        case PathNodeKind.NODE_W_CONDITION | PathNodeKind.NODE_WO_CONDITION:
          if pn.node is None:
            raise ValueError(
              "PathNodeKind.NODE_W_CONDITION and PathNodeKind.NODE_WO_CONDITION must have node"
            )
          if pn.node.type_expr is None:
            raise ValueError("Node must have type_expr")
          from src.parse3d import PrimitiveType, ArrayType, IntLiteral

          match pn.node.type_expr:
            case PrimitiveType() as pt:
              self.vars_bit_size[pn.node.name] = pt.bits
            case ArrayType() as at:
              match at.elem_type:
                case PrimitiveType() as elem_pt:
                  match at.size:
                    case IntLiteral() as il:
                      self.vars_bit_size[pn.node.name] = elem_pt.bits * int(
                        il.value.val
                      )
                    case _:
                      # dynamic size array, we cannot determine its bit size here
                      pass
                case _:
                  pass
            case _:
              continue
        case PathNodeKind.CONDITION | PathNodeKind.FSM_START | PathNodeKind.FSM_END:
          continue

    # Collect all variables in the path
    for pn in self.path.nodes:
      match pn.kind:
        case PathNodeKind.NODE_W_CONDITION:
          if pn.node is None:
            raise ValueError("PathNodeKind.NODE_W_CONDITION must have condition")
          self.vars[pn.node.name] = Int(pn.node.name)
          if pn.node.more_constrained_ast is None:  # pyright: ignore[reportUnnecessaryComparison]
            raise ValueError(
              "PathNodeKind.NODE_W_CONDITION must have node.condition_ast"
            )
          for name, var in pn.node.more_constrained_ast.get_vars().items():
            if name not in self.vars:
              self.vars[name] = var
        case PathNodeKind.NODE_WO_CONDITION:
          if pn.node is None:
            raise ValueError("PathNodeKind.NODE_WO_CONDITION must have node")
          self.vars[pn.node.name] = Int(pn.node.name)
        case PathNodeKind.CONDITION:
          if pn.condition_str is None or pn.condition_str == "True":
            continue
          if pn.condition_ast is None:
            raise ValueError("PathNodeKind.CONDITION must have condition_ast")
          for name, var in pn.condition_ast.get_vars().items():
            if name not in self.vars:
              self.vars[name] = var
        case PathNodeKind.FSM_START | PathNodeKind.FSM_END:
          continue

  def get_case_table(self) -> "list[dict[str, int]]":
    if self._list_of_case_table is not None:
      return self._list_of_case_table
    else:
      raise ValueError("case table is not generated yet")

  def constraint_collection(self) -> "list[BoolRef]":
    from src.fsm.fsm import PathNodeKind

    if (
      self.path.nodes[0].kind != PathNodeKind.FSM_START
      or self.path.nodes[0].fsm is None
    ):
      raise ValueError("Path must start with FSM_START")
    constraints: "list[BoolRef]" = []
    fsm_name_stack: "list[str]" = []
    with self.step("Constraint Collection"):
      for pn in self.path.nodes:
        match pn.kind:
          case PathNodeKind.NODE_W_CONDITION:
            if pn.node is None:
              raise ValueError("PathNodeKind.NODE_W_CONDITION must have condition")
            if pn.node.condition_ast is None:
              raise ValueError(
                "PathNodeKind.NODE_W_CONDITION must have node.condition_ast"
              )
            try:
              constraints.append(pn.node.more_constrained_ast.to_bool_z3())
            except Exception as e:
              self.log_error(f"Error converting to BoolRef: {e}")
              pass
            special_handling = list(
              filter(lambda x: "@" in x, pn.node.more_constrained_ast.get_vars().keys())
            )
            if special_handling:
              from z3 import IntVal  # pyright: ignore[reportUnknownVariableType]

              for var_name in special_handling:
                match = re.match(r"@(\w+)\((\w+)\)\[(\w+)\]", var_name)
                if match:
                  function, target, id_str = match.groups()
                  # Assuming the logic for special handling will be added later.
                  # For now, just storing the target seems appropriate given the context.
                  self.var_to_special_handling[target] = (function, target, id_str)
                  match function:
                    case "len":
                      ...
                    case "sizeof":
                      if target == "this":
                        if not fsm_name_stack:
                          raise ValueError("No FSM in stack for sizeof(this)")
                        target = self.path.nodes[0].fsm.name
                      size_str = self.path.bit_size_map.get(target)
                      if size_str is None:
                        raise ValueError(
                          f"Size of {target} not found in path.bit_size_map, which is {self.path.bit_size_map}"
                        )
                      from src.parse3d import Parse3D

                      size_expr = Parse3D(size_str).handle_arith_expr()
                      constraints.append(
                        self.vars[var_name] == (size_expr.to_arith_z3() / IntVal(8))  # pyright: ignore[reportUnknownArgumentType]
                      )
                      # self.log_info(
                      #   f"Added special handling constraint for sizeof: {self.vars[var_name]} == ({size_expr.to_arith_z3()} / 8)"
                      # )
                    case _:
                      todo(f"Function {function} in special handling")

          case PathNodeKind.NODE_WO_CONDITION:
            continue
          case PathNodeKind.CONDITION:
            if pn.condition_str is None or pn.condition_str == "True":
              continue
            if pn.condition_ast is None:
              raise ValueError("PathNodeKind.CONDITION must have condition_ast")
            constraints.append(pn.condition_ast.to_bool_z3())
            # do special handling for variables like @len(var)[id] or @sizeof(var)[id]
            special_handling = list(
              filter(lambda x: "@" in x, pn.condition_ast.get_vars().keys())
            )
            if special_handling:
              from z3 import IntVal  # pyright: ignore[reportUnknownVariableType]

              for var_name in special_handling:
                match = re.match(r"@(\w+)\((\w+)\)\[(\w+)\]", var_name)
                if match:
                  function, target, id_str = match.groups()
                  # Assuming the logic for special handling will be added later.
                  # For now, just storing the target seems appropriate given the context.
                  self.var_to_special_handling[target] = (function, target, id_str)
                  match function:
                    case "len":
                      ...
                    case "sizeof":
                      if target == "this":
                        if not fsm_name_stack:
                          raise ValueError("No FSM in stack for sizeof(this)")
                        target = self.path.nodes[0].fsm.name
                      size_str = self.path.bit_size_map.get(target)
                      if size_str is None:
                        raise ValueError(
                          f"Size of {target} not found in path.bit_size_map, which is {self.path.bit_size_map}"
                        )
                      from src.parse3d import Parse3D

                      size_expr = Parse3D(size_str).handle_arith_expr()
                      constraints.append(
                        self.vars[var_name] == (size_expr.to_arith_z3() / IntVal(8))  # pyright: ignore[reportUnknownArgumentType]
                      )
                      # self.log_info(
                      #   f"Added special handling constraint for sizeof: {self.vars[var_name]} == ({size_expr.to_arith_z3()} / 8)"
                      # )
                    case _:
                      todo(f"Function {function} in special handling")
          case PathNodeKind.FSM_START:
            if pn.fsm is None:
              raise ValueError("PathNodeKind.FSM_START must have fsm")
            fsm_name_stack.append(pn.fsm.name)
          case PathNodeKind.FSM_END:
            if pn.fsm is None:
              raise ValueError("PathNodeKind.FSM_END must have fsm")
            if not fsm_name_stack or fsm_name_stack[-1] != pn.fsm.name:
              raise ValueError("FSM_END does not match FSM_START")
            _ = fsm_name_stack.pop()
    # make constraints unique
    unique_constraints: "set[str]" = set()
    filtered_constraints: "list[BoolRef]" = []
    for c in constraints:
      c_str = c.__str__()
      if c_str not in unique_constraints:
        unique_constraints.add(c_str)
        filtered_constraints.append(c)
    constraints = filtered_constraints
    return constraints

  def enforce_constraints(
    self,
    constraints: list[BoolRef],
    blocking_clauses: list[BoolRef],
    solver: "Solver | None" = None,
  ) -> None:
    s = solver if solver is not None else self.solver
    s.reset()  # pyright: ignore[reportUnknownMemberType]
    for c in constraints:
      s.assert_and_track(c, c.__str__())  # pyright: ignore[reportUnknownMemberType]
    for blc in blocking_clauses:
      s.assert_and_track(blc, blc.__str__())  # pyright: ignore[reportUnknownMemberType]
    # if blocking_clauses and solver is None:
    #   self.log_info(f"Adding blocking clause: {blocking_clauses[-1].__str__()}")

  def solve_one(
    self, constraints: list[BoolRef], blocking_clauses: list[BoolRef]
  ) -> dict[str, int] | None:
    var_value_map: "dict[str, int]" = {}
    from z3 import sat  # pyright: ignore[reportAny]

    self.enforce_constraints(constraints, blocking_clauses)
    if self.solver.check() == sat:  # pyright: ignore[reportUnknownMemberType]
      model = self.solver.model()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
      for var_name, var in self.vars.items():
        if model.eval(var, model_completion=True) is not None:  # pyright: ignore[reportUnknownMemberType]
          var_value_map[var_name] = model.eval(  # pyright: ignore[reportUnknownMemberType]
            var, model_completion=True
          ).as_long()
        else:
          var_value_map[var_name] = 0
    else:
      return None
    return var_value_map

  def encode_one(self, var_value_map: dict[str, int]) -> bytes:
    from src.fsm.fsm import PathNodeKind

    # Encode to bytes
    byte_array = bytearray()
    current_bit_size = 0
    current_value = 0
    for pn in self.path.nodes:
      match pn.kind:
        case PathNodeKind.NODE_W_CONDITION | PathNodeKind.NODE_WO_CONDITION:
          if pn.node is None:
            raise ValueError(
              "PathNodeKind.NODE_W_CONDITION and PathNodeKind.NODE_WO_CONDITION must have node"
            )
          if pn.node.name not in var_value_map:
            raise ValueError(f"Variable {pn.node.name} not found in var_value_map")
          if pn.node.name not in self.vars_bit_size:
            # means pn.node is an array type
            special_handling = self.var_to_special_handling.get(pn.node.name, None)
            if special_handling is None:
              self.log_error(f"vars_bit_size: {self.vars_bit_size}")
              self.log_error(f"var_to_special_handling: {self.var_to_special_handling}")
              raise ValueError(
                f"Variable {pn.node.name} is not in vars_bit_size and no special handling found"
              )
            function, target, id_str = special_handling
            if target is None or id_str is None or function is None:  # pyright: ignore[reportUnnecessaryComparison]
              raise ValueError(
                f"Variable {pn.node.name} requires special handling but not found in var_to_special_handling, got {self.var_to_special_handling}"
              )
            match function:
              case "len":
                template_name = f"@{function}({target})[{id_str}]"
                if template_name not in var_value_map:
                  raise ValueError(
                    f"Variable {template_name} not found in var_value_map"
                  )
                length = var_value_map[template_name]
                if target != pn.node.name:
                  raise ValueError(
                    f"Variable {pn.node.name} special handling target {target} does not match"
                  )
                if length == 0:
                  # array length is zero, encode nothing
                  continue
                if length < 0:
                  raise EncoderError(
                    f"Array length {length} of variable {pn.node.name} is negative"
                  )
                # now we can handle the array as a very large UInt, write its value into byte array with big endian
                byte_to_write = bytes()
                for _ in range(length):
                  byte_to_write += (0).to_bytes(1, byteorder="big")
                byte_array.extend(byte_to_write)
              case "sizeof":
                ...
              case _:
                todo(f"Function {function} in special handling")
          else:
            bit_size = self.vars_bit_size[pn.node.name]
            value = var_value_map[pn.node.name]
            max_value = (1 << bit_size) - 1
            if value < 0 or value > max_value:
              raise EncoderError(
                f"Value {value} of variable {pn.node.name} exceeds its bit size {bit_size}"
              )
            current_bit_size += bit_size
            current_value = (current_value << bit_size) | value
            if current_bit_size >= 8:
              # find the max length of bytes to write
              write_length = (current_bit_size // 8) * 8
              byte_array.extend(
                (current_value >> (current_bit_size - write_length)).to_bytes(
                  write_length // 8, byteorder="big"
                )
              )
              current_bit_size -= write_length
              current_value = current_value & ((1 << current_bit_size) - 1)
        case PathNodeKind.CONDITION | PathNodeKind.FSM_START | PathNodeKind.FSM_END:
          continue
    return bytes(byte_array)

  @staticmethod
  def should_be_mutated(var_name: str, target_mutate_var: str | None) -> bool:
    if "@" in var_name:
      return False
    if "this" == var_name:
      return False
    if target_mutate_var is not None:
      return var_name == target_mutate_var
    return True

  def encode(self) -> "list[bytes]":
    from z3 import sat  # pyright: ignore[reportAny]

    with self.step("Encoding"):
      constraints = self.constraint_collection()
      self.log_info(f"Total {len(constraints)} constraints collected for encoding.")
      # self.log_info("Constraints:")
      # for c in constraints:
      #   self.log_info(f"  {simplify(c)}")
      self.enforce_constraints(constraints, blocking_clauses=[])

      generated = 0
      encoded_packets: "list[bytes]" = []
      blocked_clauses: "list[BoolRef]" = []
      same_varieble_negate_count: dict[str, int] = {}
      with self.step("Packet Generation"):
        while generated < self.encode_count:
          var_value_map = self.solve_one(constraints, blocked_clauses)
          if var_value_map is None and generated == 0:
            raise EncoderError(
              "No satisfiable model found",
              unsat_core=self.solver.unsat_core(),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            )
          if var_value_map is None:  # encoding failed
            break
          generated += 1
          if generated == 1:
            # we want to fix all sizeof and len special handling variables to avoid breaking length constraints
            self.log_info(
              "First encoding generated, fixing special handling variables for subsequent encodings."
            )
            for target_var in self.var_to_special_handling.keys():
              self.log_info(f"Fixing special handling for variable: {target_var}")
              if target_var in var_value_map:
                template_name_len = f"@len({target_var})[placeholder]"
                template_name_sizeof = f"@sizeof({target_var})[placeholder]"
                if template_name_len in var_value_map:
                  constraints.append(
                    Int(template_name_len) == IntVal(var_value_map[template_name_len])  # pyright: ignore[reportUnknownArgumentType]
                  )
                  self.log_info(
                    f"Adding constraint: {template_name_len} == {var_value_map[template_name_len]}"
                  )
                if template_name_sizeof in var_value_map:
                  constraints.append(
                    Int(template_name_sizeof)
                    == IntVal(var_value_map[template_name_sizeof])  # pyright: ignore[reportUnknownArgumentType]
                  )
                  self.log_info(
                    f"Adding constraint: {template_name_sizeof} == {var_value_map[template_name_sizeof]}"
                  )
          self.list_of_var_value_map.append(var_value_map)
          # try to mutate one variable
          mutated = False
          for var_name, var in self.vars.items():
            if (
              not mutated
              and same_varieble_negate_count.get(var_name, 0)
              < self.max_muate_attempt_for_one_variable
              and self.should_be_mutated(var_name, self.target_mutate_var)
            ):
              from z3 import Solver

              current_var = var_value_map[var_name]
              if current_var < 0:
                self.log_info(
                  f"Variable {var_name} has negative value {current_var}, skipping mutation."
                )
                continue
              new_blockclause = var != IntVal(var_value_map[var_name])  # pyright: ignore[reportUnknownVariableType]
              another_solver = Solver()
              self.enforce_constraints(
                constraints, blocked_clauses + [new_blockclause], another_solver
              )
              if another_solver.check() == sat:  # pyright: ignore[reportUnknownMemberType]
                same_varieble_negate_count[var_name] = (
                  same_varieble_negate_count.get(var_name, 0) + 1
                )
                blocked_clauses.append(new_blockclause)  # pyright: ignore[reportUnknownArgumentType]
                self.enforce_constraints(constraints, blocked_clauses)
                mutated = True
                if (
                  same_varieble_negate_count[var_name]
                  >= self.max_muate_attempt_for_one_variable
                ):
                  self.log_info(
                    f"Variable {var_name} has been negated more than {self.max_muate_attempt_for_one_variable} times, stopping further negation."
                  )
                  blocked_clauses.clear()
              else:
                self.log_info(
                  f"Cannot mutate variable {var_name} further, as negating it leads to unsat."
                )
                same_varieble_negate_count[var_name] = (
                  self.max_muate_attempt_for_one_variable
                )
          if not mutated:
            self.log_info(
              "No variable was mutated in this iteration, stopping generation."
            )
            self.log_info("Target mutate var: " + str(self.target_mutate_var))
            break
          encoded_packets.append(self.encode_one(var_value_map))
      if self._list_of_case_table is None:
        self._list_of_case_table = []
        for vmap in self.list_of_var_value_map:
          self._list_of_case_table.append(vmap)
      return encoded_packets
