from __future__ import annotations
from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override
from enum import Enum
from typing_extensions import deprecated
from src.parse3d import AstVisitor
from src.tool import todo

if TYPE_CHECKING:
  from src.parse3d import (
    Module,
    Expr,
    ParserContext,
    TypeExpr,
    LogicalExpr,
    CmpExpr,
    ParenExpr,
    Struct,
    CaseType,
    FieldDecl,
    CaseBranch,
    ArithExpr,
    IntLiteral,
    Ident,
    FunctionCall,
  )

@deprecated("Use src/fsm/fsm_new.py instead")
class FSMKind(Enum):
  Empty = 1
  Normal = 2

@deprecated("Use src/fsm/fsm_new.py instead")
class NodeKind(Enum):
  Normal = 0
  Start = 1
  Empty = 2


@dataclass
@deprecated("Use src/fsm/fsm_new.py instead")
class Node:  # children of Node can be Node or FSM
  name: str
  parser_context: "ParserContext"
  kind: NodeKind = NodeKind.Normal
  type_expr: "TypeExpr | None" = None
  condition_str: str | None = None
  _condition_ast: "LogicalExpr | CmpExpr | ParenExpr | Expr | None" = None
  _more_constrained_ast: "LogicalExpr | CmpExpr | ParenExpr | Expr | None" = None
  transitions: dict["Node | FSM", "LogicalExpr | CmpExpr | ParenExpr | None"] = field(
    default_factory=dict
  )  # Transitions to children with conditions
  size: str = "0"  # todo: maybe change to Expr

  def __post_init__(self):
    self.update_constraint_str_based_on_ast()

  def add_transition(
    self, condition: "LogicalExpr | CmpExpr | ParenExpr | None", next: "Node | FSM"
  ) -> None:
    self.transitions[next] = condition

  @property
  def more_constrained_ast(self) -> "LogicalExpr | CmpExpr | ParenExpr | Expr":
    self.update_constraint_str_based_on_ast()
    if self._more_constrained_ast is not None:
      return self._more_constrained_ast
    if self.condition_str is None:
      return todo("True condition")
    from src.parse3d import Parse3D
    from src.parse3d import LogicalExpr, CmpExpr, ParenExpr

    p = Parse3D(self.condition_str)
    cond = p.handle_logical_expr()
    if not isinstance(cond, (LogicalExpr | CmpExpr | ParenExpr)):
      raise ValueError(
        f"Condition string must be a LogicalExpr or CmpExpr, got {type(cond)}"
      )
    self._more_constrained_ast = cond
    return cond

  def update_constraint_str_based_on_ast(self):
    from src.tool import (
      length_array,
      length_byte_size_array,
      a_and_b,
      size_mod_eq_zero,
    )

    if self.condition_ast is None:
      self.condition_str = "True"

    base_str = (
      self.condition_ast.__str__() if self.condition_ast is not None else "True"
    )
    from src.parse3d import PrimitiveType, ArrayType, LogicalExpr, CmpExpr, ParenExpr

    match self.type_expr:
      case None:
        self.condition_str = base_str
      case PrimitiveType() as pt:
        bits = pt.bits
        primitives_bits_max: int = 2**bits - 1  # pyright: ignore[reportAny]
        self.condition_str = a_and_b(
          a_and_b(f"{self.name} >= 0", f"{self.name} <= {primitives_bits_max}"),
          base_str,
        )
        # * Here I cannot handle computation of `sizeof`, since struct may vary in size. This will be handled in later dfs separately for each possible path in the FSM
      case (
        ArrayType() as at
      ):  # Handle array as a very large UInt, the constraint should be its bit size
        array_size = at.size
        array_name = self.name
        is_byte_size = at.is_byte_size
        array_size_str = array_size.__str__()
        arith_result = None
        try:
          arith_result = eval(array_size_str)  # pyright: ignore[reportAny]
        except Exception:
          arith_result = None
        if arith_result is not None and isinstance(arith_result, int):
          # the array size is fixed
          array_size_str = str(arith_result)
        if array_size_str.isdigit() and is_byte_size:
          # No need to insert length_array constraint, can just handle as primitive type
          bits = int(array_size_str) * 8
          array_bits_max: int = 2**bits - 1  # pyright: ignore[reportAny]
          self.condition_str = a_and_b(
            a_and_b(f"{self.name} >= 0", f"{self.name} <= {array_bits_max}"), base_str
          )
        elif array_size_str.isdigit() and not is_byte_size:
          # cannot handle as primitive type, since the type may not be primitive
          constranint_length = length_array(array_name, array_size_str)
          self.condition_str = a_and_b(constranint_length, base_str)
        elif is_byte_size:
          constranint_length = length_byte_size_array(array_name, array_size_str)
          constranint_length_mod = size_mod_eq_zero(
            array_size_str, int(at.elem_type.name[4:-2]) // 8
          )
          self.condition_str = a_and_b(
            constranint_length, a_and_b(constranint_length_mod, base_str)
          )
        else:
          constranint_length = length_array(array_name, array_size_str)
          self.condition_str = a_and_b(constranint_length, base_str)
      case _:
        raise NotImplementedError(
          f"TypeExpr {self.type_expr} not supported in Node condition_str generation"
        )

    if self.condition_str == "True":
      self._condition_ast = None
    elif self.condition_str is None:
      assert False, "Should not reach here"
    elif self.condition_ast is None:
      from src.parse3d import Parse3D

      p = Parse3D(self.condition_str)
      cond = p.handle_logical_expr()
      if not isinstance(cond, (LogicalExpr | CmpExpr | ParenExpr)):
        raise ValueError(
          f"Condition string must be a LogicalExpr or CmpExpr, got {type(cond)}"
        )
      self._condition_ast = cond

  @property
  def condition_ast(self) -> "LogicalExpr | CmpExpr | ParenExpr | Expr | None":
    return self._condition_ast

  @condition_ast.setter
  def condition_ast(
    self, value: "LogicalExpr | CmpExpr | ParenExpr | Expr | None"
  ) -> None:
    self._condition_ast = value
    self.update_constraint_str_based_on_ast()

  @override
  def __repr__(self) -> str:
    return (
      f"Node({self.name}, type={self.type_expr}, condition={self.condition_str})"
      if self.kind == NodeKind.Normal
      else "Node(Start)"
      if self.kind == NodeKind.Start
      else f"[{self.condition_str}]"
      if self.condition_str is not None
      else ""
    )

  @override
  def __hash__(self) -> int:
    return id(self)

  @override
  def __str__(self) -> str:
    return self.__repr__()


