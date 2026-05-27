from __future__ import annotations
from collections.abc import Generator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, final, override
from enum import Enum
from src.parse3d import Tok3D, Tok3DType, AstVisitor, FunctionCall, Ident
from src.parse3d import CmpExpr, IntLiteral
from src.tool import todo
from uuid import uuid4


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

  condition_ast_type = LogicalExpr | CmpExpr | ParenExpr


class FSMKind(Enum):
  Empty = 1
  Normal = 2
  Call = 3


class NodeKind(Enum):
  Normal = 0
  Start = 1
  Empty = 2


@dataclass
class FlowNode:
  """
  FSM -> FlowGraph -> Path

  Flow Node is nodes in flattened FSM, and should be able to be traversed using easy DFS/BFS, without handling nested FSMs.

  FlowNode should consists only of:
  1. Node.Normal that represents actual data fields, which could have conditions
  2. Node.Condition that represents conditions on transitions
  3. FSM.Start that represents the start of an FSM
  4. FSM.End that represents the end of an FSM
  """

  path_segments: list[PathNode] = field(default_factory=list)

  # For debugging
  name: str = "<anon>"

  @override
  def __hash__(self) -> int:
    return hash(id(self))


@dataclass
class FlowGraph:
  """
  A FlowGraph is a flattened representation of an FSM, with all nested FSMs expanded into nodes.
  It is used to generate Paths.
  """

  nodes: list[FlowNode] = field(default_factory=list)
  predecessors: dict[FlowNode, list[FlowNode]] = field(default_factory=dict)
  successors: dict[FlowNode, list[FlowNode]] = field(default_factory=dict)

  def biconnect(self, node1: FlowNode, node2: FlowNode) -> None:
    self.predecessors.setdefault(node2, []).append(node1)
    self.successors.setdefault(node1, []).append(node2)

  def get_out_degree_0_nodes(self) -> list[FlowNode]:
    return [node for node in self.nodes if len(self.successors.get(node, [])) == 0]

  def get_in_degree_0_nodes(self) -> list[FlowNode]:
    return [node for node in self.nodes if len(self.predecessors.get(node, [])) == 0]

  @override
  def __hash__(self) -> int:
    return id(self)

  @override
  def __repr__(self) -> str:
    # print the flow graph in a readable way
    repr_str = "FlowGraph:\n"
    for node in self.nodes:
      repr_str += f"  FlowNode({node.name}):\n"
      for succ in self.successors.get(node, []):
        repr_str += f"    -> FlowNode({succ.name})\n"
    return repr_str

  def make_node_ids(self):
    node_ids: dict[FlowNode, str] = {}
    for i, node in enumerate(self.nodes):
      node_id = f"node_{i}"
      node_ids[node] = node_id
    return node_ids

  def to_dot(self) -> str:
    # we want to make nodes with the same name unique in dot format
    dot_str = "digraph FlowGraph {\n"
    node_ids: dict[FlowNode, str] = self.make_node_ids()
    for node in self.nodes:
      node_id = node_ids[node]
      dot_str += f'  {node_id} [label="{node.name}"];\n'
    for node in self.nodes:
      for succ in self.successors.get(node, []):
        dot_str += f"  {node_ids[node]} -> {node_ids[succ]};\n"
    dot_str += "}\n"
    return dot_str


