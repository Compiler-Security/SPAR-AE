from __future__ import annotations
from copy import deepcopy
import time
from src.parse3d.ast import (
  ArithExpr,
  CmpExpr,
  FunctionCall,
  Ident,
  IntLiteral,
  LogicalExpr,
  ParenExpr,
)
from typing import TYPE_CHECKING, Generator, cast, final, override
from collections.abc import Sequence
from z3.z3 import BoolRef, Int, IntVal, Solver, substitute, unsat  # pyright: ignore[reportUnknownVariableType]
import re
from src.log import StepLogger
from src.tool import todo

if TYPE_CHECKING:
  from src.parse3d import (
    Module,
    ArithExpr,
    IntLiteral,
    Ident,
    LogicalExpr,
    CmpExpr,
    FunctionCall,
    ParenExpr,
    TypeExpr,
  )
  from src.parse3d import ParserContext
  from src.parse3d import PathCondition
  from src.fsm.fsm_new import Path
from z3 import ArithRef


class EncoderError(Exception):
  def __init__(self, *args, unsat_core=None) -> None:  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    super().__init__(*args)  # pyright: ignore[reportUnknownArgumentType]
    self.unsat_core = unsat_core  # pyright: ignore[reportUnknownMemberType, reportUnannotatedClassAttribute]


class EncoderStackFrame:
  def __init__(self, fsm_name: str):
    self.fsm_name: str = fsm_name
    self.vars: dict[str, EncoderContextVariable] = {}
    self.vars_bit_size: dict[str, int] = {}
    self.var_to_special_handling: dict[
      str, tuple[str, str, str]
    ] = {}  # var_name -> (function, target, id_str)
    self.arg_list: Sequence[
      ArithExpr
      | IntLiteral
      | Ident
      | LogicalExpr
      | CmpExpr
      | FunctionCall
      | ParenExpr
      | TypeExpr
    ] = []
    self.prev: EncoderStackFrame | None = None
    self.next: EncoderStackFrame | None = None
    self.fsm_size_expr: str | None = None
    self.fsm_size_cache: tuple[str, int] | None = None  # (expr_str, value)
    self.fsm_size_simplified: bool = False

  @property
  def canonical_prefix(self) -> str:
    if self.prev is not None:
      return f"{self.prev.canonical_prefix}_{self.normalized_fsm_name}"
    else:
      return self.normalized_fsm_name

  @property
  def normalized_fsm_name(self) -> str:
    from src.tool.str_functions import normalize_name

    return normalize_name(self.fsm_name)

  @override
  def __repr__(self) -> str:
    return f"EncoderStackFrame(fsm_name={self.fsm_name}, vars={self.vars}, vars_bit_size={self.vars_bit_size}, prev={self.prev.fsm_name if self.prev else None}, next={self.next.fsm_name if self.next else None})"


class EncoderContext:
  def __init__(self):
    self.global_frame: EncoderStackFrame = EncoderStackFrame("global")
    self.current_frame: EncoderStackFrame = self.global_frame

  def push_frame(self, fsm_name: str):
    new_frame = EncoderStackFrame(fsm_name)
    new_frame.prev = self.current_frame
    self.current_frame.next = new_frame
    self.current_frame = new_frame

  def pop_frame(self):
    if self.current_frame.prev is not None:
      self.current_frame = self.current_frame.prev
      self.current_frame.next = None
    else:
      raise EncoderError("Cannot pop global frame")


class EncoderContextVariable:
  def __init__(
    self,
    name: str,
    related_arg: ArithRef | None = None,
    in_frame: EncoderStackFrame | None = None,
  ):
    self.name: str = name
    self.related_arg: ArithRef | None = related_arg
    self.in_frame: EncoderStackFrame | None = in_frame
    self.var: ArithRef = Int(self.canonical_name)

  @property
  def canonical_name(self) -> str:
    if self.in_frame is not None:
      return f"{self.in_frame.canonical_prefix}_{self.normalized_name}"
    else:
      return self.normalized_name

  @property
  def normalized_name(self) -> str:
    from src.tool.str_functions import normalize_name

    return normalize_name(self.name)

  @override
  def __repr__(self) -> str:
    return f"EncoderContextVariable(name={self.name}, related_arg={self.related_arg}, var={self.var}, in_frame={self.in_frame.fsm_name if self.in_frame else None})"