@deprecated("Use src/fsm/fsm_new.py instead")
class FSM:
  def __init__(
    self,
    name: str,
    parser_context: "ParserContext",
    size: str | None = None,
    size_expr_ast: "Expr | None" = None,
    fsm_kind: "FSMKind" = FSMKind.Normal,
    fsm_params: "list[FieldDecl] | None" = None,
    fsm_args: Sequence[
      ArithExpr
      | IntLiteral
      | Ident
      | LogicalExpr
      | CmpExpr
      | FunctionCall
      | ParenExpr
      | TypeExpr
    ]
    | None = None,
  ):
    self.fsm_kind: "FSMKind" = fsm_kind
    self.name: str = name

    self.entry: "Node" = Node(
      name="start",
      kind=NodeKind.Start,
      parser_context=parser_context,
    )
    self.exits: "list[Node | FSM]" = [self.entry]
    self.nexts: "list[Node | FSM]" = []  # not include in this FSM, but the following FSM
    self.size_expr: str | None = size
    self.size_expr_ast: "Expr | None" = None
    self.parser_context: "ParserContext" = parser_context
    self.fsm_params: "list[FieldDecl]" = fsm_params or []
    self.fsm_args: Sequence[
      ArithExpr
      | IntLiteral
      | Ident
      | LogicalExpr
      | CmpExpr
      | FunctionCall
      | ParenExpr
      | TypeExpr
    ] = fsm_args or []

  def addlists(self, node_or_FSM_list: "list[Node | FSM] | None") -> None:
    if node_or_FSM_list is None:
      return

    for node_or_FSM in node_or_FSM_list:
      for exit in self.exits:
        if isinstance(exit, Node):
          exit.add_transition(None, node_or_FSM)
        else:
          exit.addNext(node_or_FSM)

    self.exits = node_or_FSM_list

  def addNext(self, next: "Node | FSM") -> None:
    self.nexts.append(next)

  def addNexts(self, nexts: "list[Node | FSM]") -> None:
    self.nexts.extend(nexts)

  @override
  def __repr__(self):
    bfs_output: list[str] = []

    from collections import deque

    queue: "deque[Node | FSM]" = deque([self.entry])
    visited: "set[Node|FSM]" = set()
    while queue:
      current = queue.popleft()
      if current in visited:
        continue
      visited.add(current)
      bfs_output.append(current.__repr__())
      if isinstance(current, Node):
        for next_node in current.transitions.keys():
          if next_node not in visited:
            queue.append(next_node)
      else:
        for next_fsm in current.nexts:
          if next_fsm not in visited:
            queue.append(next_fsm)
    this_str = ""
    this_end = f"FSM_END({self.name})"
    match self.fsm_kind:
      case FSMKind.Empty:
        this_str = f"emptyFSM({self.name}): {self.size_expr if self.size_expr is not None else ''} "
      case FSMKind.Normal:
        this_str = (
          f"FSM({self.name}): {self.size_expr if self.size_expr is not None else ''} "
        )
    return this_str + " -> ".join(filter(None, bfs_output)) + " -> " + this_end

  def dfs(
    self,
    current: "Node | FSM",
    current_path: "Path",
    all_paths: "list[Path]",
    should_terminate: bool = False,
  ) -> None:
    should_terminate = should_terminate or (current in self.exits)

    if isinstance(current, Node):
      match current.kind:
        case NodeKind.Normal:
          current_path.add_node(
            PathNode(
              PathNodeKind.NODE_WO_CONDITION
              if current.condition_ast is None
              else PathNodeKind.NODE_W_CONDITION,
              node=current,
              fsm=None,
              condition_str=current.condition_str
              if current.condition_ast is not None
              else None,
            )
          )
        case NodeKind.Empty:
          if current.condition_ast is not None:
            current_path.add_node(
              PathNode(
                PathNodeKind.CONDITION,
                node=None,
                fsm=None,
                condition_str=current.condition_str,
              )
            )
        case NodeKind.Start:
          # do nothing for start node
          ...
    else:  # current is FSM
      match current.fsm_kind:
        case FSMKind.Empty:
          node = PathNode(
            PathNodeKind.CONDITION,
            fsm=current,
            condition_str=f"{current.size_expr} == 0"
            if current.size_expr is not None
            else "True",
          )
          current_path.add_node(node=node)
        case FSMKind.Normal:
          node = PathNode(
            PathNodeKind.FSM_START,
            fsm=current,
            condition_str=current.size_expr,
          )
          node_for_size_expr: PathNode | None = None
          if current.size_expr is not None:
            node_for_size_expr = PathNode(
              PathNodeKind.CONDITION,
              fsm=current,
              condition_str=current.size_expr,
            )
          if node_for_size_expr is not None:
            current_path.add_node(node=node_for_size_expr)
          current_path.add_node(node=node)

    if isinstance(current, Node) and not current.transitions and should_terminate:
      all_paths.append(current_path.copy())

    if isinstance(current, Node):
      for child, condition in current.transitions.items():
        condition_node = PathNode(
          PathNodeKind.CONDITION,
          node=None,
          fsm=None,
          condition_str=str(condition) if condition is not None else "True",
        )
        new_path = current_path.copy()
        new_path.add_node(condition_node)
        self.dfs(child, new_path, all_paths, should_terminate)
    elif isinstance(current, FSM):  # pyright: ignore[reportUnnecessaryIsInstance]
      entry_paths: "list[Path]" = []
      current.dfs(current.entry, current_path.copy(), entry_paths, False)
      if current.fsm_kind is FSMKind.Normal:
        for entry_path in entry_paths:
          entry_path.add_node(
            PathNode(
              PathNodeKind.FSM_END,
              fsm=current,
              condition_str=None,
            )
          )

      if not current.nexts:
        all_paths.extend(entry_paths)
      else:
        for i in range(len(entry_paths)):
          for child in current.nexts:
            self.dfs(child, entry_paths[i].copy(), all_paths, should_terminate)

  def save_all_paths(self) -> "Generator[Path]":
    all_paths: "list[Path]" = []
    self.dfs(self, Path([]), all_paths, False)
    for path in all_paths:
      yield path.renamed_copy()