@dataclass
class Node:
  name: str
  parser_context: ParserContext
  kind: NodeKind = NodeKind.Normal
  type_expr: TypeExpr | None = None
  _condition_ast: condition_ast_type | None = None
  transitions: dict["Node | FSM", "LogicalExpr | CmpExpr | ParenExpr | None"] = field(
    default_factory=dict
  )

  @property
  def condition_ast(self) -> condition_ast_type | None:
    return self._condition_ast or FSM.dummy_true_condition  # always true

  @condition_ast.setter
  def condition_ast(self, value: condition_ast_type | None) -> None:
    self._condition_ast = value

  @property
  def condition_str(self) -> str:
    if self._condition_ast is None:
      return "1 == 1"  # always true
    return self.condition_ast.__str__()

  @property
  def tightened_condition_str(self) -> str:
    tightened_ast = self.tightened_condition_ast
    return tightened_ast.__str__()

  @property
  def tightened_condition_ast(self) -> condition_ast_type:
    from src.parse3d import CmpExpr, Tok3DType, IntLiteral, Tok3D

    if self._condition_ast is None:
      self._condition_ast = FSM.dummy_true_condition  # always true

    from src.parse3d.ast import PrimitiveType, ArrayType, LogicalExpr

    line = self._condition_ast.line
    col = self._condition_ast.col

    def add_bound_constraints(expr: condition_ast_type, bits_max: int):
      # add lower bound
      new_condition = LogicalExpr(
        left=expr,
        op=Tok3D(Tok3DType.LOGOP, "&&", line, col),
        right=CmpExpr(
          Tok3D(Tok3DType.CMPOP, ">=", line, col),
          Ident(
            Tok3D(
              Tok3DType.IDENT,
              self.name,
              line,
              col,
            )
          ),
          IntLiteral(Tok3D(Tok3DType.INT, "0", line, col)),
        ),
      )
      # add upper bound
      new_condition = LogicalExpr(
        op=Tok3D(Tok3DType.LOGOP, "&&", line, col),
        left=new_condition,
        right=CmpExpr(
          Tok3D(Tok3DType.CMPOP, "<=", line, col),
          Ident(
            Tok3D(
              Tok3DType.IDENT,
              self.name,
              line,
              col,
            )
          ),
          IntLiteral(
            Tok3D(
              Tok3DType.INT,
              str(bits_max),
              line,
              col,
            ),
          ),
        ),
      )
      return new_condition

    def a_and_b(a: condition_ast_type, b: condition_ast_type) -> LogicalExpr:
      return LogicalExpr(
        left=a,
        op=Tok3D(Tok3DType.LOGOP, "&&", line, col),
        right=b,
      )

    def length_constraint(
      array_size: ArithExpr | IntLiteral | Ident | FunctionCall | ParenExpr,
    ) -> CmpExpr:
      return CmpExpr(
        op=Tok3D(Tok3DType.CMPOP, "==", line, col),
        left=FunctionCall(
          Tok3D(Tok3DType.IDENT, "length_array", line, col),
          [Ident(Tok3D(Tok3DType.IDENT, self.name, line, col))],
        ),
        right=array_size,
      )

    def length_byte_size_constraint(
      array_size: ArithExpr | IntLiteral | Ident | FunctionCall | ParenExpr,
    ) -> CmpExpr:
      return CmpExpr(
        op=Tok3D(Tok3DType.CMPOP, "==", line, col),
        left=FunctionCall(
          Tok3D(Tok3DType.IDENT, "length_byte_size_array", line, col),
          [Ident(Tok3D(Tok3DType.IDENT, self.name, line, col))],
        ),
        right=array_size,
      )

    def size_mod_eq_zero_constraint(
      expr: ArithExpr | IntLiteral | Ident | FunctionCall | ParenExpr, mod: int
    ) -> CmpExpr:
      from src.parse3d import ArithExpr

      return CmpExpr(
        op=Tok3D(Tok3DType.CMPOP, "==", line, col),
        left=ArithExpr(
          left=expr,
          op=Tok3D(Tok3DType.ARITHOP, "%", line, col),
          right=IntLiteral(Tok3D(Tok3DType.INT, str(mod), line, col)),
        ),
        right=IntLiteral(Tok3D(Tok3DType.INT, "0", line, col)),
      )

    match self.type_expr:
      case None:
        return self._condition_ast
      case PrimitiveType() as pt:
        bits: int = pt.bits
        array_bits_max: int = 2**bits - 1  # pyright: ignore[reportAny]
        # we can tighten the condition by adding upper bound checks and lower bound checks
        return add_bound_constraints(self._condition_ast, array_bits_max)
      case (
        ArrayType() as at
      ):  # Handle array as a very large UINT, the constraint should be the whole array treated as a number's bit_max
        array_size = at.size
        is_byte_size = at.is_byte_size
        arith_result = None
        arith_result_str_if_digit = array_size.__str__()
        try:
          # try to evaluate the array size expression into integer
          arith_result = eval(array_size.__str__())  # pyright: ignore[reportAny]
        except Exception:
          arith_result = None
        if arith_result is not None and isinstance(arith_result, int):
          # fixed size array
          arith_result_str_if_digit = str(arith_result)
        if is_byte_size and arith_result_str_if_digit.isdigit():
          # No need to consider array length, can just handle as primitive type
          bits = int(arith_result_str_if_digit) * 8
          array_bits_max = 2**bits - 1  # pyright: ignore[reportAny]
          # we can tighten the condition by adding upper bound checks and lower bound checks
          return add_bound_constraints(self._condition_ast, array_bits_max)
        elif is_byte_size:
          return a_and_b(
            length_byte_size_constraint(array_size),
            a_and_b(
              self._condition_ast,
              size_mod_eq_zero_constraint(
                array_size, int(at.elem_type.name[4:-2]) // 8
              ),
            ),
          )
        else:
          return a_and_b(
            length_constraint(array_size),
            self._condition_ast,
          )
      case _:
        return self._condition_ast

  @override
  def __repr__(self) -> str:
    match self.kind:
      case NodeKind.Normal:
        return (
          f"Node({self.name}, type={self.type_expr}, condition=({self.condition_str}))"
        )
      case NodeKind.Start:
        return f"Node({self.name})"
      case NodeKind.Empty:
        return f"[{self.condition_str}]"

  @override
  def __str__(self) -> str:
    return self.__repr__()

  @override
  def __hash__(self) -> int:
    return hash((self.name, id(self)))

  def add_transition(self, condition: condition_ast_type | None, target: Node | FSM):
    if target is self:
      raise ValueError("Self-loop transitions are not supported yet")
    self.transitions[target] = condition