@final
class Encoder(StepLogger):
  class IdxFrameMapping:
    def __init__(
      self,
      idx: int,
      prev_frame: Encoder.IdxFrameMapping | None,
      current_frame: EncoderStackFrame,
      next_frame: Encoder.IdxFrameMapping | None,
    ):
      self.idx: int = idx
      self.prev_frame: Encoder.IdxFrameMapping | None = prev_frame
      self.current_frame: EncoderStackFrame = current_frame
      self.next_frame: Encoder.IdxFrameMapping | None = next_frame

  def __init__(
    self,
    path: "Path",
    path_conditions: "dict[str, dict[str, PathCondition]]",
    context: "ParserContext",
    count: int = 40,
    target_mutate_var: str | None = None,
    mute: bool = False,
  ):
    super().__init__("Encoder", mute)
    self.mute = mute
    self.path: "Path" = path
    self.path_condition: "dict[str, dict[str, PathCondition]]" = path_conditions
    self.context: "ParserContext" = context
    self.encode_ctx = EncoderContext()
    self.encode_count: int = count
    self.target_mutate_var: str | None = target_mutate_var
    self.max_muate_attempt_for_one_variable: int = 20
    self.solver = Solver()
    self.frame_map: list[EncoderStackFrame] = []
    self.idx_frame_map: list[Encoder.IdxFrameMapping] = []
    self.vars: dict[str, EncoderContextVariable] = {}
    self.var_to_special_handling: dict[
      str, tuple[str, str, str]
    ] = {}  # var_name -> (function, target, id_str)
    self.list_of_var_value_map: list[dict[str, int]] = []
    self._list_of_case_table: list[dict[str, int]] = []
    self.encoded_cases: list[bytes] | None = None
    self.fill_self_vars()
    self.smt_time_cost: float = 0.0

  @override
  def run(self):
    pass

  @property
  def curr_vars_bit_size(self) -> dict[str, int]:
    return self.encode_ctx.current_frame.vars_bit_size

  @property
  def curr_vars(self) -> dict[str, EncoderContextVariable]:
    return self.encode_ctx.current_frame.vars

  @property
  def current_frame(self) -> EncoderStackFrame:
    return self.encode_ctx.current_frame

  def get_case_table(self) -> list[dict[str, int]]:
    return self._list_of_case_table

  def substitute_var(
    self,
    expr: "ArithExpr | IntLiteral | Ident | LogicalExpr | CmpExpr | FunctionCall | ParenExpr | TypeExpr",
    arg_var: ArithRef | BoolRef,
    idx: int,
  ) -> ArithRef | BoolRef:
    from src.parse3d import TypeExpr
    from src.tool.str_functions import normalize_name

    if isinstance(expr, TypeExpr):
      raise EncoderError("Cannot use TypeExpr as FSM argument")
    vars = expr.get_vars()
    substituted_args = list(
      map(lambda x: self.get_var(normalize_name(x), idx), vars.keys())
    )
    # Now, substitute variables in arg_var
    substitute_list = []
    for var_arg, sub_var in zip(vars.values(), substituted_args):
      if sub_var is None:
        # self.log_warning(
        #   f"sub var is None for var_arg: {var_arg},  skipping substitution"
        # )
        # self.log_warning(f"vars: {vars}")
        # self.log_warning(
        #   f"self.encode_ctx.current_frame: {self.encode_ctx.current_frame}"
        # )
        # self.log_warning(f"want to substitute in expr: {expr}")
        continue
      substitute_list.append((var_arg, sub_var.var))  # pyright: ignore[reportUnknownMemberType]
    if not substitute_list:
      return arg_var
    arg_var = cast(ArithRef, substitute(arg_var, substitute_list))
    return arg_var

  def get_var(self, var_name: str, idx: int) -> EncoderContextVariable | None:
    frame = self.idx_frame_map[idx]
    while frame is not None:
      if var_name in frame.current_frame.vars:
        return frame.current_frame.vars[var_name]
      mapping = self.idx_frame_map[frame.idx]
      frame = mapping.prev_frame
    return None

  def restore_from_frame_map(self, index: int):
    if index < 0 or index >= len(self.frame_map):
      raise EncoderError(f"Index {index} out of bounds for frame_map")
    self.encode_ctx.current_frame = self.frame_map[index]

  # After this function, we do not use push_frame anymore, just step into and out of frames
  def fill_var_bit_size(self):
    from src.fsm.fsm_new import PathNodeKind
    from src.parse3d import PrimitiveType, ArrayType, IntLiteral

    current_bit_expr = "0"
    current_bit_number = 0

    for idx, pn in enumerate(self.path.nodes):
      match pn.kind:
        case PathNodeKind.NODE_W_CONDITION | PathNodeKind.NODE_WO_CONDITION:
          self.restore_from_frame_map(idx)
          if pn.node is None:
            raise ValueError(
              "PathNodeKind.NODE_W_CONDITION and NODE_WO_CONDITION must have node"
            )
          if pn.node.type_expr is None:
            raise ValueError(
              "PathNodeKind.NODE_W_CONDITION and NODE_WO_CONDITION must have node.type_expr"
            )

          match pn.node.type_expr:
            case PrimitiveType() as pt:
              self.curr_vars_bit_size[pn.node.name] = pt.bits
            case ArrayType() as at:
              match at.elem_type:
                case PrimitiveType() as elem_pt:
                  match at.size:
                    case IntLiteral() as il:
                      self.curr_vars_bit_size[pn.node.name] = elem_pt.bits * int(
                        il.value.val
                      )
                    case _:
                      pass
                case _:
                  pass
            case _:
              pass

          # update current_bit_expr and current_bit_number
          bit_size = pn.bit_size()

          from src.parse3d import Parse3D

          bit_size_expr: (
            ArithExpr
            | IntLiteral
            | Ident
            | LogicalExpr
            | CmpExpr
            | FunctionCall
            | ParenExpr
          ) = Parse3D(str(bit_size)).handle_arith_expr()

          bit_size_expr_z3 = self.substitute_var(
            bit_size_expr, bit_size_expr.to_arith_z3(), idx
          )
          if not bit_size_expr_z3.eq(bit_size_expr.to_arith_z3()):  # pyright: ignore[reportUnknownMemberType]
            # self.log_info(f"bit size before: {bit_size}")
            bit_size = (
              f"({bit_size_expr_z3})"
              if not str(bit_size_expr_z3).isdigit()
              else str(bit_size_expr_z3)
            )
            # self.log_info(f"bit size after substitution: {bit_size}")

          if bit_size.isdigit():
            current_bit_number += int(bit_size)
          else:
            if current_bit_number % 8 != 0:
              raise ValueError(
                f"Non-byte-aligned bit size expr {current_bit_expr} + {bit_size}"
              )
            if current_bit_number > 0:
              if current_bit_expr == "0":
                current_bit_expr = str(current_bit_number)
              else:
                current_bit_expr = f"(({current_bit_expr}) + ({current_bit_number}))"
            if current_bit_expr == "0":
              current_bit_expr = bit_size
            else:
              current_bit_expr = f"(({current_bit_expr}) + ({bit_size}))"
            current_bit_number = 0
        case PathNodeKind.FSM_START:
          # we want to add a frame
          if pn.fsm is None:
            raise ValueError("PathNodeKind.FSM_START must have fsm")
          # store current fsm size expr and bit number in previous frame
          self.current_frame.fsm_size_cache = (
            deepcopy(current_bit_expr),
            current_bit_number,
          )
          current_bit_expr = "0"
          current_bit_number = 0
          self.restore_from_frame_map(idx)
          # do not want to handle parameters' definition here, just add bit sizes
          for param in pn.fsm.fsm_params:
            match param.typ:
              case PrimitiveType() as pt:
                self.curr_vars_bit_size[param.name] = pt.bits
              case ArrayType() as at:
                match at.elem_type:
                  case PrimitiveType() as elem_pt:
                    match at.size:
                      case IntLiteral() as il:
                        self.curr_vars_bit_size[param.name] = elem_pt.bits * int(
                          il.value.val
                        )
                      case _:
                        pass
                  case _:
                    pass
              case _:
                pass
        case PathNodeKind.FSM_END:
          if pn.fsm is None:
            raise ValueError("PathNodeKind.FSM_END must have fsm")
          # we want to step back a frame, but do not want to pop, since we may need vars later
          if self.encode_ctx.current_frame.prev is None:
            raise EncoderError("Cannot step back from global frame")

          # we want to 1. calculate fsm size for the current frame, and 2. restore current_bit_expr and current_bit_number from last frame
          from src.parse3d import Parse3D

          current_bit_expr_parsed = Parse3D(current_bit_expr).handle_arith_expr()
          current_bit_expr_z3 = self.substitute_var(
            current_bit_expr_parsed, current_bit_expr_parsed.to_arith_z3(), idx
          )
          if not current_bit_expr_z3.eq(current_bit_expr_parsed.to_arith_z3()):  # pyright: ignore[reportUnknownMemberType]
            # self.log_info(f"FSM_END current_bit_expr before: {current_bit_expr}")
            # self.log_info(f"FSM_END current_frame: {self.current_frame}")
            current_bit_expr = (
              f"({str(current_bit_expr_z3)})"
              if not str(current_bit_expr_z3).isdigit()
              else str(current_bit_expr_z3)
            )
            # self.log_info(
            #   f"FSM_END current_bit_expr after substitution: {current_bit_expr}"
            # )

          if current_bit_number % 8 != 0:
            raise ValueError(
              f"Non-byte-aligned bit size expr {current_bit_expr} in FSM_END, current_bit_number={current_bit_number}"
            )
          if current_bit_number > 0:
            if current_bit_expr == "0":
              current_bit_expr = str(current_bit_number)
            else:
              current_bit_expr = f"(({current_bit_expr}) + ({current_bit_number}))"
          prev_bit_expr, prev_bit_number = self.frame_map[idx].fsm_size_cache or (
            "0",
            0,
          )
          if self.current_frame.fsm_name.split("@")[0] != pn.fsm.name:
            raise ValueError(
              f"FSM_END {pn.fsm.name} does not match current frame {self.current_frame.fsm_name}"
            )
          self.current_frame.fsm_size_expr = (
            current_bit_expr if current_bit_expr != "0" else str(current_bit_number)
          )
          self.restore_from_frame_map(idx)
          # self.log_info(
          #   f"FSM {self.current_frame.fsm_name} size expr: {self.current_frame.fsm_size_expr}"
          # )
          current_bit_expr = (
            (f"(({prev_bit_expr}) + ({current_bit_expr}))")
            if prev_bit_expr != "0"
            else current_bit_expr
          )
          current_bit_number = prev_bit_number
        case PathNodeKind.CONDITION:
          self.restore_from_frame_map(idx)
    # import sympy as sp

    # for _, fm in enumerate(self.frame_map):
    #   if not fm.fsm_size_simplified:
    #     if fm.fsm_size_expr is None:
    #       raise ValueError(
    #         f"FSM size expr is None for frame {fm.fsm_name} during simplification"
    #       )
    #     fm.fsm_size_expr = str(sp.simplify(sp.sympify(fm.fsm_size_expr)))

  def fill_vars(self):
    from src.fsm.fsm_new import PathNodeKind, FSM
    from src.parse3d import TypeExpr

    for idx, pn in enumerate(self.path.nodes):
      match pn.kind:
        case PathNodeKind.NODE_W_CONDITION | PathNodeKind.NODE_WO_CONDITION:
          if pn.node is None:
            raise ValueError("PathNodeKind.NODE_W_CONDITION must have node")
          # a node itself will define a variable, shadowing any variable defined before
          self.restore_from_frame_map(idx)
          if pn.node.name in self.curr_vars:
            raise EncoderError(
              f"Variable {pn.node.name} re-defined in the same frame {self.current_frame.fsm_name}"
            )
          self.curr_vars[pn.node.name] = EncoderContextVariable(
            pn.node.name, None, self.current_frame
          )
          self.vars[self.curr_vars[pn.node.name].canonical_name] = self.curr_vars[
            pn.node.name
          ]
          if pn.kind is PathNodeKind.NODE_W_CONDITION and (
            pn.node.tightened_condition_ast is None  # pyright: ignore[reportUnnecessaryComparison]
            or pn.node.tightened_condition_ast is FSM.dummy_true_condition
          ):
            raise ValueError(
              f"PathNodeKind.NODE_W_CONDITION {pn} must have node.tightened_condition_ast, got {pn.node.tightened_condition_ast}"
            )
          # we want to add vars that needs to be handled specially in conditions
          vars_in_condition = pn.node.tightened_condition_ast.get_vars()
          special_handling_list = list(
            filter(lambda x: "@" in x, vars_in_condition.keys())
          )
          from src.tool.str_functions import normalize_name

          for name in special_handling_list:
            self.current_frame.vars[normalize_name(name)] = EncoderContextVariable(
              name, None, self.current_frame
            )
            self.vars[self.current_frame.vars[normalize_name(name)].canonical_name] = (
              self.current_frame.vars[normalize_name(name)]
            )
          for name in vars_in_condition.keys():
            if name in ("this"):
              self.current_frame.vars[normalize_name(name)] = EncoderContextVariable(
                name, None, self.current_frame
              )
              self.vars[
                self.current_frame.vars[normalize_name(name)].canonical_name
              ] = self.current_frame.vars[normalize_name(name)]
        case PathNodeKind.FSM_START:
          # we have already pushed frame in fill_var_bit_size, now step into it
          if pn.fsm is None:
            raise ValueError("PathNodeKind.FSM_START must have fsm")
          # want to create bindings for parameters
          if (
            len(pn.fsm.fsm_params) != len(pn.fsm_args)
            and pn.fsm.name != self.context.entrypoint
          ):
            raise EncoderError(
              f"FSM_START {pn.fsm.name} has {len(pn.fsm.fsm_params)} params but {len(pn.fsm_args)} args"
            )
          # first, convert args to ArithRef
          arg_vars: list[ArithRef] = []
          for arg in pn.fsm_args:
            if isinstance(arg, TypeExpr):
              raise EncoderError("Cannot use TypeExpr as FSM argument")
            arg_vars.append(arg.to_arith_z3())
          # then, we want to substitute variables in arg_vars with canonical names from current context
          substituted_arg_vars: list[ArithRef] = []
          for fsm_arg, arg_var in zip(pn.fsm_args, arg_vars):
            arg_var = self.substitute_var(fsm_arg, arg_var, idx)
            if not isinstance(arg_var, ArithRef):
              raise EncoderError(
                f"FSM argument substitution did not result in ArithRef: {arg_var}"
              )
            substituted_arg_vars.append(arg_var)
          # above is done when the frame is not restored yet, such that the variables are not shadowed
          self.restore_from_frame_map(idx)
          # finally, create EncoderContextVariable for each parameter
          for param, arg_var in zip(pn.fsm.fsm_params, substituted_arg_vars):
            # self.log_info(
            #   f"Binding param {param.name} in FSM_START {pn.fsm.name}, found in ctx: {self.encode_ctx.get_var(param.name)}, related_arg: {arg_var}"
            # )
            if param.name in self.curr_vars:
              raise EncoderError(
                f"Parameter {param.name} re-defined in the same frame {self.current_frame.fsm_name}"
              )
            self.curr_vars[param.name] = EncoderContextVariable(
              param.name, related_arg=arg_var, in_frame=self.current_frame
            )
            self.vars[self.curr_vars[param.name].canonical_name] = self.curr_vars[
              param.name
            ]
        case PathNodeKind.FSM_END:
          # we have already stepped back frame in fill_var_bit_size
          if pn.fsm is None:
            raise ValueError("PathNodeKind.FSM_END must have fsm")
          # restore frame, despite not necessary
          if self.current_frame.fsm_name.split("@")[0] != pn.fsm.name:
            raise ValueError(
              f"FSM_END {pn.fsm.name} does not match current frame {self.current_frame.fsm_name}, self.encoder_ctx.current_frame={self.encode_ctx.current_frame}"
            )
          self.restore_from_frame_map(idx)
        case PathNodeKind.CONDITION:
          self.restore_from_frame_map(idx)
          # if pn.condition_ast is None or pn.condition_ast is FSM.dummy_true_condition:
          #   raise ValueError("PathNodeKind.CONDITION must have condition_ast")
          if pn.tightened_condition_ast is None:
            raise ValueError("PathNodeKind.CONDITION must have tightened_condition_ast")
          if pn.tightened_condition_ast is FSM.dummy_true_condition:
            continue
          vars_in_condition = pn.tightened_condition_ast.get_vars()
          special_handling_list = list(
            filter(lambda x: "@" in x, vars_in_condition.keys())
          )
          from src.tool.str_functions import normalize_name

          for name in special_handling_list:
            if normalize_name(name) in self.current_frame.vars:
              raise EncoderError(
                f"Variable {name} re-defined in the same frame {self.current_frame.fsm_name}"
              )
            self.current_frame.vars[normalize_name(name)] = EncoderContextVariable(
              name, None, self.current_frame
            )
            self.vars[self.current_frame.vars[normalize_name(name)].canonical_name] = (
              self.current_frame.vars[normalize_name(name)]
            )
          for name in vars_in_condition.keys():
            if name in ("this"):
              self.current_frame.vars[normalize_name(name)] = EncoderContextVariable(
                name, None, self.current_frame
              )
              self.vars[
                self.current_frame.vars[normalize_name(name)].canonical_name
              ] = self.current_frame.vars[normalize_name(name)]

  def build_frame_map(self):
    from src.fsm.fsm_new import PathNodeKind

    self.frame_map = []

    for idx, pn in enumerate(self.path.nodes):
      match pn.kind:
        case PathNodeKind.NODE_W_CONDITION | PathNodeKind.NODE_WO_CONDITION:
          self.frame_map.append(self.encode_ctx.current_frame)
        case PathNodeKind.FSM_START:
          if pn.fsm is None:
            raise ValueError("PathNodeKind.FSM_START must have fsm")
          self.encode_ctx.push_frame(
            f"{pn.fsm.name}@{idx}"
          )  # push new frame, use idx to distinguish multiple calls to the same fsm in the same depth
          self.frame_map.append(self.encode_ctx.current_frame)
        case PathNodeKind.FSM_END:
          if pn.fsm is None:
            raise ValueError("PathNodeKind.FSM_END must have fsm")
          if self.current_frame.fsm_name.split("@")[0] != pn.fsm.name:
            raise ValueError(
              f"FSM_END {pn.fsm.name} does not match current frame {self.current_frame.fsm_name}"
            )
          if self.encode_ctx.current_frame.prev is None:
            raise EncoderError("Cannot step back from global frame")
          self.encode_ctx.current_frame = self.encode_ctx.current_frame.prev
          self.frame_map.append(self.encode_ctx.current_frame)
        case PathNodeKind.CONDITION:
          self.frame_map.append(self.encode_ctx.current_frame)

    # want to build a data structure that 1. records unique frames along the path and keep the order, and 2. for each idx, give (prev_frame, current_frame, next_frame) according to the path

    # first pass, build current_frame
    for idx, frame in enumerate(self.frame_map):
      self.idx_frame_map.append(
        Encoder.IdxFrameMapping(
          idx,
          prev_frame=None,
          current_frame=frame,
          next_frame=None if idx + 1 < len(self.frame_map) else None,
        )
      )

    # second pass, build prev_frame
    prev_frame: Encoder.IdxFrameMapping | None = None
    for idx, mapping in enumerate(self.idx_frame_map):
      if self.idx_frame_map[idx].prev_frame is None:
        mapping.prev_frame = prev_frame
      if prev_frame is None or mapping.current_frame != prev_frame.current_frame:
        prev_frame = mapping

    # third pass, build next_frame
    next_frame: Encoder.IdxFrameMapping | None = None
    for idx in range(len(self.idx_frame_map) - 1, -1, -1):
      mapping = self.idx_frame_map[idx]
      if mapping.next_frame is None:
        mapping.next_frame = next_frame
      if next_frame is None or mapping.current_frame != next_frame.current_frame:
        next_frame = mapping

  def fill_self_vars(self):
    """
    Fill in variables and their bit sizes along the path, mapping nodes to frames, i.e. building self.frame_map
    Frame map is nessesary since we may step into and out of frames multiple times along the path, and we need to know which frame we are in at each node, without creating and popping frames multiple times.
    1. First, fill in bit sizes of variables along the path, building self.frame_map
    2. Then, fill in variables along the path, using self.frame_map to restore frames
    """
    self.build_frame_map()
    self.fill_vars()
    self.fill_var_bit_size()

  def make_special_handling_constraints(
    self, special_handling_list: list[str], idx: int
  ) -> list[BoolRef]:
    from src.tool.str_functions import normalize_name

    constraints: list[BoolRef] = []
    for var_name in special_handling_list:
      match = re.match(r"@(\w+)\((\w+)\)\[(\w+)\]", var_name)
      if match:
        function, target, id_str = match.groups()
        # Assuming the logic for special handling will be added later.
        # For now, just storing the target seems appropriate given the context.
        self.var_to_special_handling[
          f"{self.current_frame.canonical_prefix}_{target}"
        ] = (function, target, id_str)
        self.current_frame.var_to_special_handling[target] = (function, target, id_str)
        match function:
          case "len":
            ...
          case "sizeof":
            if target == "this":
              if self.current_frame.fsm_name == "global":
                raise EncoderError("Cannot use sizeof(this) in global frame")
              target = self.current_frame.fsm_name
            size_str = self.current_frame.fsm_size_expr
            if size_str is None:
              raise ValueError(
                f"Size of {target} not found in current frame {self.current_frame.fsm_name}"
              )
            from src.parse3d import Parse3D

            size_expr = Parse3D(size_str).handle_arith_expr()
            from src.tool import normalize_name

            normalized_var_name = normalize_name(var_name)
            if self.get_var(normalized_var_name, idx) is None:
              raise EncoderError(
                f"Variable {var_name} not found in current context for special handling"
              )
            constraints.append(
              self.get_var(normalized_var_name, idx).var  # pyright: ignore[reportOptionalMemberAccess, reportArgumentType]
              == self.substitute_var(
                size_expr,
                (size_expr.to_arith_z3() / IntVal(8)),  # pyright: ignore[reportUnknownArgumentType]
                idx,
              )
            )
            self.log_info(
              f"Added special handling constraint for sizeof: {constraints[-1]}"
            )
          case _:
            todo(f"Function {function} in special handling")
    return constraints

  def constraint_collection(self):
    from src.fsm.fsm_new import PathNodeKind, FSM

    if (
      self.path.nodes[0].kind != PathNodeKind.FSM_START
      or self.path.nodes[0].fsm is None
    ):
      raise EncoderError("Path must start with FSM_START node")

    constraints: list[BoolRef] = []

    with self.step("Collecting constraints"):
      for idx, pn in enumerate(self.path.nodes):
        match pn.kind:
          case PathNodeKind.NODE_W_CONDITION | PathNodeKind.NODE_WO_CONDITION:
            if pn.node is None:
              raise ValueError("PathNodeKind.NODE_W_CONDITION must have node")
            if (
              pn.node.tightened_condition_ast is None  # pyright: ignore[reportUnnecessaryComparison]
              or pn.node.tightened_condition_ast is FSM.dummy_true_condition
            ):
              continue
            # first, restore frame
            self.restore_from_frame_map(idx)
            # then, convert tightened_condition_ast to z3 BoolRef
            tightened_condition_z3 = self.substitute_var(
              pn.node.tightened_condition_ast,
              pn.node.tightened_condition_ast.to_bool_z3(),
              idx,
            )
            if not isinstance(tightened_condition_z3, BoolRef):
              raise EncoderError(
                f"Tightened condition z3 is not BoolRef: {tightened_condition_z3}"
              )
            # do special handling
            special_handling_list = list(
              filter(
                lambda x: "@" in x, pn.node.tightened_condition_ast.get_vars().keys()
              )
            )
            constraints.extend(
              self.make_special_handling_constraints(special_handling_list, idx=idx)
            )
            # finally, add the tightened condition constraint
            constraints.append(tightened_condition_z3)
          case PathNodeKind.CONDITION:
            if pn.tightened_condition_ast is FSM.dummy_true_condition:
              continue
            tightened_condition = pn.tightened_condition_ast
            if tightened_condition is None:
              continue
            self.restore_from_frame_map(idx)
            self.log_info(
              f"Adding CONDITION constraint at idx {idx}, tightened_condition: {tightened_condition}"
            )
            tightened_condition_z3 = self.substitute_var(
              tightened_condition, tightened_condition.to_bool_z3(), idx
            )
            # first, restore frame
            # do special handling
            special_handling_list = list(
              filter(lambda x: "@" in x, tightened_condition.get_vars().keys())
            )
            constraints.extend(
              self.make_special_handling_constraints(special_handling_list, idx)
            )
            # finally, add the tightened condition constraint
            constraints.append(tightened_condition_z3)  # pyright: ignore[reportArgumentType]
          case PathNodeKind.FSM_START:
            # make bindings between arguments and parameters
            self.restore_from_frame_map(idx)
            if pn.fsm is None:
              raise ValueError("PathNodeKind.FSM_START must have fsm")
            if (
              len(pn.fsm.fsm_params) != len(pn.fsm_args)
              and pn.fsm.name != self.context.entrypoint
            ):
              raise ValueError(
                f"FSM_START {pn.fsm.name} has {len(pn.fsm.fsm_params)} params but {len(pn.fsm_args)} args"
              )
            if pn.fsm.name == self.context.entrypoint:
              # no need to bind arguments for entrypoint
              continue
            # first, convert args to ArithRef
            for param in pn.fsm.fsm_params:
              param_in_ctx = self.get_var(param.name, idx)
              self.log_info(
                f"Binding param {param.name} in FSM_START {pn.fsm.name}, found in ctx: {param_in_ctx}"
              )
              if param_in_ctx is None:
                self.log_error(f"Current frame: {self.current_frame}")
                self.log_error(f"Vars in current frame: {self.curr_vars}")
                raise ValueError(
                  f"Parameter {param.name} not found in current context for FSM_START {pn.fsm.name}"
                )
              param_var = param_in_ctx.var
              related_arg = param_in_ctx.related_arg
              if related_arg is None:
                self.log_error(f"Current frame: {self.current_frame}")
                self.log_error(f"Vars in current frame: {self.curr_vars}")
                raise ValueError(
                  f"Related argument for parameter {param.name} is None in FSM_START {pn.fsm.name}"
                )
              self.log_info(
                f"Adding constraint for parameter {param.name} in FSM_START {pn.fsm.name}: {param_var} == {related_arg}"
              )
              constraints.append(param_var == related_arg)  # pyright: ignore[reportArgumentType]
          case PathNodeKind.FSM_END:
            pass

    # make constraints unique
    unique_constraints: set[str] = set()
    filtered_constraints: list[BoolRef] = []
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
    block_clauses: list[BoolRef],
    solver: Solver | None = None,
  ):
    s = solver if solver is not None else self.solver
    s.reset()  # pyright: ignore[reportUnknownMemberType]
    # we want to make constraints unique
    unique_constraints: set[str] = set()
    filtered_constraints: list[BoolRef] = []
    for c in constraints:
      c_str = c.__str__()
      if c_str not in unique_constraints:
        unique_constraints.add(c_str)
        filtered_constraints.append(c)
    constraints = filtered_constraints

    for c in constraints:
      s.assert_and_track(c, c.__str__())  # pyright: ignore[reportUnknownMemberType]
    for bc in block_clauses:
      s.assert_and_track(bc, bc.__str__())  # pyright: ignore[reportUnknownMemberType]

  @staticmethod
  def should_be_negated(var_name: str, target_mutate_var: str | None) -> bool:
    if "@" in var_name:
      return False
    if "this" == var_name:
      return False
    if target_mutate_var is not None:
      return target_mutate_var == var_name
    return True

  def solve_one(
    self, constraints: list[BoolRef], blocked_clauses: list[BoolRef]
  ) -> dict[str, int] | None:
    var_value_map: dict[str, int] = {}
    from z3 import sat  # pyright: ignore[reportAny]

    self.enforce_constraints(constraints, blocked_clauses, solver=self.solver)
    if self.solver.check() == sat:  # pyright: ignore[reportUnknownMemberType]
      model = self.solver.model()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
      for var_name, var in self.vars.items():
        if model.eval(var.var, model_completion=True) is not None:  # pyright: ignore[reportUnknownMemberType]
          value = model.eval(var.var, model_completion=True).as_long()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
          var_value_map[var_name] = value
        else:
          var_value_map[var_name] = 0
    else:
      return None  # should not happen but just in case
    return var_value_map

  def encode_one(self, var_value_map: dict[str, int]) -> bytes:
    from src.fsm.fsm_new import PathNodeKind

    byte_array = bytearray()
    current_bit_size = 0
    current_value = 0
    for idx, pn in enumerate(self.path.nodes):
      match pn.kind:
        case PathNodeKind.NODE_W_CONDITION | PathNodeKind.NODE_WO_CONDITION:
          self.restore_from_frame_map(idx)
          if pn.node is None:
            raise ValueError(
              "PathNodeKind.NODE_W_CONDITION and NODE_WO_CONDITION must have node"
            )
          var = self.curr_vars.get(pn.node.name)
          if var is None:
            raise EncoderError(
              f"Variable {pn.node.name} not found in current context during encoding"
            )
          if var.canonical_name not in var_value_map:
            raise EncoderError(
              f"Variable {var.canonical_name} not found in var_value_map during encoding"
            )
          if var.name not in self.curr_vars_bit_size:
            # pn is an array type
            special_handling = self.var_to_special_handling.get(var.canonical_name)
            if special_handling is None:
              self.log_error(f"vars_bit_size: {self.current_frame.vars_bit_size}")
              self.log_error(f"var_to_special_handling: {self.var_to_special_handling}")
              self.log_error(f"var_value_map: {var_value_map}")
              self.log_error(f"vars: {self.vars}")
              raise ValueError(
                f"Variable {pn.node.name} is not in vars_bit_size and no special handling found, special_handling: {self.var_to_special_handling}, var: {var}"
              )
            function, target, id_str = special_handling
            if target is None or id_str is None or function is None:  # pyright: ignore[reportUnnecessaryComparison]
              raise ValueError(
                f"Special handling for variable {var.name} is incomplete: {special_handling}"
              )
            from src.tool.str_functions import normalize_name
            from src.tool.tool import todo

            match function:
              case "len":
                template_name = f"@{function}({target})[{id_str}]"
                name_to_lookup = f"{self.current_frame.canonical_prefix}_{normalize_name(template_name)}"
                if name_to_lookup not in var_value_map:
                  raise ValueError(
                    f"Variable {normalize_name(template_name)} not found in var_value_map during encoding"
                  )
                length = var_value_map[name_to_lookup]
                if target != pn.node.name:
                  raise ValueError(
                    f"Length special handling target {target} does not match variable name {pn.node.name}"
                  )
                if length == 0:
                  continue
                if length < 0:
                  raise EncoderError(
                    f"Length of variable {target} is negative: {length}"
                  )
                byte_to_write = bytes()
                for _ in range(length):
                  byte_to_write += (0).to_bytes(1, byteorder="big")
                byte_array.extend(byte_to_write)
              case "sizeof":
                ...
              case _:
                todo(f"Function {function} in special handling during encoding")
          else:
            bit_size = self.curr_vars_bit_size[pn.node.name]
            value = var_value_map[var.canonical_name]
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

  def encode(self) -> Generator[bytes, None, None]:
    from z3 import sat  # pyright: ignore[reportAny]

    if self.encoded_cases is not None:
      for case in self.encoded_cases:
        yield case
      return
    self.encoded_cases = []

    if self._list_of_case_table:
      self._list_of_case_table = []
    with self.step("Encoding"):
      constraints = self.constraint_collection()
      self.enforce_constraints(constraints, block_clauses=[])

      generated = 0
      encoded_packets: list[bytes] = []
      blocked_clauses: list[BoolRef] = []
      same_variable_negate_count: dict[str, int] = {}
      with self.step("Packet Generation"):
        fixed = False
        while generated < self.encode_count:
          var_value_map = self.solve_one(constraints, blocked_clauses)
          if var_value_map is None and generated == 0:
            raise EncoderError(
              f"No satifiable model found, unsat_core: {self.solver.unsat_core()}",  # pyright: ignore[reportUnknownMemberType]
              unsat_core=self.solver.unsat_core(),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            )
          if var_value_map is None:
            break
          generated += 1
          if generated == 1 and fixed:
            generated = 0
            raise EncoderError(
              "First encoding already fixed special handling variables, which means no valid encoding can be generated.",
              unsat_core=self.solver.unsat_core(),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            )
          if generated == 1:
            # we want to fix all sizeof and len special handling variables to avoid breaking length constraints
            self.log_info(
              "First encoding generated, fixing special handling variables for subsequent encodings."
            )
            for target_var in self.var_to_special_handling.keys():
              # self.log_info(f"Fixing variable {target_var}")
              # self.log_info(f"Var value map: {var_value_map}")
              # self.log_info(f"Vars: {self.vars.keys()}")

              target_encode_var = self.vars.get(target_var, None)
              if target_encode_var is None:
                raise EncoderError(
                  f"Target encode variable {target_var} not found in vars for special handling fixing"
                )
              # self.log_info(f"Target encode var: {target_encode_var}")
              var_name = target_encode_var.name
              template_name_len = f"@len({var_name})[placeholder]"
              template_name_sizeof = f"@sizeof({var_name})[placeholder]"
              template_name_len = (
                target_encode_var.in_frame.canonical_prefix + "_" + template_name_len  # pyright: ignore[reportOptionalMemberAccess]
              )
              template_name_sizeof = (
                target_encode_var.in_frame.canonical_prefix  # pyright: ignore[reportOptionalMemberAccess]
                + "_"
                + template_name_sizeof
              )
              from src.tool.str_functions import normalize_name

              normalized_template_name_len = normalize_name(template_name_len)
              normalized_template_name_sizeof = normalize_name(template_name_sizeof)
              if normalized_template_name_len in self.vars:
                self.log_info(
                  f"Fixing length variable {normalized_template_name_len} to value {var_value_map[normalized_template_name_len]}"
                )
                constraints.append(
                  Int(normalized_template_name_len)  # pyright: ignore[reportUnknownArgumentType]
                  == IntVal(var_value_map[normalized_template_name_len])
                )
              if normalized_template_name_sizeof in self.vars:
                self.log_info(
                  f"Fixing sizeof variable {normalized_template_name_sizeof} to value {var_value_map[normalized_template_name_sizeof]}"
                )
                constraints.append(
                  Int(normalized_template_name_sizeof)  # pyright: ignore[reportUnknownArgumentType]
                  == IntVal(var_value_map[normalized_template_name_sizeof])
                )
            fixed = True
          self.list_of_var_value_map.append(var_value_map)
          # block the current solution for next iteration
          negated = False
          chosen_var_name = ""
          for var_name in var_value_map.keys():
            var = self.vars[var_name]
            if (
              not negated
              and same_variable_negate_count.get(var_name, 0)
              <= self.max_muate_attempt_for_one_variable
              and self.should_be_negated(var.name, self.target_mutate_var)
            ):
              from z3 import Solver

              current_var = var_value_map[var_name]
              if current_var < 0:
                self.log_info(
                  f"Variable {var_name} has negative value {current_var}, skipping negation."
                )
                continue
              new_block_clause = var.var != IntVal(current_var)  # pyright: ignore[reportUnknownVariableType]
              # self.log_info(str(var))
              # self.log_info(str(IntVal(current_var)))
              # self.log_info(str(constraints))
              another_solver = Solver()
              self.enforce_constraints(
                constraints,
                block_clauses=blocked_clauses + [new_block_clause],
                solver=another_solver,
              )
              if another_solver.check() == sat:  # pyright: ignore[reportUnknownMemberType]
                # self.log_info(
                #   str(another_solver.model())
                # )
                if var_name == "global_BFDControl_at_0_A":
                  breakpoint()
                same_variable_negate_count[var_name] = (
                  same_variable_negate_count.get(var_name, 0) + 1
                )
                blocked_clauses.append(new_block_clause)  # pyright: ignore[reportUnknownArgumentType]
                negated = True
                chosen_var_name = var_name
                self.enforce_constraints(
                  constraints, blocked_clauses, solver=self.solver
                )
                self.log_info(f"Adding {new_block_clause} to block clauses.")
                if (
                  same_variable_negate_count[var_name]
                  >= self.max_muate_attempt_for_one_variable
                ):
                  self.log_info(
                    f"Variable {var_name} has reached max mutate attempts {self.max_muate_attempt_for_one_variable}, will not be negated further."
                  )
                  blocked_clauses.clear()
              else:
                self.log_info(
                  f"Negating variable {var_name} would lead to unsat, skipping negation."
                )
                same_variable_negate_count[var_name] = (
                  self.max_muate_attempt_for_one_variable
                )
          if not negated and generated >= 1:
            self.log_info(
              "No variable negated in this iteration, stopping further generation."
            )
            self.log_info("Target mutate var: " + str(self.target_mutate_var))
            break
          else:
            ...
          try:
            # self.log_warning(
            #   f"Encoding packet {generated} with variable assignments: {var_value_map}"
            # )
            encoded_packet = self.encode_one(var_value_map)
            self.encoded_cases.append(encoded_packet)
            self._list_of_case_table.append(var_value_map)
            # self.log_warning("yielding encoded packet")
            yield encoded_packet
          except EncoderError as e:
            self.log_error(f"Encoding error: {e}")
            generated -= 1  # do not count this packet
            # stop negating this variable further
            blocked_clauses.clear()
            same_variable_negate_count[chosen_var_name] = (
              self.max_muate_attempt_for_one_variable
            )
            # self.log_info(str(var_value_map))
      self.log_info(f"Generated {len(self.encoded_cases)} packets.")
      self.encoded_cases = encoded_packets