@deprecated("Use src/fsm/fsm_new.py instead")
class FSMBuilder(AstVisitor):
  def __init__(self) -> None:
    super().__init__()
    self.FSM_map: dict[str, FSM] = {}

  def build(self, node: "Module", context: "ParserContext") -> dict[str, FSM]:
    return self.build_fsms(node, context)

  def build_fsms(self, node: "Module", context: "ParserContext") -> dict[str, FSM]:
    self.FSM_map.clear()
    self.visit(node, context)
    return self.FSM_map

  def visit_Module(self, node: "Module", context: "ParserContext") -> None:
    for definition in node.definitions.values():
      self.visit(definition, context)

  def visit_Struct(
    self,
    struct: "Struct",
    context: "ParserContext",
  ) -> "FSM":
    from copy import deepcopy

    struct = deepcopy(struct)
    fsm = FSM(struct.name, parser_context=context, fsm_kind=FSMKind.Normal)
    fsm.fsm_params = struct.parameters
    self.FSM_map[struct.name] = fsm
    constraint_expr = None
    for param_constraint in struct.parameter_constraints:
      from src.parse3d import LogicalExpr, CmpExpr, ParenExpr, Tok3D, Tok3DType

      if not isinstance(param_constraint.expr, (LogicalExpr, CmpExpr, ParenExpr)):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError("Expect (LogicalExpr, CmpExpr, ParenExpr)")
      if constraint_expr is None:
        constraint_expr = param_constraint.expr
      else:
        constraint_expr = LogicalExpr(
          Tok3D(
            Tok3DType.LOGOP,
            "&&",
            param_constraint.expr.line,
            param_constraint.expr.col,
          ),
          constraint_expr,
          param_constraint.expr,
        )
    is_first_list = True
    for f in struct.fields:
      expect_list = self.visit_FieldDecl(f, context)
      if not isinstance(expect_list, list):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError("Expected a list of Node or FSM")
      if constraint_expr is not None and is_first_list:
        # make the fsm transition to the first expect_list with the constraint
        for node_or_fsm in expect_list:
          for exit in fsm.exits:
            if isinstance(exit, Node):
              exit.add_transition(constraint_expr, node_or_fsm)
            else:
              todo("Add constraint to FSM transition")
        fsm.exits = expect_list
      else:
        fsm.addlists(expect_list)
      is_first_list = False
    for key, value in context.defined_structs.items():
      if value.name == struct.name:
        self.FSM_map[key] = fsm
        fsm_renamed = deepcopy(fsm)
        fsm_renamed.name = key
        self.FSM_map[key] = fsm_renamed
    return fsm

  def visit_CaseType(
    self,
    casetype: "CaseType",
    context: "ParserContext",
  ) -> FSM:
    from src.parse3d import (
      LogicalExpr,
      CmpExpr,
      ParenExpr,
    )

    fsm = FSM(casetype.name, parser_context=context, fsm_kind=FSMKind.Normal)
    fsm.fsm_params = casetype.case_variables
    self.FSM_map[casetype.name] = fsm
    for key, value in context.defined_casetypes.items():
      if value.name == casetype.name:
        self.FSM_map[key] = fsm

    for case in casetype.cases:
      case_branch = casetype.cases[case]
      expect_fsm = self.visit_CaseBranch(case_branch, context)
      from src.parse3d import Parse3D

      text = f"{casetype.switch_var.name.val} == {case}"
      parser = Parse3D(text)
      expr_ast: (
        LogicalExpr
        | CmpExpr
        | ArithExpr
        | IntLiteral
        | Ident
        | FunctionCall
        | ParenExpr
      ) = parser.handle_logical_expr()
      if not isinstance(expr_ast, (LogicalExpr, CmpExpr, ParenExpr)):
        raise ValueError("Expect (LogicalExpr, CmpExpr, ParenExpr)")
      from src.parse3d import LogicalExpr, CmpExpr, ParenExpr, Tok3D, Tok3DType

      for param_constraint in casetype.parameter_constraints:
        if not isinstance(param_constraint.expr, (LogicalExpr, CmpExpr, ParenExpr)):  # pyright: ignore[reportUnnecessaryIsInstance]
          raise ValueError("Expect (LogicalExpr, CmpExpr, ParenExpr)")
        expr_ast = LogicalExpr(
          Tok3D(
            Tok3DType.LOGOP,
            "&&",
            param_constraint.expr.line,
            param_constraint.expr.col,
          ),
          expr_ast,
          param_constraint.expr,
        )
      if case_branch.field.constraint is not None:
        expr_ast = LogicalExpr(
          Tok3D(
            Tok3DType.LOGOP,
            "&&",
            case_branch.field.constraint.expr.line,
            case_branch.field.constraint.expr.col,
          ),
          expr_ast,
          case_branch.field.constraint.expr,
        )
      fsm.entry.add_transition(expr_ast, expect_fsm)
    return fsm

  def visit_CaseBranch(
    self, case_branch: "CaseBranch", context: "ParserContext"
  ) -> "FSM":
    from copy import deepcopy
    from src.parse3d import (
      StructNameType,
      StructType,
      PrimitiveType,
      ArrayType,
      EmptyType,
    )

    match case_branch.field.typ:
      case EmptyType():
        fsm = FSM("emptyFSM", parser_context=context, fsm_kind=FSMKind.Empty)
        return fsm
      case StructType() as st:
        expect_fsm = self.visit_Struct(st.struct, context)
        if not isinstance(expect_fsm, FSM):  # pyright: ignore[reportUnnecessaryIsInstance]
          raise ValueError("Expected an FSM")
        expect_fsm.name = case_branch.field.name
        self.FSM_map[case_branch.field.name] = expect_fsm
        return expect_fsm
      case StructNameType() as snt:
        if snt.name not in self.FSM_map:
          raise ValueError(f"Undefined struct {snt.name}")
        from copy import deepcopy

        struct_fsm = deepcopy(self.FSM_map[snt.name])
        if len(snt.args) > 0:
          # first, verify the type parameters match
          if len(struct_fsm.fsm_params) != len(snt.args):
            raise ValueError(
              f"Number of type arguments {len(snt.args)} does not match number of struct parameters {len(struct_fsm.fsm_params)}"
            )
          # then, verify arguments are actually arithmetic expressions
          for arg in snt.args:
            from src.parse3d import (
              ArithExpr,
              IntLiteral,
              Ident,
              FunctionCall,
              ParenExpr,
            )

            if not isinstance(
              arg, (ArithExpr, IntLiteral, Ident, FunctionCall, ParenExpr)
            ):
              raise ValueError(
                f"Struct type argument must be arithmetic expression, got {type(arg)}"
              )
          struct_fsm.fsm_args = snt.args
        return struct_fsm
      case PrimitiveType() as pt:
        expect_list = self.visit_FieldDecl(case_branch.field, context)
        if not isinstance(expect_list, list):  # pyright: ignore[reportUnnecessaryIsInstance]
          raise ValueError("Expected a list of Node or FSM")
        if len(expect_list) != 1:
          raise ValueError(
            f"Primitive type should result in exactly one Node, got {expect_list}"
          )
        expect_node = expect_list[0]
        if not isinstance(expect_node, Node):
          raise ValueError(f"PrimitiveType should result a Node, got {expect_node}")
        fsm = FSM(f"FSM_{pt.name}", parser_context=context, fsm_kind=FSMKind.Normal)
        fsm.entry.add_transition(None, expect_node)
        fsm.exits = [expect_node]
        return fsm
      case ArrayType() as at:
        expect_list = self.visit_FieldDecl(case_branch.field, context)
        if not isinstance(expect_list, list):  # pyright: ignore[reportUnnecessaryIsInstance]
          raise ValueError("Expected a list of Node or FSM")
        fsm = FSM(f"FSM_{at.name}", parser_context=context, fsm_kind=FSMKind.Normal)
        if len(expect_list) == 1:
          fsm.entry.add_transition(None, expect_list[0])
          fsm.exits = [expect_list[0]]
        else:
          fsm.addlists(expect_list)
          fsm.entry.add_transition(None, expect_list[0])
          fsm.exits = [expect_list[-1]]
        return fsm
      case _:
        raise ValueError(f"Unsupported type in CaseBranch: {case_branch.field.typ}")

  def visit_FieldDecl(
    self, field_decl: "FieldDecl", context: "ParserContext"
  ) -> "list[Node | FSM]":
    from src.parse3d.ast import StructNameType, PrimitiveType, ArrayType, EmptyType
    from src.tool import (
      bits_complete_for_type,
    )

    match field_decl.typ:
      case EmptyType():
        return [
          FSM(
            "emptyFSM",
            parser_context=context,
            fsm_kind=FSMKind.Normal
            if field_decl.constraint is not None
            else FSMKind.Empty,
            size=field_decl.constraint.__str__()
            if field_decl.constraint is not None
            else None,
            size_expr_ast=field_decl.constraint.expr if field_decl.constraint else None,
          )
        ]
      case PrimitiveType() as pt:
        return [
          Node(
            name=field_decl.name,
            parser_context=context,
            kind=NodeKind.Normal,
            type_expr=pt,
            condition_str=field_decl.constraint.__str__()
            if field_decl.constraint is not None
            else None,
            _condition_ast=field_decl.constraint.expr
            if field_decl.constraint
            else None,
          )
        ]
      case StructNameType() as snt:
        if snt.name not in self.FSM_map:
          raise ValueError(f"Undefined struct {snt.name}")
        from copy import deepcopy

        casetype = context.defined_casetypes.get(snt.name, None)
        struct = context.defined_structs.get(snt.name, None)
        if casetype is None and struct is None:
          raise ValueError(f"Undefined Struct or CaseType {snt.name}")
        elif casetype is None and struct is not None:
          struct_fsm = deepcopy(self.FSM_map[snt.name])
          if len(snt.args) > 0:
            # first, verify the type parameters match
            if len(struct_fsm.fsm_params) != len(struct.parameters):
              raise ValueError(
                f"Number of type arguments {len(snt.args)} does not match number of struct parameters {len(struct.parameters)}"
              )
            # then, verify arguments are actually arithmetic expressions
            for arg in snt.args:
              from src.parse3d import (
                ArithExpr,
                IntLiteral,
                Ident,
                FunctionCall,
                ParenExpr,
              )

              if not isinstance(
                arg, (ArithExpr, IntLiteral, Ident, FunctionCall, ParenExpr)
              ):
                raise ValueError(
                  f"Struct type argument must be arithmetic expression, got {type(arg)}"
                )
            struct_fsm.fsm_args = snt.args
          return [struct_fsm]
        elif casetype is not None:
          args = snt.args
          case_fsm = deepcopy(self.FSM_map[snt.name])
          if len(args) > 0:
            # first, verify the type parameters match
            if len(case_fsm.fsm_params) != len(casetype.case_variables):
              raise ValueError(
                f"Number of type arguments {len(args)} does not match number of casetype parameters {len(casetype.case_variables)}"
              )
            # then, verify arguments are actually arithmetic expressions
            for arg in args:
              from src.parse3d import (
                ArithExpr,
                IntLiteral,
                Ident,
                FunctionCall,
                ParenExpr,
              )

              if not isinstance(
                arg, (ArithExpr, IntLiteral, Ident, FunctionCall, ParenExpr)
              ):
                raise ValueError(
                  f"CaseType type argument must be arithmetic expression, got {type(arg)}"
                )
            case_fsm.fsm_args = args
          return [case_fsm]
        else:
          todo("Other cases in StructNameType in FieldDecl")
      case ArrayType() as at:
        array_name = field_decl.name
        array_type: TypeExpr = at
        array_size = at.size
        array_size_str = array_size.__str__()
        if array_size_str.isdigit():
          if isinstance(array_type.elem_type, PrimitiveType):
            return [
              Node(
                array_name,
                context,
                NodeKind.Normal,
                array_type,
              )
            ]
          else:
            assert isinstance(array_type.elem_type, StructNameType), (
              f"Array of non-primitive type must be StructNameType currently, got {array_type}"
            )
            if array_type.elem_type.name not in self.FSM_map:
              raise ValueError(f"Undefined struct {array_type.elem_type.name}")
            from copy import deepcopy

            struct_fsm = deepcopy(self.FSM_map[array_type.elem_type.name])
            struct_fsm.size_expr = f"{array_size_str} == sizeof({array_type.elem_type.name})"  # since it is byte-size, should not multiply elem size again
            empty_fsm = FSM(
              f"emptyFSM_{array_type.elem_type.name}",
              parser_context=context,
              fsm_kind=FSMKind.Empty,
            )
            empty_fsm.size_expr = f"{array_size_str}"
            return [
              empty_fsm,
              struct_fsm,
            ]
        if "sizeof(this)" in array_size_str:
          if isinstance(array_type.elem_type, PrimitiveType):
            return [
              Node(
                array_name,
                context,
                NodeKind.Normal,
                array_type,
                array_size_str,
                array_size,
              )
            ]
          else:
            assert isinstance(array_type.elem_type, StructNameType), (
              f"Array of non-primitive type must be StructNameType currently, got {array_type}"
            )
            if array_type.elem_type.name not in self.FSM_map:
              raise ValueError(f"Undefined struct {array_type.elem_type.name}")
            from copy import deepcopy

            struct_fsm = deepcopy(self.FSM_map[array_type.elem_type.name])
            struct_fsm.size_expr = f"{array_size_str} == sizeof({array_type.elem_type.name})"  # since it is byte-size, should not multiply elem size again
            empty_fsm = FSM(
              f"emptyFSM_{array_type.elem_type.name}",
              parser_context=context,
              fsm_kind=FSMKind.Empty,
            )
            empty_fsm.size_expr = f"{array_size_str}"
            return [
              empty_fsm,
              struct_fsm,
            ]
        else:
          needed_condition_str_empty = f"{array_size_str} == 0"
          from src.parse3d import Parse3D

          p = Parse3D(needed_condition_str_empty)
          needed_condition_ast = p.handle_logical_expr()
          if isinstance(array_type.elem_type, PrimitiveType):
            return [
              Node(
                name="empty",
                parser_context=context,
                kind=NodeKind.Empty,
                condition_str=needed_condition_str_empty,
                _condition_ast=needed_condition_ast,
              ),
              Node(
                name=array_name,
                parser_context=context,
                kind=NodeKind.Normal,
                type_expr=at,
                condition_str=field_decl.constraint.__str__(),
                _condition_ast=field_decl.constraint.expr
                if field_decl.constraint
                else None,
              ),
            ]
          else:
            assert isinstance(array_type.elem_type, StructNameType), (
              f"Array of non-primitive type must be StructNameType currently, got {array_type}"
            )
            if array_type.elem_type.name not in self.FSM_map:
              raise ValueError(f"Undefined struct {array_type.elem_type.name}")
            from copy import deepcopy

            struct_fsm = deepcopy(self.FSM_map[array_type.elem_type.name])
            struct_fsm.size_expr = f"{array_size_str} == sizeof({array_type.elem_type.name})"  # since it is byte-size, should not multiply elem size again
            empty_fsm = FSM(
              f"emptyFSM_{array_type.elem_type.name}",
              parser_context=context,
              fsm_kind=FSMKind.Empty,
            )
            empty_fsm.size_expr = f"{array_size_str}"
            return [
              empty_fsm,
              struct_fsm,
            ]
      case _:
        raise ValueError(f"Unsupported type in FieldDecl: {field_decl.typ}")