@final
class FSM:
  dummy_true_condition: ClassVar[condition_ast_type] = CmpExpr(
    op=Tok3D(Tok3DType.CMPOP, "==", 0, 0),
    left=IntLiteral(Tok3D(Tok3DType.INT, "1", 0, 0)),
    right=IntLiteral(Tok3D(Tok3DType.INT, "1", 0, 0)),
  )  # a static always true condition AST

  @override
  def __hash__(self) -> int:
    return hash((self.name, id(self)))

  def __init__(
    self,
    name: str,
    parser_context: ParserContext,
    size_expr: Expr | None = None,
    kind: FSMKind = FSMKind.Normal,
    fsm_params: list[FieldDecl] | None = None,
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
    fsm_size_expr: Expr | None = None,
    call_fsm: FSM | None = None,
  ):
    self.name = name
    self.parser_context = parser_context
    self.size_expr = size_expr
    self.kind = kind
    self.fsm_params = fsm_params or []

    self.entry: Node = Node(
      name="start",
      parser_context=parser_context,
      kind=NodeKind.Start,
    )
    self.exits: list[Node | FSM] = [self.entry]
    self.nexts: list[Node | FSM] = []
    # for CallFSM nodes
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
    self.fsm_size_expr: Expr | None = fsm_size_expr
    self.call_fsm: FSM | None = call_fsm
    self._flow_graph: FlowGraph | None = None

  def addNext(self, next: Node | FSM) -> None:
    self.nexts.append(next)

  def addNexts(self, nexts: list[Node | FSM]) -> None:
    self.nexts.extend(nexts)

  def addlists(self, node_or_FSM_list: list[Node | FSM] | None) -> None:
    if node_or_FSM_list is None:
      return

    for node_or_FSM in node_or_FSM_list:
      for exit in self.exits:
        match exit:
          case Node() as exit_node:
            exit_node.add_transition(None, node_or_FSM)
          case FSM() as exit_fsm:
            exit_fsm.addNext(node_or_FSM)
    self.exits = node_or_FSM_list

  def into_flowgraph(self) -> "FlowGraph":
    """
    Convert the FSM into a FlowGraph by expanding all nested FSMs.
    """
    flowgraph = FlowGraph()
    _ = self._build_flowgraph(self, {}, flowgraph)
    _ = self._remove_start_nodes(flowgraph)
    # self._check_flow_graph(flowgraph)
    return flowgraph

  def _check_flow_graph(self, flow_graph: FlowGraph):  # pyright: ignore[reportUnusedFunction]
    """
    Check that flow_graph must contain one node of zero indegree and one node of zero outdegree.
    """
    indegree_0_nodes = [
      node
      for node in flow_graph.nodes
      if len(flow_graph.predecessors.get(node, [])) == 0
    ]
    outdegree_0_nodes = flow_graph.get_out_degree_0_nodes()
    if len(indegree_0_nodes) != 1:
      raise ValueError(
        f"Flow graph must contain exactly one node of zero indegree, found {len(indegree_0_nodes)}, which is {indegree_0_nodes}"
      )
    if len(outdegree_0_nodes) != 1:
      raise ValueError(
        f"Flow graph must contain exactly one node of zero outdegree, found {len(outdegree_0_nodes)}"
      )

  def _remove_start_nodes(self, flow_graph: FlowGraph) -> None:
    """
    Remove redundant start nodes from the flow graph.
    A redundant start node is defined as a FlowNode that does not contain any path segment.
    """
    removes: set[int] = set()
    for idx, node in enumerate(flow_graph.nodes):
      if len(node.path_segments) == 0:
        # remove this node by connecting its predecessors to its successors
        predecessors = flow_graph.predecessors.get(node, [])
        successors = flow_graph.successors.get(node, [])
        for pred in predecessors:
          flow_graph.successors[pred] = []
          for succ in successors:
            flow_graph.biconnect(pred, succ)
        # remove the node from the graph
        removes.add(idx)
    flow_graph.nodes = [
      node for idx, node in enumerate(flow_graph.nodes) if idx not in removes
    ]

  def _build_flowgraph(
    self,
    current: Node | FSM,
    visited: dict[Node | FSM, FlowNode],
    flow_graph: FlowGraph,
    father: FlowNode | None = None,
    fsm_end: FlowNode | None = None,
  ) -> list["FlowNode"]:
    """
    1. modify flow_graph in place by adding nodes and edges
    2. when ends, return the last FlowNode created, so that father can connect to it
    """
    should_terminate = current in self.exits
    if current in visited:
      current_flow_node = visited[current]
      if father is not None:
        flow_graph.biconnect(father, current_flow_node)
      return [current_flow_node]
    path_nodes = self._create_path_node(current)
    current_flow_node = FlowNode(name=f"{current.name}@{str(uuid4())[:4]}")
    visited[current] = current_flow_node
    current_flow_node.path_segments.extend(path_nodes)

    if father is not None:
      flow_graph.biconnect(father, current_flow_node)
    flow_graph.nodes.append(current_flow_node)

    if isinstance(current, Node) and not current.transitions and should_terminate:
      return [current_flow_node]
    if isinstance(current, Node):
      returns_node: list[FlowNode] = []
      for child, condition in current.transitions.items():
        if condition is None:
          condition_node = None
        else:
          condition_node = PathNode(
            PathNodeKind.CONDITION,
            node=Node(
              name="<dummy>",
              parser_context=self.parser_context,
              kind=NodeKind.Normal,
              _condition_ast=condition,
            ),
            fsm=None,
          )
        if condition_node is not None:
          condition_flow_node = FlowNode(
            name=f"[{condition_node.condition_ast.__str__()}]@{str(uuid4())[:8]}",
            path_segments=[],
          )
          condition_flow_node.path_segments.extend([condition_node])
          flow_graph.nodes.append(condition_flow_node)
          flow_graph.biconnect(current_flow_node, condition_flow_node)
        else:
          condition_flow_node = None
        fa = (
          condition_flow_node if condition_flow_node is not None else current_flow_node
        )
        returns_node.extend(
          self._build_flowgraph(child, visited, flow_graph, fa, fsm_end)
        )
      if not returns_node:
        returns_node.append(current_flow_node)
      return returns_node
    else:  # is FSM
      uid = str(uuid4())[:4]
      match current.kind:
        case FSMKind.Normal:
          current_flow_node.name = f"FSM_START({current.name})@{uid}"
          entry_returns = current._build_flowgraph(
            current.entry, {}, flow_graph, current_flow_node
          )  # use empty visited for nested FSMs
          fsm_end_node = FlowNode(name=f"FSM_END({current.name})@{uid}")
          fsm_end_node.path_segments.extend(
            [
              PathNode(
                kind=PathNodeKind.FSM_END,
                fsm=current,
                fsm_args=current.fsm_args,
              )
            ]
          )
          flow_graph.nodes.append(fsm_end_node)
          returns_normal: list[FlowNode] = []
          print(entry_returns)
          for entry_return in entry_returns:
            flow_graph.biconnect(entry_return, fsm_end_node)
          if not current.nexts:
            returns_normal.append(fsm_end_node)
          else:
            for child in current.nexts:
              returns_normal.extend(
                current._build_flowgraph(child, visited, flow_graph, fsm_end_node)
              )
          return returns_normal  # for outer layer's FSM maybe
        case FSMKind.Call:
          if current.call_fsm is None:
            raise ValueError("CallFSM must have a call_fsm")
          current_flow_node.name = f"FSM_START({current.call_fsm.name})@{uid}"
          entry_returns = current.call_fsm._build_flowgraph(
            current.call_fsm.entry, {}, flow_graph, current_flow_node
          )  # use empty visited for nested FSMs
          fsm_end_node = FlowNode(name=f"FSM_END({current.call_fsm.name})@{uid}")
          fsm_end_node.path_segments.extend(
            [
              PathNode(
                PathNodeKind.FSM_END,
                fsm=current.call_fsm,
                fsm_args=current.fsm_args,
              )
            ]
          )
          flow_graph.nodes.append(fsm_end_node)
          returns_call: list[FlowNode] = []
          for entry_return in entry_returns:
            flow_graph.biconnect(entry_return, fsm_end_node)
          if not current.call_fsm.nexts:
            if not current.nexts:
              returns_call.append(fsm_end_node)
            else:
              for child in current.nexts:
                returns_call.extend(
                  current._build_flowgraph(child, visited, flow_graph, fsm_end_node)
                )
          else:
            if not current.nexts:
              returns_call.append(fsm_end_node)
            else:
              for child in current.call_fsm.nexts:
                returns_call.extend(
                  current._build_flowgraph(child, visited, flow_graph, fsm_end_node)
                )
          return returns_call
        case FSMKind.Empty:
          entry_returns = current._build_flowgraph(
            current.entry, {}, flow_graph, current_flow_node
          )  # use empty visited for nested FSMs
          returns: list[FlowNode] = []
          if not current.nexts:
            returns.extend(entry_returns)
          else:
            for entry_return in entry_returns:
              for child in current.nexts:
                returns.extend(
                  self._build_flowgraph(child, visited, flow_graph, entry_return)
                )
          return returns

  def _create_path_node(self, current: Node | FSM) -> list[PathNode]:
    """
    Helper to generate the correct PathNode(s) representation for a current element.
    Refactored from the original dfs to reduce duplication.
    """
    if isinstance(current, Node):
      match current.kind:
        case NodeKind.Normal:
          kind = (
            PathNodeKind.NODE_WO_CONDITION
            if current.condition_ast is None
            or current.condition_ast is FSM.dummy_true_condition
            else PathNodeKind.NODE_W_CONDITION
          )
          return [PathNode(kind, node=current, fsm=None)]
        case NodeKind.Empty:
          if current.condition_ast is not None:
            # Empty nodes with conditions are treated as Conditions
            return [
              PathNode(
                PathNodeKind.CONDITION,
                node=Node(
                  name="<dummy>",
                  parser_context=self.parser_context,
                  kind=NodeKind.Normal,
                  _condition_ast=current.condition_ast,
                ),
                fsm=None,
              )
            ]
          # Pure empty node (no condition) -> emits nothing in the path
          return []
        case NodeKind.Start:
          return []  # Start node is implicit
    else:  # current is FSM
      match current.kind:
        case FSMKind.Empty:
          return [
            PathNode(
              PathNodeKind.CONDITION,
              fsm=current,
              node=Node(
                name="<dummy>",
                parser_context=self.parser_context,
                type_expr=None,
                kind=NodeKind.Normal,
                _condition_ast=current.size_expr  # pyright: ignore[reportArgumentType]
                if current.size_expr is not None
                else FSM.dummy_true_condition,
              ),
            )
          ]
        case FSMKind.Normal:
          nodes = [
            PathNode(PathNodeKind.FSM_START, fsm=current, fsm_args=current.fsm_args)
          ]
          if current.size_expr is not None:
            # Add size check condition
            nodes = [
              (
                PathNode(
                  PathNodeKind.CONDITION,
                  fsm=current,
                  node=Node(
                    name="<dummy>",
                    parser_context=self.parser_context,
                    type_expr=None,
                    kind=NodeKind.Normal,
                    _condition_ast=CmpExpr(
                      op=Tok3D(Tok3DType.CMPOP, "==", 0, 0),
                      left=current.size_expr,
                      right=FunctionCall(
                        Tok3D(Tok3DType.IDENT, "sizeof", 0, 0),
                        [Ident(Tok3D(Tok3DType.IDENT, "this", 0, 0))],
                      ),
                    ),
                  ),
                )
              )
            ] + nodes
          return nodes
        case FSMKind.Call:
          if current.call_fsm is None:
            raise ValueError("CallFSM must have a call_fsm")
          nodes = [
            PathNode(
              PathNodeKind.FSM_START,
              fsm=current.call_fsm,
              fsm_args=current.fsm_args,
            )
          ]
          if current.fsm_size_expr is not None:
            nodes.append(
              PathNode(
                PathNodeKind.CONDITION,
                fsm=current,
                node=Node(
                  name="<dummy>",
                  parser_context=self.parser_context,
                  type_expr=None,
                  kind=NodeKind.Normal,
                  _condition_ast=CmpExpr(
                    op=Tok3D(Tok3DType.CMPOP, "==", 0, 0),
                    left=current.fsm_size_expr,
                    right=FunctionCall(
                      Tok3D(Tok3DType.IDENT, "sizeof", 0, 0),
                      [Ident(Tok3D(Tok3DType.IDENT, "this", 0, 0))],
                    ),
                  ),
                ),
              )
            )
          return nodes

  def dfs_sparse(
    self,
    flow_graph: FlowGraph,
  ) -> Generator[
    Path, None, None
  ]:  # perform sparse DFS on the flow graph to generate paths
    """
    Perform sparse DFS on the flow graph to generate paths.
    Basically calculate a Path Cover. But we want all paths starting from the entry node to exit node. Start node and Exit node should only be one in the flow graph.
    """
    in_degree_0_nodes = flow_graph.get_in_degree_0_nodes()
    if len(in_degree_0_nodes) != 1:
      raise ValueError(
        f"Flow graph must contain exactly one node of zero indegree, found {len(in_degree_0_nodes)}, which is {in_degree_0_nodes}"
      )
    entry_node = in_degree_0_nodes[0]
    print(
      f"{len(flow_graph.nodes)} nodes in the flow graph. Starting DFS from {entry_node.name}"
    )
    visited: set[str] = set()
    yield from self._dfs_sparse_helper(
      entry_node,
      flow_graph,
      Path(),
      node_ids=flow_graph.make_node_ids(),
      path_visited=visited,
    )  # type: ignore[arg-type]
    # if len(visited) < len(flow_graph.nodes):
    #   todo(
    #     f"Not all nodes visited in sparse DFS. Visited {len(visited)}/{len(flow_graph.nodes)} nodes."
    #   )

  def _dfs_sparse_helper(
    self,
    current: FlowNode,
    flow_graph: FlowGraph,
    current_path: Path,
    path_visited: set[str] | None = None,
    global_visited: set[str] | None = None,
    node_ids: dict[FlowNode, str] | None = None,
  ) -> Generator[Path, None, None]:
    if path_visited is None:
      path_visited = set()
    if global_visited is None:
      global_visited = set()
    new_visited = path_visited.copy()
    node_ids = node_ids or {}
    current_node_id = node_ids[current]
    if current_node_id in new_visited:
      for path_segment in current.path_segments:
        current_path.add_node(path_segment)
      yield from self._dfs_sparse_pick_default_path(
        current, flow_graph, current_path.copy(), path_visited, node_ids
      )
    new_visited.add(current_node_id)
    global_visited.add(current_node_id)
    for path_segment in current.path_segments:
      current_path.add_node(path_segment)
    successors = flow_graph.successors.get(current, [])
    if not successors:
      yield current_path.copy()
      return

    fresh_successors: list[FlowNode] = []
    stale_successors: list[FlowNode] = []

    for succ in successors:
      succ_id = node_ids[succ]
      if succ_id in new_visited:
        continue
      if succ_id in global_visited:
        stale_successors.append(succ)
      else:
        fresh_successors.append(succ)

    if fresh_successors:
      for succ in fresh_successors:
        yield from self._dfs_sparse_helper(
          succ, flow_graph, current_path.copy(), new_visited, global_visited, node_ids
        )
    elif stale_successors:
      # pick the first stale successor to continue the path
      succ = stale_successors[0]
      yield from self._dfs_sparse_helper(
        succ, flow_graph, current_path, new_visited, global_visited, node_ids
      )
    else:
      # all successors have been visited in the current path, pick default path
      yield from self._dfs_sparse_pick_default_path(
        current, flow_graph, current_path, new_visited, node_ids
      )

    # for succ in successors:
    #   succ_id = node_ids[succ]
    #   if succ_id in new_visited:
    #     continue

    #   if succ_id in new_visited:
    #     yield from self._dfs_sparse_pick_default_path(
    #       succ, flow_graph, current_path, new_visited, node_ids
    #     )
    #   else:
    #     yield from self._dfs_sparse_helper(
    #       succ, flow_graph, current_path.copy(), new_visited, node_ids
    #     )

  def _dfs_sparse_pick_default_path(
    self,
    current: FlowNode,
    flow_graph: FlowGraph,
    current_path: Path,
    visited: set[str],
    node_ids: dict[FlowNode, str],
  ) -> Generator[Path, None, None]:
    """
    Helper function to pick a default path.
    """
    current_node_id = node_ids[current]
    visited.add(current_node_id)
    for path_segment in current.path_segments:
      current_path.add_node(path_segment)
    successors = flow_graph.successors.get(current, [])
    if not successors:
      yield current_path.copy()
      return
    # pick the first successor that is not parent of current node
    first_succ = successors[0]
    yield from self._dfs_sparse_pick_default_path(
      first_succ, flow_graph, current_path, visited, node_ids
    )

  def dfs(
    self, current: Node | FSM, current_path: Path, should_terminate: bool = False
  ) -> Generator[Path, None, None]:
    should_terminate = should_terminate or (current in self.exits)

    if isinstance(current, Node):
      match current.kind:
        case NodeKind.Normal:
          current_path.add_node(
            PathNode(
              PathNodeKind.NODE_WO_CONDITION
              if current.condition_ast is None
              or current.condition_ast is FSM.dummy_true_condition
              else PathNodeKind.NODE_W_CONDITION,
              node=current,
              fsm=None,
            )
          )
        case NodeKind.Empty:
          if current.condition_ast is not None:
            current_path.add_node(
              PathNode(
                PathNodeKind.CONDITION,
                node=Node(
                  name="<dummy>",
                  parser_context=self.parser_context,
                  kind=NodeKind.Normal,
                  _condition_ast=current.condition_ast,
                ),
                fsm=None,
              )
            )
        case NodeKind.Start:
          # do nothing for start node
          ...
    else:  # current is FSM
      match current.kind:
        case FSMKind.Empty:
          node = PathNode(
            PathNodeKind.CONDITION,
            fsm=current,
            node=Node(
              name="<dummy>",
              parser_context=self.parser_context,
              type_expr=None,
              kind=NodeKind.Normal,
              _condition_ast=current.size_expr  # pyright: ignore[reportArgumentType]
              if current.size_expr is not None
              else FSM.dummy_true_condition,
            ),
          )
          current_path.add_node(node)
        case FSMKind.Normal:
          node = PathNode(
            PathNodeKind.FSM_START, fsm=current, fsm_args=current.fsm_args
          )
          node_for_size_expr: PathNode | None = None  # pyright: ignore[reportRedeclaration]
          if current.size_expr is not None:
            node_for_size_expr = PathNode(
              PathNodeKind.CONDITION,
              fsm=current,
              node=Node(
                name="<dummy>",
                parser_context=self.parser_context,
                type_expr=None,
                kind=NodeKind.Normal,
                _condition_ast=CmpExpr(
                  op=Tok3D(Tok3DType.CMPOP, "==", 0, 0),
                  left=current.size_expr,
                  right=FunctionCall(
                    Tok3D(Tok3DType.IDENT, "sizeof", 0, 0),
                    [
                      Ident(
                        Tok3D(
                          Tok3DType.IDENT,
                          "this",
                          0,
                          0,
                        )
                      )
                    ],
                  ),
                ),
              ),
            )
          if node_for_size_expr is not None:
            current_path.add_node(node_for_size_expr)
          current_path.add_node(node)
        case FSMKind.Call:
          fsm = current.call_fsm
          if fsm is None:
            raise ValueError("CallFSM must have a call_fsm")
          node = PathNode(
            PathNodeKind.FSM_START,
            fsm=fsm,
            fsm_args=current.fsm_args,
          )
          node_for_size_expr: PathNode | None = None
          if current.fsm_size_expr is not None:
            node_for_size_expr = PathNode(
              PathNodeKind.CONDITION,
              fsm=current,
              node=Node(
                name="<dummy>",
                parser_context=self.parser_context,
                type_expr=None,
                kind=NodeKind.Normal,
                _condition_ast=CmpExpr(
                  op=Tok3D(Tok3DType.CMPOP, "==", 0, 0),
                  left=current.fsm_size_expr,
                  right=FunctionCall(
                    Tok3D(Tok3DType.IDENT, "sizeof", 0, 0),
                    [
                      Ident(
                        Tok3D(
                          Tok3DType.IDENT,
                          "this",
                          0,
                          0,
                        )
                      )
                    ],
                  ),
                ),
              ),
            )
          current_path.add_node(node)
          if node_for_size_expr is not None:
            current_path.add_node(node_for_size_expr)
    if isinstance(current, Node) and not current.transitions and should_terminate:
      yield current_path.copy()

    if isinstance(current, Node):
      for child, condition in current.transitions.items():
        condition_node = PathNode(
          PathNodeKind.CONDITION,
          node=Node(
            name="<dummy>",
            parser_context=self.parser_context,
            kind=NodeKind.Normal,
            _condition_ast=condition,
          ),
          fsm=None,
        )
        new_path = current_path.copy()
        new_path.add_node(condition_node)
        yield from self.dfs(child, new_path, should_terminate)
    elif isinstance(current, FSM):  # pyright: ignore[reportUnnecessaryIsInstance]
      if current.kind is FSMKind.Normal:
        entry_paths = current.dfs(current.entry, current_path.copy(), False)
        for entry_path in entry_paths:
          entry_path.add_node(
            PathNode(
              PathNodeKind.FSM_END,
              fsm=current,
            )
          )
          if not current.nexts:
            yield entry_path
          else:
            for child in current.nexts:
              yield from self.dfs(child, entry_path.copy(), should_terminate)
      elif current.kind is FSMKind.Call:
        if current.call_fsm is None:
          raise ValueError("CallFSM must have a call_fsm")
        entry_paths = current.call_fsm.dfs(
          current.call_fsm.entry, current_path.copy(), False
        )
        for entry_path in entry_paths:
          entry_path.add_node(
            PathNode(
              PathNodeKind.FSM_END,
              fsm=current.call_fsm,
            )
          )
          fsm = current.call_fsm
          # want to splice the dfs of fsm with current's dfs result
          if not fsm.nexts:
            if not current.nexts:
              yield entry_path
            else:
              for child in current.nexts:
                yield from self.dfs(child, entry_path.copy(), should_terminate)
      else:
        entry_paths = current.dfs(current.entry, current_path.copy(), False)
        if not current.nexts:
          yield from entry_paths
        else:
          for entry_path in entry_paths:
            for child in current.nexts:
              yield from self.dfs(child, entry_path.copy(), should_terminate)

  def save_all_paths(self) -> Generator[Path, None, None]:
    # yield from self.save_all_paths_dense()
    # return
    if self._flow_graph is None:
      flow_graph = self.into_flowgraph()
      self._flow_graph = flow_graph
    # print(flow_graph.to_dot())
    yield from self.dfs_sparse(
      self._flow_graph,
    )
    # yield from self.dfs(self, initial_path)

  def count_all_paths_dense(self) -> int:
    count = 0
    initial_path = Path()
    for _ in self.dfs(self, initial_path):
      count += 1
    return count

  def save_all_paths_dense(self) -> Generator[Path, None, None]:
    initial_path = Path()
    yield from self.dfs(self, initial_path)

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
        if current.kind == FSMKind.Call:
          if current.call_fsm is None:
            raise ValueError("CallFSM must have a call_fsm")
          next_fsms = [current.call_fsm]
        else:
          next_fsms = current.nexts
        for next_fsm in next_fsms:
          if next_fsm not in visited:
            queue.append(next_fsm)
    this_str = ""
    this_end = (
      f"FSM_END({self.call_fsm.name})"
      if self.kind == FSMKind.Call and self.call_fsm is not None
      else f"FSM_END({self.name})"
    )
    match self.kind:
      case FSMKind.Empty:
        this_str = f"emptyFSM({self.name}): {self.size_expr if self.size_expr is not None else ''} "
      case FSMKind.Normal:
        this_str = (
          f"FSM({self.name}): {self.size_expr if self.size_expr is not None else ''} "
        )
      case FSMKind.Call:
        if self.call_fsm is None:
          raise ValueError("CallFSM must have a call_fsm")
        this_str: str = f"Call({self.call_fsm.name}, [{', '.join(map(str, self.fsm_args))}]): {self.call_fsm.size_expr if self.call_fsm.size_expr is not None else ''} "
    return this_str + " -> ".join(filter(None, bfs_output)) + " -> " + this_end