@deprecated("Use src/fsm/fsm_new.py instead")
class PathNodeKind(Enum):
  NODE_W_CONDITION = 0
  NODE_WO_CONDITION = 1
  FSM_START = 2
  FSM_END = 3
  CONDITION = 4


class PathNode:
  def __init__(
    self,
    kind: "PathNodeKind",
    node: "Node | None" = None,
    fsm: "FSM | None" = None,
    condition_str: "str | None" = None,
  ):
    self.kind: "PathNodeKind" = kind
    self.node: "Node | None" = node
    self.fsm: "FSM | None" = fsm
    self.condition_str: "str | None" = condition_str
    self._condition_ast: "Expr | None" = None
    from src.parse3d import Parse3D

    self.parser: "Parse3D" = Parse3D("")  # for later use if needed
    match self.kind:
      case PathNodeKind.NODE_W_CONDITION:
        assert self.node is not None and self.node.condition_str is not None
      case PathNodeKind.NODE_WO_CONDITION:
        assert self.node is not None and (
          self.node.condition_str is None or self.node.condition_str == "True"
        )
      case PathNodeKind.FSM_START | PathNodeKind.FSM_END:
        assert self.fsm is not None
      case PathNodeKind.CONDITION:
        assert self.condition_str is not None

  def bit_size(self) -> str:
    from src.parse3d import PrimitiveType, ArrayType

    if self.kind not in (
      PathNodeKind.NODE_W_CONDITION,
      PathNodeKind.NODE_WO_CONDITION,
    ):
      return "0"

    if self.node is None:
      raise ValueError("NODE_W_CONDITION and NODE_WO_CONDITION must have node")

    match self.node.type_expr:
      case None:
        return "0"
      case PrimitiveType() as pt:
        return str(pt.bits)
      case ArrayType() as at:
        match at.elem_type:
          case PrimitiveType() as pet:
            if pet.bits not in (8, 16, 32, 64):
              todo("bit_size for non-byte-aligned primitive types")
            return f"(({at.size}) * {pet.bits})"
          case _:
            todo("bit_size for non-primitive array element types")
      case _:
        todo("bit_size for non-primitive, non-array types")

  @property
  def condition_ast(self) -> "Expr | None":
    if self.kind in (PathNodeKind.NODE_W_CONDITION, PathNodeKind.NODE_WO_CONDITION):
      if self._condition_ast is None:
        self._condition_ast = self.node.condition_ast  # pyright: ignore[reportOptionalMemberAccess]
    elif self.kind == PathNodeKind.CONDITION:
      if self.node is not None:
        raise ValueError("CONDITION PathNode should not have node")
      if self._condition_ast is None:
        self.parser.change_text(self.condition_str)  # pyright: ignore[reportArgumentType]
        self._condition_ast = self.parser.handle_logical_expr()
    else:
      raise ValueError("FSM_START and FSM_END do not have condition_ast")
    return self._condition_ast

  @override
  def __repr__(self) -> str:
    match self.kind:
      case PathNodeKind.NODE_W_CONDITION:
        return f"Node({self.node.name}, type={self.node.type_expr}, condition={self.node.condition_str})"  # pyright: ignore[reportOptionalMemberAccess]
      case PathNodeKind.NODE_WO_CONDITION:
        return f"Node({self.node.name}, type={self.node.type_expr})"  # pyright: ignore[reportOptionalMemberAccess]
      case PathNodeKind.FSM_START:
        return f"FSM_START({self.fsm.name}){f': {self.fsm.size_expr}' if self.fsm.size_expr else ''}"  # pyright: ignore[reportOptionalMemberAccess]
      case PathNodeKind.FSM_END:
        return f"FSM_END({self.fsm.name})"  # pyright: ignore[reportOptionalMemberAccess]
      case PathNodeKind.CONDITION:
        return (
          f"[{self.condition_str}]"
          if (self.condition_str is not None and self.condition_str != "True")
          else ""
        )


@deprecated("Use src/fsm/fsm_new.py instead")
class Path:
  def __init__(self, nodes: "list[PathNode]"):
    self.nodes: list[PathNode] = nodes
    self._bit_size: str | None = None
    self._bit_size_map: dict[str, str] | None = (
      None  # map from FSM name to its bit size expression, we want this to handle the calling to `sizeof`, which could only be calculated deterministically when there is one path.
    )

  def copy(self) -> "Path":
    return Path(self.nodes.copy())

  @property
  def name(self) -> str:
    if not self.nodes:
      raise ValueError("Path has no nodes")
    first_node = self.nodes[0]
    if first_node.kind == PathNodeKind.FSM_START and first_node.fsm is not None:
      return first_node.fsm.name
    raise ValueError("First node is not FSM_START")

  @override
  def __repr__(self) -> str:
    return " -> ".join(filter(None, map(str, self.nodes)))

  @override
  def __str__(self) -> str:
    return self.__repr__()

  @override
  def __hash__(self) -> int:
    return hash(tuple(self.nodes))

  def add_node(self, node: PathNode) -> None:
    self.nodes.append(node)

  def add_nodes(self, nodes: "list[PathNode]") -> None:
    self.nodes.extend(nodes)

  def renamed_copy(self) -> "Path":
    fsm_stack: list[tuple[str, list[FieldDecl]]] = []
    fsm_appear_times: dict[str, int] = {}
    renamed_path = Path(nodes=[])
    from copy import deepcopy, copy

    # first copy the path to renamed_path
    for pn in self.nodes:
      renamed_path.add_node(
        PathNode(
          pn.kind,
          Node(
            deepcopy(pn.node.name),
            pn.node.parser_context,
            pn.node.kind,
            deepcopy(pn.node.type_expr),
            deepcopy(pn.node.condition_str),
            deepcopy(pn.node.condition_ast),
          )
          if pn.node is not None
          else None,
          copy(pn.fsm),
          deepcopy(pn.condition_str),
        )
      )

    last_is_fsm_start = False
    last_fsm = None

    for pn in renamed_path.nodes:
      match pn.kind:
        case PathNodeKind.FSM_START:
          if pn.fsm is None:
            raise ValueError("FSM_START must have fsm")
          if pn.fsm.fsm_kind == FSMKind.Empty:  # do nothing for empty FSM
            continue
          # if fsm_appear_times.get(pn.fsm.name, 0) > 0:
          #   pn.fsm.name = f"{pn.fsm.name}_{fsm_appear_times[pn.fsm.name]}"
          fsm_stack.append((deepcopy(pn.fsm.name), pn.fsm.fsm_params))
          pn.fsm.name = "_".join(map(lambda x: x[0], fsm_stack))
        case PathNodeKind.FSM_END:
          if not fsm_stack:
            raise ValueError("FSM_END without matching FSM_START")
          if pn.fsm is None:
            raise ValueError("FSM_END must have fsm")
          if pn.fsm.fsm_kind == FSMKind.Empty:  # do nothing for empty FSM
            continue
          # fsm_appear_times[pn.fsm.name] = fsm_appear_times.get(pn.fsm.name, 0) + 1
          pn.fsm.name = "_".join(map(lambda x: x[0], fsm_stack))
          _ = fsm_stack.pop()
        case PathNodeKind.NODE_W_CONDITION | PathNodeKind.NODE_WO_CONDITION:
          if not fsm_stack:
            raise ValueError("Node or Condition outside of any FSM")
          if pn.node is not None:
            pn.node.name = "_".join(map(lambda x: x[0], fsm_stack)) + "_" + pn.node.name
            # we want to rename the node's condition_str as well
            condition_str = pn.node.condition_str or "True"
            prefix = "_".join(map(lambda x: x[0], fsm_stack)) + "_"
            from src.parse3d import ExprRenamer, Parse3D

            parser = Parse3D(condition_str)
            condition_ast = parser.handle_logical_expr()
            renamer = ExprRenamer(prefix)
            renamed_condition_ast = renamer.rename(condition_ast, parser.context)
            pn.node.condition_ast = renamed_condition_ast

            # want to also rename node's type_expr
            if pn.node.type_expr is not None:
              type_expr = pn.node.type_expr

              from src.parse3d import (
                ArrayType,
                Ident,
                ArithExpr,
                IntLiteral,
                FunctionCall,
                ParenExpr,
              )

              match type_expr:
                case ArrayType() as at:
                  elem_size = at.size
                  elem_size_renamed = renamer.rename(elem_size, parser.context)
                  if not isinstance(
                    elem_size_renamed,
                    (IntLiteral, Ident, ArithExpr, FunctionCall, ParenExpr),
                  ):
                    raise ValueError(
                      f"Renamed array size must be arithmetic expression, got {type(elem_size_renamed)}"
                    )
                  at.size = elem_size_renamed
                  pn.node.type_expr = at
                case _:
                  # do nothing for other types for now
                  ...

        case PathNodeKind.CONDITION:  # rename the condition node
          condition_str = pn.condition_str or "True"
          prefix = "_".join(map(lambda x: x[0], fsm_stack)) + "_"
          # rename the existing condition_str first
          from src.parse3d import Parse3D, ExprRenamer

          if condition_str != "True":
            parser = Parse3D(condition_str)
            condition_ast = parser.handle_logical_expr()
            renamer = ExprRenamer(prefix)
            renamed_condition_ast = renamer.rename(condition_ast, parser.context)
            condition_str = renamed_condition_ast.__str__()
          if last_is_fsm_start:  # want to add the param equals args constraints, if any, if only one FSM in stack, it is impossible to have param equals args constraints
            if last_fsm is None:
              raise ValueError("last_fsm is None when last_is_fsm_start is True")
            prefix_lower_one_layer = "_".join(map(lambda x: x[0], fsm_stack[:-1])) + "_"
            if len(fsm_stack) < 1:
              raise ValueError("fsm_stack has less than 1 element")
            from src.parse3d import (
              CmpExpr,
              Tok3D,
              Tok3DType,
              ExprRenamer,
              TypeExpr,
              ParserContext,
              Ident,
              LogicalExpr,
            )

            args: Sequence[
              ArithExpr
              | IntLiteral
              | Ident
              | LogicalExpr
              | CmpExpr
              | FunctionCall
              | ParenExpr
              | TypeExpr
            ] = last_fsm.fsm_args
            if len(args) > 0:
              # now make the constraints
              bind_constraints: list[
                ArithExpr
                | IntLiteral
                | Ident
                | LogicalExpr
                | CmpExpr
                | FunctionCall
                | ParenExpr
              ] = []
              for param, arg in zip(last_fsm.fsm_params, args):
                # since params can be not in the last fsm, we need to first find the correct fsm, then rename using the correct prefix
                fsm_at_idx = len(fsm_stack) - 1
                path_nodes = list(map(lambda x: x[1], fsm_stack))
                while fsm_at_idx >= 0:
                  if param.name in map(
                    lambda x: x.name,
                    path_nodes[fsm_at_idx],
                  ):
                    break
                  fsm_at_idx -= 1
                if fsm_at_idx < 0:
                  raise ValueError(
                    f"Parameter {param.name} not found in any FSM in stack"
                  )
                prefix = (
                  "_".join(map(lambda x: x[0], fsm_stack[: fsm_at_idx + 1])) + "_"
                )
                if isinstance(arg, TypeExpr):
                  raise ValueError("TypeExpr not supported in FSM args for now")
                arg_renamed = ExprRenamer(prefix_lower_one_layer).rename(
                  deepcopy(arg), ParserContext()
                )

                bind_constraint = CmpExpr(
                  Tok3D(
                    Tok3DType.CMPOP,
                    "==",
                    arg.line,
                    arg.col,
                  ),
                  Ident(
                    Tok3D(
                      Tok3DType.IDENT,
                      prefix + param.name,
                      arg.line,
                      arg.col,
                    )
                  ),
                  arg_renamed,
                )
                bind_constraints.append(bind_constraint)

              if last_fsm.parser_context is None:
                raise ValueError("last_fsm.parser_context is None")

              potential_casetype = last_fsm.parser_context.defined_casetypes.get(
                last_fsm.name, None
              )
              if potential_casetype is not None:
                # we make a variable for each case branch to cover all possibilities
                for case in potential_casetype.cases:
                  case_branch = potential_casetype.cases[case]
                  prefix_for_branch = (
                    ("_".join(map(lambda x: x[0], fsm_stack)) + "_")
                    + (
                      case_branch.field.typ.name
                      if not case_branch.field.typ.name.startswith("<")
                      else case_branch.field.name
                    )
                    + "_"
                  )
                  for param in last_fsm.fsm_params:
                    bind_constraint = CmpExpr(
                      Tok3D(
                        Tok3DType.CMPOP,
                        "==",
                        param.line,
                        param.col,
                      ),
                      Ident(
                        Tok3D(
                          Tok3DType.IDENT,
                          prefix_for_branch + param.name,
                          param.line,
                          param.col,
                        )
                      ),
                      Ident(
                        Tok3D(
                          Tok3DType.IDENT,
                          prefix + param.name,
                          param.line,
                          param.col,
                        )
                      ),
                    )
                    bind_constraints.append(bind_constraint)

              from functools import reduce

              binded_constraint_ast = reduce(
                lambda a, b: LogicalExpr(
                  Tok3D(
                    Tok3DType.LOGOP,
                    "&&",
                    b.line,
                    b.col,
                  ),
                  a,
                  b,
                ),
                bind_constraints,
              )

              # combine the two condition ast
              condition_str = (
                f"({condition_str}) && ({binded_constraint_ast.__str__()})"
              )
          pn.condition_str = condition_str

          parser = Parse3D(condition_str)
          condition_ast = parser.handle_logical_expr()
          pn._condition_ast = condition_ast  # pyright: ignore[reportPrivateUsage]

      last_is_fsm_start = pn.kind == PathNodeKind.FSM_START
      if last_is_fsm_start:
        last_fsm = copy(pn.fsm)
        if last_fsm is not None:
          last_fsm.name = fsm_stack[-1][0]
      else:
        last_fsm = None
    return renamed_path

  @property
  def bit_size_map(self) -> "dict[str, str]":
    if self._bit_size_map is None:
      self._bit_size_map = {}
      fsm_stack: list[tuple[str, int]] = []
      current_bit_expr = "0"
      current_bit_number = 0
      for pn in self.nodes:
        match pn.kind:
          case PathNodeKind.NODE_W_CONDITION | PathNodeKind.NODE_WO_CONDITION:
            bit_size = pn.bit_size()
            if bit_size.isdigit():
              current_bit_number += int(bit_size)
            else:
              if current_bit_number % 8 != 0:
                raise ValueError(
                  f"bit size must be byte-aligned: {pn.node.name if pn.node is not None else ''}"
                )
              if current_bit_number > 0:
                if current_bit_expr == "0":
                  current_bit_expr = str(current_bit_number)
                else:
                  current_bit_expr = f"({current_bit_expr} + {current_bit_number})"
              if current_bit_expr == "0":
                current_bit_expr = bit_size
              else:
                current_bit_expr = f"({current_bit_expr} + {bit_size})"
              current_bit_number = 0
          case PathNodeKind.FSM_START:
            fsm_stack.append((current_bit_expr, current_bit_number))
            current_bit_expr = "0"
            current_bit_number = 0
          case PathNodeKind.FSM_END:
            if not fsm_stack:
              raise ValueError("FSM_END without matching FSM_START")
            if pn.fsm is None:
              raise ValueError("FSM_END must have fsm")
            fsm_name = pn.fsm.name
            if current_bit_number % 8 != 0:
              raise ValueError("bit size must be byte-aligned")
            if current_bit_number > 0:
              if current_bit_expr == "0":
                current_bit_expr = str(current_bit_number)
              else:
                current_bit_expr = f"({current_bit_expr} + {current_bit_number})"
            prev_bit_expr, prev_bit_number = fsm_stack.pop()
            if fsm_name in self._bit_size_map:
              todo(
                f"handle multiple calls to the same FSM in one path, fsm_name: {fsm_name}, Path: {self}"
              )
            if pn.fsm.parser_context is None:
              raise ValueError("FSM must have parser_context")
            self._bit_size_map[fsm_name] = (
              current_bit_expr if current_bit_expr != "0" else str(current_bit_number)
            )
            for f_name, fsm in list(
              pn.fsm.parser_context.defined_structs.items()
            ) + list(pn.fsm.parser_context.defined_casetypes.items()):
              if f_name == fsm_name:
                self._bit_size_map[fsm.name] = self._bit_size_map[fsm_name]
              if fsm.name == fsm_name:
                self._bit_size_map[f_name] = self._bit_size_map[fsm_name]
            current_bit_expr = (
              f"({prev_bit_expr} + {current_bit_expr})"
              if prev_bit_expr != "0"
              else current_bit_expr
            )
            current_bit_number = prev_bit_number
          case PathNodeKind.CONDITION:
            pass

      import sympy as sp

      for fsm_name, bit_expr in self._bit_size_map.items():
        self._bit_size_map[fsm_name] = str(sp.simplify(sp.sympify(bit_expr)))  # pyright: ignore[reportUnknownMemberType]

    return self._bit_size_map