class FSMBuilder(AstVisitor):
  def __init__(self, make_branch_for_empty: bool = False) -> None:
    super().__init__()
    self.FSM_map: dict[str, FSM] = {}
    self.make_branch_for_empty: bool = make_branch_for_empty

  def build_from_format(self, format_code: str) -> tuple[FSM, Module, ParserContext]:
    from src.parse3d import Parse3D

    parser = Parse3D(format_code)
    module_node = parser.parse()
    if module_node.entrypoint is None:
      raise ValueError("No entrypoint defined in the module")
    context = parser.context
    fsm_map = self.build(module_node, context)
    return fsm_map[module_node.entrypoint], module_node, context

  def build(self, node: "Module", context: "ParserContext") -> dict[str, FSM]:
    self.FSM_map.clear()
    self.visit(node, context)
    return self.FSM_map

  def visit_Module(self, node: "Module", context: "ParserContext") -> None:
    for definition in node.definitions.values():
      self.visit(definition, context)

  def visit_Struct(self, struct: "Struct", context: "ParserContext") -> None:
    fsm = FSM(struct.name, context, kind=FSMKind.Normal)
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
    from copy import copy

    for key, value in context.defined_structs.items():
      if value.name == struct.name:
        self.FSM_map[key] = fsm
        fsm_renamed = copy(fsm)
        fsm_renamed.name = key
        self.FSM_map[key] = fsm_renamed

  def visit_CaseType(self, casetype: "CaseType", context: "ParserContext") -> FSM:
    from src.parse3d import (
      LogicalExpr,
      CmpExpr,
      ParenExpr,
    )

    fsm = FSM(casetype.name, context, kind=FSMKind.Normal)
    fsm.fsm_params = casetype.parameters
    self.FSM_map[casetype.name] = fsm
    for key, value in context.defined_casetypes.items():
      if value.name == casetype.name:
        self.FSM_map[key] = fsm
    for case in casetype.cases:
      case_branch = casetype.cases[case]
      expect_fsm = self.visit_CaseBranch(case_branch, context)
      case_constraint = CmpExpr(
        op=Tok3D(Tok3DType.CMPOP, "==", case_branch.line, case_branch.col),
        left=casetype.switch_var,
        right=IntLiteral(Tok3D(Tok3DType.INT, case, case_branch.line, case_branch.col)),
      )
      for param_constraint in casetype.parameter_constraints:
        if not isinstance(param_constraint.expr, (LogicalExpr, CmpExpr, ParenExpr)):  # pyright: ignore[reportUnnecessaryIsInstance]
          raise ValueError("Expect (LogicalExpr, CmpExpr, ParenExpr)")
        case_constraint = LogicalExpr(
          Tok3D(
            Tok3DType.LOGOP,
            "&&",
            param_constraint.expr.line,
            param_constraint.expr.col,
          ),
          case_constraint,
          param_constraint.expr,
        )
      if case_branch.field.constraint is not None:
        case_constraint = LogicalExpr(
          Tok3D(
            Tok3DType.LOGOP,
            "&&",
            case_branch.field.constraint.expr.line,
            case_branch.field.constraint.expr.col,
          ),
          case_constraint,
          case_branch.field.constraint.expr,
        )
      fsm.entry.add_transition(case_constraint, expect_fsm)
    return fsm

  def visit_CaseBranch(
    self, case_branch: "CaseBranch", context: "ParserContext"
  ) -> FSM:
    from src.parse3d import (
      StructNameType,
      StructType,
      PrimitiveType,
      ArrayType,
      EmptyType,
    )

    match case_branch.field.typ:
      case EmptyType():
        fsm = FSM("emptyFSM", parser_context=context, kind=FSMKind.Empty)
        return fsm
      case StructType() as st:
        self.visit_Struct(st.struct, context)
        fsm = self.FSM_map[st.struct.name]
        self.FSM_map[case_branch.field.name] = fsm
        return fsm
      case StructNameType() as snt:
        if snt.name not in self.FSM_map:
          raise ValueError(f"FSM {snt.name} not found in FSM_map")
        struct_fsm = self.FSM_map[snt.name]
        return FSM(
          name=case_branch.field.name,
          parser_context=context,
          kind=FSMKind.Call,
          fsm_args=snt.args,
          fsm_size_expr=None,
          call_fsm=struct_fsm,
        )
      case PrimitiveType() as pt:
        expect_list = self.visit_FieldDecl(case_branch.field, context)
        if not isinstance(expect_list, list):  # pyright: ignore[reportUnnecessaryIsInstance]
          raise ValueError("Expected a list of Node or FSM")
        if len(expect_list) != 1:
          raise ValueError("Expected exactly one Node for PrimitiveType field")
        expect_node = expect_list[0]
        if not isinstance(expect_node, Node):
          raise ValueError("Expected a Node for PrimitiveType field")
        fsm = FSM(f"FSM_{pt.name}", parser_context=context, kind=FSMKind.Normal)
        fsm.entry.add_transition(None, expect_node)
        fsm.exits = [expect_node]
        return fsm
      case ArrayType() as at:
        expect_list = self.visit_FieldDecl(case_branch.field, context)
        if not isinstance(expect_list, list):  # pyright: ignore[reportUnnecessaryIsInstance]
          raise ValueError("Expected a list of Node or FSM")
        fsm = FSM(f"FSM_{at.name}", parser_context=context, kind=FSMKind.Normal)
        if len(expect_list) == 1:
          fsm.entry.add_transition(None, expect_list[0])
          fsm.exits = [expect_list[0]]
        else:
          fsm.addlists(expect_list)
          fsm.entry.add_transition(None, expect_list[0])
          fsm.exits = [expect_list[-1]]
        return fsm
      case _:
        raise ValueError(f"Unsupported case branch field type: {case_branch.field.typ}")

  def visit_FieldDecl(
    self, field_decl: "FieldDecl", context: "ParserContext"
  ) -> list[Node | FSM]:
    from src.parse3d.ast import (
      StructNameType,
      PrimitiveType,
      ArrayType,
      EmptyType,
      TypeExpr,
    )

    match field_decl.typ:
      case EmptyType():
        return [
          FSM(
            name="emptyFSM",
            parser_context=context,
            kind=FSMKind.Empty,
            size_expr=field_decl.constraint.expr
            if field_decl.constraint is not None
            else None,
          )
        ]
      case PrimitiveType() as pt:
        return [
          Node(
            name=field_decl.name,
            parser_context=context,
            type_expr=pt,
            _condition_ast=field_decl.constraint.expr
            if field_decl.constraint is not None
            else None,
            kind=NodeKind.Normal,
          )
        ]
      case StructNameType() as snt:
        # this is a call to another FSM
        if snt.name not in self.FSM_map:
          raise ValueError(f"FSM {snt.name} not found in FSM_map")
        called_fsm = self.FSM_map[snt.name]
        for arg in snt.args:
          if isinstance(arg, TypeExpr):
            raise ValueError("FSM arguments should not be TypeExpr")
        fsm_call = FSM(
          name=f"{called_fsm.name}",
          parser_context=context,
          kind=FSMKind.Call,
          fsm_args=snt.args,
          fsm_size_expr=None,
          call_fsm=called_fsm,
        )
        return [fsm_call]
      case ArrayType() as at:
        array_name = field_decl.name
        array_type: TypeExpr = at
        array_size = at.size
        array_size_str = array_size.__str__()
        if array_size_str.isdigit() or "sizeof(this)" in array_size_str:
          if isinstance(array_type.elem_type, PrimitiveType):
            return [Node(array_name, context, NodeKind.Normal, at)]
          else:
            assert isinstance(array_type.elem_type, StructNameType)
            elem_fsm = self.FSM_map.get(array_type.elem_type.name)
            if elem_fsm is None:
              raise ValueError(f"FSM {array_type.elem_type.name} not found in FSM_map")
            fsm_call = FSM(
              name=f"{elem_fsm.name}",
              parser_context=context,
              kind=FSMKind.Call,
              fsm_args=array_type.elem_type.args,
              fsm_size_expr=array_size,
              call_fsm=elem_fsm,
            )
            if not self.make_branch_for_empty:
              return [fsm_call]
            empty_call = FSM(
              name="emptyFSM",
              parser_context=context,
              kind=FSMKind.Call,
              fsm_size_expr=fsm_call.fsm_size_expr,
              call_fsm=FSM(
                name="emptyFSM",
                parser_context=context,
                kind=FSMKind.Empty,
                size_expr=fsm_call.fsm_size_expr,
              ),
            )
            return [
              fsm_call,
              empty_call,
            ]
        else:
          if isinstance(array_type.elem_type, PrimitiveType):
            return [
              Node(
                name="empty",
                parser_context=context,
                kind=NodeKind.Empty,
                _condition_ast=CmpExpr(
                  op=Tok3D(Tok3DType.CMPOP, "==", 0, 0),
                  left=array_size,
                  right=IntLiteral(Tok3D(Tok3DType.INT, "0", 0, 0)),
                ),
              ),
              Node(
                name=array_name,
                parser_context=context,
                kind=NodeKind.Normal,
                type_expr=at,
                _condition_ast=field_decl.constraint.expr
                if field_decl.constraint is not None
                else None,
              ),
            ]
          else:
            assert isinstance(array_type.elem_type, StructNameType)
            elem_fsm = self.FSM_map.get(array_type.elem_type.name)
            if elem_fsm is None:
              raise ValueError(f"FSM {array_type.elem_type.name} not found in FSM_map")
            fsm_call = FSM(
              name=f"{elem_fsm.name}",
              parser_context=context,
              kind=FSMKind.Call,
              fsm_args=array_type.elem_type.args,
              fsm_size_expr=array_size,
              call_fsm=elem_fsm,
            )
            if not self.make_branch_for_empty:
              return [fsm_call]
            empty_call = FSM(
              name="emptyFSM",
              parser_context=context,
              kind=FSMKind.Call,
              fsm_size_expr=fsm_call.fsm_size_expr,
              call_fsm=FSM(
                name="emptyFSM",
                parser_context=context,
                kind=FSMKind.Empty,
                size_expr=fsm_call.fsm_size_expr,
              ),
            )
            return [
              fsm_call,
              empty_call,
            ]
      case _:
        raise ValueError(f"Unsupported field type: {field_decl.typ}")


class PathNodeKind(Enum):
  NODE_W_CONDITION = 0
  NODE_WO_CONDITION = 1
  FSM_START = 2
  FSM_END = 3
  CONDITION = 4


class PathNode:
  def __init__(
    self,
    kind: PathNodeKind,
    node: Node | None = None,
    fsm: FSM | None = None,
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
    match kind:
      case PathNodeKind.NODE_W_CONDITION | PathNodeKind.CONDITION:
        if node is None:
          raise ValueError("Node must be provided for NODE_W_CONDITION or CONDITION")
        if (
          node.condition_ast is FSM.dummy_true_condition
          and kind == PathNodeKind.NODE_W_CONDITION
        ):
          raise ValueError(
            "Node with condition kind must have a non-trivial condition_ast"
          )
      case PathNodeKind.NODE_WO_CONDITION:
        if node is None:
          raise ValueError("Node must be provided for NODE_WO_CONDITION")
      case PathNodeKind.FSM_START | PathNodeKind.FSM_END:
        if fsm is None:
          raise ValueError("FSM must be provided for FSM_START, FSM_END")
    self.kind: PathNodeKind = kind
    self.node: Node | None = node
    self.fsm: FSM | None = fsm
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
    # do not want a seperate condition field, for CONDITION kind, we want to make a dummy node with only condition_ast set. by removing seperate condition field, we can avoid confusion

  def bit_size(self) -> str:
    if self.kind not in (PathNodeKind.NODE_W_CONDITION, PathNodeKind.NODE_WO_CONDITION):
      return "0"
    if self.node is None:
      raise ValueError("Node is None for bit_size computation")
    from src.parse3d.ast import PrimitiveType, ArrayType

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
            return f"(({at.size}) * ({pet.bits}))"
          case _:
            todo("bit_size for array of non-primitive types")
      case _:
        todo("bit_size for non-primitive, non-array types")

  @property
  def condition_ast(self) -> condition_ast_type | None:
    if self.kind in (
      PathNodeKind.NODE_W_CONDITION,
      PathNodeKind.CONDITION,
      PathNodeKind.NODE_WO_CONDITION,
    ):
      if self.node is None:
        raise ValueError("Node is None for condition_ast retrieval")
      return self.node.condition_ast
    else:
      raise ValueError(f"condition_ast is not available for {self.kind}")

  @property
  def tightened_condition_ast(self) -> condition_ast_type | None:
    if self.kind in (
      PathNodeKind.NODE_W_CONDITION,
      PathNodeKind.CONDITION,
      PathNodeKind.NODE_WO_CONDITION,
    ):
      if self.node is None:
        raise ValueError("Node is None for tightened_condition_ast retrieval")
      return self.node.tightened_condition_ast
    else:
      raise ValueError(f"tightened_condition_ast is not available for {self.kind}")

  @override
  def __repr__(self) -> str:
    match self.kind:
      case PathNodeKind.NODE_W_CONDITION:
        if self.node is None:
          raise ValueError("Node is None for NODE_W_CONDITION")
        return (
          f"Node({self.node.name}, type={self.node.type_expr}, condition=({self.node.condition_str}))"
          if self.node.condition_ast is not FSM.dummy_true_condition
          else f"Node({self.node.name}, type={self.node.type_expr})"
        )
      case PathNodeKind.NODE_WO_CONDITION:
        return f"Node({self.node.name}, type={self.node.type_expr})"  # pyright: ignore[reportOptionalMemberAccess]
      case PathNodeKind.FSM_START:
        return f"FSM_START({self.fsm.name}){f': {self.fsm.size_expr}' if self.fsm.size_expr and self.fsm.size_expr is not FSM.dummy_true_condition else ''}"  # pyright: ignore[reportOptionalMemberAccess]
      case PathNodeKind.FSM_END:
        return f"FSM_END({self.fsm.name})"  # pyright: ignore[reportOptionalMemberAccess]
      case PathNodeKind.CONDITION:
        return (
          f"[{self.condition_ast.__str__()}]"
          if self.condition_ast is not None
          and self.condition_ast is not FSM.dummy_true_condition
          else ""
        )


class Path:
  def __init__(self, nodes: list[PathNode] | None = None):
    self.nodes: list[PathNode] = nodes or []

  def add_node(self, path_node: PathNode) -> None:
    self.nodes.append(path_node)

  def add_nodes(self, path_nodes: list[PathNode]) -> None:
    self.nodes.extend(path_nodes)

  def copy(self) -> Path:
    return Path(self.nodes.copy())

  @property
  def name(self) -> str:
    if not self.nodes:
      raise ValueError("Path has no nodes to get name from")
    first_node = self.nodes[0]
    match first_node.kind:
      case PathNodeKind.FSM_START:
        if first_node.fsm is None:
          raise ValueError("FSM is None for FSM_START PathNode")
        return first_node.fsm.name
      case _:
        raise ValueError(f"First node of Path is not FSM_START, got {first_node.kind}")

  @override
  def __repr__(self) -> str:
    return " -> ".join(filter(None, map(str, self.nodes)))

  @override
  def __str__(self) -> str:
    return self.__repr__()

  @override
  def __hash__(self) -> int:
    return hash(tuple(self.nodes))

  def compute_field_offsets(self) -> dict[str, tuple[int, int, int]]:
    """Walk PathNodes and compute byte/bit offset for each data field.

    Returns a dict mapping field_name -> (byte_offset, bit_offset, bit_width).
    Byte_offset is relative to the start of the path's packet layout.
    Bit_offset is the bit position within the byte (0-7).

    Handles nested FSM calls via a simple stack accumulator.
    Symbolic (non-concrete) sizes are skipped with a warning.
    """
    offsets: dict[str, tuple[int, int, int]] = {}
    # Stack of (saved_byte, saved_bit) for nested FSM calls
    stack: list[tuple[int, int]] = []
    byte_offset = 0
    bit_offset = 0  # bit position within current byte (0-7)

    for pn in self.nodes:
      match pn.kind:
        case PathNodeKind.FSM_START:
          stack.append((byte_offset, bit_offset))

        case PathNodeKind.FSM_END:
          if stack:
            byte_offset, bit_offset = stack.pop()

        case PathNodeKind.NODE_W_CONDITION | PathNodeKind.NODE_WO_CONDITION:
          if pn.node is None:
            continue
          name = pn.node.name
          bit_size_str = pn.bit_size()

          # Try to parse as a concrete integer size
          try:
            bit_size = int(bit_size_str)
          except (ValueError, TypeError):
            # Symbolic size expression — skip with a sentinel value
            bit_size = -1

          if bit_size > 0:
            # Record current offset for this field
            offsets[name] = (byte_offset, bit_offset, bit_size)

            # Advance the bit accumulator
            total_bits = bit_offset + bit_size
            byte_offset += total_bits // 8
            bit_offset = total_bits % 8
          else:
            # Symbolic size: record with sentinel byte_offset = -1
            offsets[name] = (-1, -1, -1)

        case PathNodeKind.CONDITION:
          pass  # pure condition nodes occupy no bits

    return offsets

  # bit size computing is not included here, but rather should be computed by encoders, to make Path purely represent the path structure. Encoders should build stacks/frames when encountering FSM calls to track bit sizes
