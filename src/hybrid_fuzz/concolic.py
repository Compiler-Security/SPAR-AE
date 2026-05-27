from dataclasses import dataclass, field
from z3.z3 import BoolRef, Not
import sys
import operator
from typing import Any, Callable, Literal, TypedDict, final, override
import z3
from contextvars import ContextVar
from src.tool import todo


class PathEventDict(TypedDict):
  constraint: str
  lineno: int
  filename: str
  function_name: str
  variable_names: list[str]
  byte_variables: list[str]


@dataclass
class PathEvent:
  constraint: BoolRef  # z3 BoolRef
  lineno: int
  filename: str
  function_name: str
  variable_names: list[str] = field(default_factory=list)
  byte_variables: list[str] = field(default_factory=list)

  def as_dict(self) -> PathEventDict:
    return {
      "constraint": self.constraint.sexpr(),  # pyright: ignore[reportUnknownMemberType]
      "lineno": self.lineno,
      "filename": self.filename,
      "function_name": self.function_name,
      "variable_names": self.variable_names,
      "byte_variables": self.byte_variables,
    }

  @classmethod
  def from_dict(cls, data: PathEventDict) -> "PathEvent":
    constraint = z3.parse_smt2_string(data["constraint"])[0]  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(constraint, BoolRef):
      raise ValueError("Parsed constraint is not a BoolRef")
    return cls(
      constraint=constraint,
      lineno=data["lineno"],
      filename=data["filename"],
      function_name=data["function_name"],
      variable_names=data.get("variable_names", []),
      byte_variables=data.get("byte_variables", []),
    )


_current_constraints = ContextVar("constraints", default=[])


class ContextMeta(type):
  """
  The Metaclass.
  Properties defined here become properties of the CLASS that uses this metaclass.
  """

  @property
  def path_constraints(cls) -> list[PathEvent]:
    # This runs when you access ExecutionContext.path_constraints
    return _current_constraints.get()


class ExecutionContext(metaclass=ContextMeta):
  @classmethod
  def reset(cls):
    _ = _current_constraints.set([])

  # Names that will never appear in name_to_section_py and should be
  # filtered from slicing results to avoid noise in section lookups.
  _BUILTIN_BLOCKLIST: set[str] = {
    "len", "sys", "__name__", "locals", "range", "int", "dict",
    "set", "open", "True", "False", "None", "ValueError",
    "NotImplemented", "type", "isinstance", "str", "bytes",
    "bytearray", "print", "enumerate", "zip", "map", "filter",
    "min", "max", "sum", "abs", "ord", "chr", "hex",
    "tuple", "list", "frozenset", "object", "float", "bool",
    "complex", "memoryview", "staticmethod", "classmethod",
    "Exception", "BaseException", "KeyError", "IndexError",
    "TypeError", "AttributeError", "StopIteration", "super",
    "any", "all", "sorted", "reversed", "iter", "next",
  }

  @staticmethod
  def _extract_vars_from_source_line(line: str) -> list[str]:
    """Parse a single Python source line and extract all user-defined Name references.

    Python builtins and keywords are filtered out since they will never
    map to RFC document sections via name_to_section_py.
    """
    import ast

    stripped = line.strip()
    if not stripped:
      return []

    wrappers = [
      stripped,
      stripped + "\n    pass",
    ]

    for wrapped in wrappers:
      try:
        tree = ast.parse(wrapped)
      except SyntaxError:
        continue
      return list({
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id not in ExecutionContext._BUILTIN_BLOCKLIST
      })

    return []

  @staticmethod
  def _extract_vars_from_context(filecontent: str, lineno: int) -> list[str]:
    """Fallback: find the tightest enclosing AST node and return all variable names within it."""
    import ast

    try:
      tree = ast.parse(filecontent)
    except SyntaxError:
      return []

    class ContextCollector(ast.NodeVisitor):
      def __init__(self, target_lineno: int):
        self.target_lineno = target_lineno
        self.best_node: ast.AST | None = None
        self.best_size: int = 10**9

      def visit(self, node: ast.AST) -> None:
        if hasattr(node, "lineno") and hasattr(node, "end_lineno"):
          end = node.end_lineno or node.lineno  # pyright: ignore[reportAny]
          if node.lineno <= self.target_lineno <= end:  # pyright: ignore[reportAny]
            size = end - node.lineno  # pyright: ignore[reportAny]
            if size < self.best_size:
              self.best_size = size
              self.best_node = node
        super().visit(node)

    collector = ContextCollector(lineno)
    collector.visit(tree)

    if collector.best_node is None:
      return []

    return list({
      node.id
      for node in ast.walk(collector.best_node)
      if isinstance(node, ast.Name)
      and node.id not in ExecutionContext._BUILTIN_BLOCKLIST
    })

  @staticmethod
  def _extract_bv_variables(expr: "z3.ExprRef") -> list[str]:  # pyright: ignore[reportUnknownMemberType]
    """Walk a z3 expression tree and collect all leaf BitVec variable names.

    Returns names like ['byte_0', 'byte_5'] that identify which input bytes
    a constraint depends on.  These can be matched to 3D field byte offsets.
    """
    variables: set[str] = set()

    def walk(node: "z3.ExprRef") -> None:  # pyright: ignore[reportUnknownMemberType]
      if z3.is_const(node):  # pyright: ignore[reportUnknownMemberType]
        if node.decl().kind() == z3.Z3_OP_UNINTERPRETED:  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
          if z3.is_bv_sort(node.sort()):  # pyright: ignore[reportUnknownMemberType]
            variables.add(str(node))
      else:
        for i in range(node.num_args()):  # pyright: ignore[reportUnknownMemberType]
          walk(node.arg(i))  # pyright: ignore[reportUnknownMemberType, reportAny]

    walk(expr)
    return list(variables)

  @staticmethod
  def slice_from_lineno(
    filecontent: str, lineno: int, concolic_bool: "ConcolicBool | None" = None
  ) -> list[str]:
    """Extract Python variable names involved in the branch condition at lineno.

    Primary: parse the source line directly for variable names.
    Fallback: examine the enclosing function/block for all variables in context.
    """
    if lineno < 0 or not filecontent:
      return []

    lines = filecontent.splitlines()
    if lineno > len(lines):
      return []

    line = lines[lineno - 1]

    source_vars = ExecutionContext._extract_vars_from_source_line(line)
    if source_vars:
      return source_vars

    return ExecutionContext._extract_vars_from_context(filecontent, lineno)

  @classmethod
  def add_constraint(
    cls,
    concrete_val: bool,
    symbolic_expr: BoolRef,
    filename: str = "",
    lineno: int = 0,
    function_name: str = "",
    concolic_bool: "ConcolicBool | None" = None,
  ):
    # We need to copy the list to modify it in ContextVar (immutable logic usually applies)
    # Or simpler: just store the list instance in thread-local storage (threading.local)
    constraints = _current_constraints.get()
    filecontent: str = ""
    try:
      with open(filename, "r", encoding="utf-8") as f:
        filecontent = f.read()
    except Exception:
      pass  # if we can't read the file, we just won't have the slice context
    variable_name = []
    sliced: list[str] = ExecutionContext.slice_from_lineno(
      filecontent, lineno, concolic_bool=concolic_bool
    )  # we can log this slice for better context in constraints
    variable_name = sliced
    byte_vars = ExecutionContext._extract_bv_variables(symbolic_expr)
    constraints.append(
      PathEvent(
        constraint=symbolic_expr if concrete_val else Not(symbolic_expr),  # pyright: ignore[reportUnknownArgumentType]
        lineno=lineno,
        filename=filename,
        function_name=function_name,
        variable_names=variable_name,
        byte_variables=byte_vars,
      )
    )


class ConcolicBool:
  def __init__(self, concrete_val: bool, symbolic_expr: BoolRef):
    self.concrete: bool = concrete_val
    self.symbolic: BoolRef = symbolic_expr

  def __bool__(self) -> bool:
    try:
      frame = sys._getframe(
        1
      )  # Get the caller's frame  # pyright: ignore[reportPrivateUsage]
      filename = frame.f_code.co_filename
      lineno = frame.f_lineno
      # get function name:
      func_name = frame.f_code.co_name
    except ValueError:
      # Fallback if stack is too shallow (rare)
      filename = "<unknown>"
      lineno = -1
      func_name = "<unknown>"
    ExecutionContext.add_constraint(
      self.concrete,
      self.symbolic,
      filename=filename,
      lineno=lineno,
      function_name=func_name,
      concolic_bool=self,
    )
    return self.concrete


class ConcolicByte:
  """
  A class representing a byte that can be used as a concrete value, but contains a symbolic variable for concolic execution.
  For example, if the concrete byte value is 65, it will have a symbolic variable and a constraint that the symbolic variable equals 65.
  Attributes:
    concrete_value (int): The concrete byte value (0-255).
    symbolic_var (z3.BitVec): The symbolic variable representing the byte.
    constraints (list): A list of z3 constraints associated with the symbolic variable.
  """

  def __init__(self, concrete_value: int, var_name: str):
    self.concrete: int = concrete_value & 0xFF  # ensure it's a byte
    self.symbolic: Any = z3.BitVec(  # pyright: ignore[reportExplicitAny, reportUnknownMemberType]
      var_name, 8
    )  # 8-bit BitVec for a byte

  @override
  def __repr__(self) -> str:
    return f"CB({self.concrete:02x})"

  # define comparison magic
  def _cmp(self, other, op_concorete: Callable[..., bool], op_symbolic):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    if isinstance(other, ConcolicByte):
      conc = other.concrete
      sym = other.symbolic  # pyright: ignore[reportAny]
    else:
      conc = other  # pyright: ignore[reportUnknownVariableType]
      sym = z3.BitVecVal(other, 8)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType, reportUnknownMemberType]

    res_concrete: bool = op_concorete(self.concrete, conc)
    res_symbolic = op_symbolic(self.symbolic, sym)  # pyright: ignore[reportUnknownVariableType, reportAny]
    return ConcolicBool(res_concrete, res_symbolic)  # pyright: ignore[reportUnknownArgumentType]

  def _operation_normalize(self, other):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    if isinstance(other, ConcolicByte):
      conc = other.concrete
      sym = other.symbolic  # pyright: ignore[reportAny]
    else:
      conc = other  # pyright: ignore[reportUnknownVariableType]
      sym = z3.BitVecVal(other, 8)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType, reportUnknownMemberType]

    return conc, sym  # pyright: ignore[reportUnknownVariableType]

  def _operation_helper(self, other, op):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    conc, sym = self._operation_normalize(other)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType, reportUnknownVariableType]

    res_concrete: int = op(self.concrete, conc) & 0xFF  # pyright: ignore[reportUnknownVariableType]
    res_symbolic = op(self.symbolic, sym)  # pyright: ignore[reportUnknownVariableType, reportAny]
    return ConcolicValue(res_concrete, res_symbolic)  # pyright: ignore[reportUnknownArgumentType]

  @override
  def __hash__(self) -> int:
    return hash((self.concrete))

  def __lshift__(self, other):
    return self._operation_helper(other, lambda x, y: x << y)  # pyright: ignore[reportUnknownArgumentType]

  def __rshift__(self, other):
    return self._operation_helper(other, lambda x, y: x >> y)  # pyright: ignore[reportUnknownArgumentType]

  def __or__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: x | y)

  def __ror__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: y | x)

  def __and__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: x & y)

  def __rand__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: y & x)

  def __add__(self, other):
    return self._operation_helper(other, lambda x, y: x + y)

  def __radd__(self, other):
    return self._operation_helper(other, lambda x, y: y + x)

  def __sub__(self, other):
    return self._operation_helper(other, lambda x, y: x - y)

  def __rsub__(self, other):
    return self._operation_helper(other, lambda x, y: y - x)

  def __mul__(self, other):
    return self._operation_helper(other, lambda x, y: x * y)

  def __rmul__(self, other):
    return self._operation_helper(other, lambda x, y: y * x)

  def __floordiv__(self, other):
    return self._operation_helper(other, lambda x, y: z3.UDiv(x, y))

  def __rfloordiv__(self, other):
    return self._operation_helper(other, lambda x, y: z3.UDiv(y, x))

  @override
  def __eq__(self, other):  # pyright: ignore[reportIncompatibleMethodOverride]
    return self._cmp(other, lambda x, y: x == y, lambda x, y: x == y)  # pyright: ignore[reportImplicitOverride, reportIncompatibleMethodOverride]

  @override
  def __ne__(self, other):  # pyright: ignore[reportIncompatibleMethodOverride]
    return self._cmp(other, lambda x, y: x != y, lambda x, y: x != y)  # pyright: ignore[reportIncompatibleMethodOverride, reportImplicitOverride]

  def __gt__(self, other):
    return self._cmp(other, lambda x, y: x > y, z3.UGT)  # Unsigned Greater Than

  def __ge__(self, other):
    return self._cmp(other, lambda x, y: x >= y, z3.UGE)

  def __lt__(self, other):
    return self._cmp(other, lambda x, y: x < y, z3.ULT)

  def __le__(self, other):
    return self._cmp(other, lambda x, y: x <= y, z3.ULE)

  def __bool__(self) -> bool:
    return bool(self.concrete)

  def as_int(
    self, byteorder: Literal["little", "big"] = "big", signed: bool = False
  ) -> "ConcolicValue":
    # simulate int.from_bytes for single byte
    # byteorder and signed have no effect for single byte
    return ConcolicValue(self.concrete, z3.BitVecVal(self.concrete, 8))  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]

  def __index__(self) -> int:
    return self.concrete

  def __int__(self) -> int:
    return self.concrete

  @override
  def __format__(self, format_spec: str) -> str:
    return format(self.concrete, format_spec)


@final
class ConcolicSlice:
  def __init__(self, concolic_bytes: "list[ConcolicByte]"):
    self.data: list[ConcolicByte] = concolic_bytes

  def __len__(self) -> int:
    return len(self.data)

  @override
  def __repr__(self) -> str:
    return f"CSlice({self.data})"

  def __bool__(self) -> bool:
    return bool(len(self.data))

  @override
  def __hash__(self) -> int:
    return hash(tuple(self.data))

  def __getitem__(self, key: int | slice) -> "ConcolicByte | ConcolicSlice":
    if isinstance(key, slice):
      return ConcolicSlice(self.data[key])
    return self.data[key]

  def _operation_normalize(self, other):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    if isinstance(other, ConcolicByte):
      conc = other.concrete
      sym = other.symbolic  # pyright: ignore[reportAny]
    else:
      conc = other  # pyright: ignore[reportUnknownVariableType]
      sym = z3.BitVecVal(other, 8)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType, reportUnknownMemberType]

    return conc, sym  # pyright: ignore[reportUnknownVariableType]

  @property
  def concrete(self) -> bytes:
    return bytes([b.concrete for b in self.data])

  @property
  def symbolic(self) -> Any:  # pyright: ignore[reportExplicitAny]
    if not self.data:
      return z3.BitVecVal(0, 0)  # pyright: ignore[reportUnknownMemberType]
    sym = self.data[0].symbolic  # pyright: ignore[reportAny]
    for i in range(1, len(self.data)):
      sym = z3.Concat(sym, self.data[i].symbolic)  # pyright: ignore[reportAny, reportUnknownMemberType, reportUnknownVariableType]
    return sym

  def _operation_helper(self, other, op):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    conc, sym = self._operation_normalize(other)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType, reportUnknownVariableType]

    res_concrete: int = op(self.data, conc) & 0xFF  # pyright: ignore[reportUnknownVariableType]
    res_symbolic = op(self.symbolic, sym)  # pyright: ignore[reportUnknownVariableType, reportAny]
    return ConcolicValue(res_concrete, res_symbolic)  # pyright: ignore[reportUnknownArgumentType]

  def __lshift__(self, other):
    return self._operation_helper(other, lambda x, y: x << y)  # pyright: ignore[reportUnknownArgumentType]

  def __rshift__(self, other):
    return self._operation_helper(other, lambda x, y: x >> y)  # pyright: ignore[reportUnknownArgumentType]

  def __or__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: x | y)

  def __ror__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: y | x)

  def __and__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: x & y)

  def __rand__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: y & x)

  def __add__(self, other):
    return self._operation_helper(other, lambda x, y: x + y)

  def __radd__(self, other):
    return self._operation_helper(other, lambda x, y: y + x)

  def __sub__(self, other):
    return self._operation_helper(other, lambda x, y: x - y)

  def __rsub__(self, other):
    return self._operation_helper(other, lambda x, y: y - x)

  def __mul__(self, other):
    return self._operation_helper(other, lambda x, y: x * y)

  def __rmul__(self, other):
    return self._operation_helper(other, lambda x, y: y * x)

  def __floordiv__(self, other):
    return self._operation_helper(other, lambda x, y: z3.UDiv(x, y))

  def __rfloordiv__(self, other):
    return self._operation_helper(other, lambda x, y: z3.UDiv(y, x))

  @override
  def __eq__(self, other):  # pyright: ignore[reportIncompatibleMethodOverride]
    return self._cmp(other, lambda x, y: x == y, lambda x, y: x == y)  # pyright: ignore[reportImplicitOverride, reportIncompatibleMethodOverride]

  @override
  def __ne__(self, other):  # pyright: ignore[reportIncompatibleMethodOverride]
    return self._cmp(other, lambda x, y: x != y, lambda x, y: x != y)  # pyright: ignore[reportIncompatibleMethodOverride, reportImplicitOverride]

  def __gt__(self, other):
    return self._cmp(other, lambda x, y: x > y, z3.UGT)  # Unsigned Greater Than

  def __ge__(self, other):
    return self._cmp(other, lambda x, y: x >= y, z3.UGE)

  def __lt__(self, other):
    return self._cmp(other, lambda x, y: x < y, z3.ULT)

  def __le__(self, other):
    return self._cmp(other, lambda x, y: x <= y, z3.ULE)

  def __eq__(self, other):  # pyright: ignore[reportIncompatibleMethodOverride, reportUnknownParameterType, reportImplicitOverride, reportMissingParameterType]
    if isinstance(other, (bytes, list, tuple)):
      other_data = other  # pyright: ignore[reportUnknownVariableType]
    elif isinstance(other, ConcolicSlice):
      other_data = other.data
    else:
      return ConcolicBool(False, z3.BoolVal(False))  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]

    if len(other_data) != len(self.data):  # pyright: ignore[reportUnknownArgumentType]
      return ConcolicBool(False, z3.BoolVal(False))  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]

    concrete_results: list[bool] = []
    symbolic_exprs: list[BoolRef] = []
    for i in range(len(self.data)):
      result = self.data[i] == other_data[i]  # pyright: ignore[reportUnknownVariableType]
      if not isinstance(result, ConcolicBool):
        todo(f"Unexpected result type in ConcolicSlice.__eq__: {type(result)}")  # pyright: ignore[reportUnknownArgumentType]
      concrete_results.append(result.concrete)
      symbolic_exprs.append(result.symbolic)

    final_concrete = all(concrete_results)
    final_symbolic = z3.And(*symbolic_exprs)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

    return ConcolicBool(final_concrete, final_symbolic)  # pyright: ignore[reportUnknownArgumentType]

  def as_int(
    self, byteorder: Literal["little", "big"] = "big", signed: bool = False
  ) -> "ConcolicValue":
    bytes_concrete = bytes([b.concrete for b in self.data])
    val_concrete = int.from_bytes(bytes_concrete, byteorder=byteorder, signed=signed)

    if not self.data:
      # empty slice, return 0
      return ConcolicValue(0, z3.IntVal(0))  # pyright: ignore[reportUnknownMemberType]
    if byteorder == "big":
      val_symbolic = self.data[0].symbolic  # pyright: ignore[reportAny]
      for i in range(1, len(self.data)):
        val_symbolic = z3.Concat(val_symbolic, self.data[i].symbolic)  # pyright: ignore[reportAny, reportUnknownMemberType, reportUnknownVariableType]
    else:  # little endian
      val_symbolic = self.data[-1].symbolic  # pyright: ignore[reportAny]
      for i in range(len(self.data) - 2, -1, -1):
        val_symbolic = z3.Concat(val_symbolic, self.data[i].symbolic)  # pyright: ignore[reportAny, reportUnknownMemberType, reportUnknownVariableType]

    return ConcolicValue(val_concrete, val_symbolic)


class ConcolicList:
  def __init__(self, bytes_list: "list[int | ConcolicByte]"):
    self.data: list[ConcolicByte] = []
    for i, b in enumerate(bytes_list):
      if isinstance(b, ConcolicByte):
        self.data.append(b)
      else:
        self.data.append(ConcolicByte(b, f"byte_{i}"))

  @override
  def __hash__(self) -> int:
    return hash(tuple(self.data))

  def __bool__(self) -> bool:
    return bool(len(self.data))

  def as_bytes(self) -> bytes:
    return bytes([b.concrete for b in self.data])

  @classmethod
  def from_bytes(cls, byte_data: bytes) -> "ConcolicList":
    return cls([b for b in byte_data])

  def __len__(self):
    return len(self.data)

  def __getitem__(self, key: int | slice) -> ConcolicByte | ConcolicSlice:
    if isinstance(key, slice):
      return ConcolicSlice(self.data[key])
    return self.data[key]

  def as_int(
    self, byteorder: Literal["little", "big"] = "big", signed: bool = False
  ) -> "ConcolicValue":
    return ConcolicSlice(self.data).as_int(byteorder=byteorder, signed=signed)

  def __contains__(self, item: object) -> bool:
    return item in self.data

  @override
  def __repr__(self):
    return f"CList({self.data})"


class ConcolicValue:
  """Helper class for multi-byte integers created from slices of ConcolicList."""

  def __init__(self, concrete: int, symbolic: Any):  # pyright: ignore[reportExplicitAny, reportAny]
    self.concrete: int = concrete
    self.symbolic: Any = symbolic  # pyright: ignore[reportExplicitAny]

  @override
  def __repr__(self) -> str:
    return f"CVal({self.concrete})"

  def __bool__(self) -> bool:
    return bool(self.concrete)

  @classmethod
  def from_bytes(
    cls,
    bytes: "ConcolicList",
    byteorder: Literal["big", "little"] = "big",
    *,
    signed: bool = False,
  ) -> "ConcolicValue":
    return bytes.as_int(byteorder=byteorder, signed=signed)

  def as_int(
    self, byteorder: Literal["little", "big"] = "big", signed: bool = False
  ) -> "ConcolicValue":
    # simulate int.from_bytes for multi-byte values
    # byteorder and signed have no effect here since we already have an int
    return self

  def __index__(self) -> int:
    return self.concrete

  def __int__(self) -> int:
    return self.concrete

  @override
  def __format__(self, format_spec: str) -> str:
    return format(self.concrete, format_spec)

  def _normalize_other(self, other: Any):  # pyright: ignore[reportUnknownParameterType, reportAny, reportExplicitAny]
    target_size = self.symbolic.size()  # pyright: ignore[reportAny]

    if isinstance(other, (ConcolicByte, ConcolicValue)):
      other_concrete = other.concrete
      other_symbolic = other.symbolic  # pyright: ignore[reportAny]
    elif isinstance(other, int):
      other_concrete = other
      masked_val = other & ((1 << target_size) - 1)  # pyright: ignore[reportAny]
      other_symbolic = z3.BitVecVal(masked_val, target_size)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportAny]
    else:
      raise TypeError(f"Unsupported type for comparison: {type(other)}")  # pyright: ignore[reportAny]

    other_size = other_symbolic.size()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if other_size < target_size:
      other_symbolic = z3.ZeroExt(target_size - other_size, other_symbolic)  # pyright: ignore[, reportUnknownMemberType, reportUnknownVariableType]
    elif other_size > target_size:
      self_sym_upcast = z3.ZeroExt(other_size - target_size, self.symbolic)  # pyright: ignore[ reportUnknownMemberType, reportAny, reportUnknownVariableType]
      return other_concrete, self_sym_upcast, other_symbolic  # pyright: ignore[reportUnknownVariableType]

    return other_concrete, self.symbolic, other_symbolic  # pyright: ignore[reportUnknownVariableType, reportAny]

  # Reuse comparison logic from ConcolicByte
  def _cmp(self, other, op_concorete: Callable[..., bool], op_symbolic):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    conc, sym, sym_other = self._normalize_other(other)

    res_concrete: bool = op_concorete(self.concrete, conc)
    res_symbolic = op_symbolic(sym, sym_other)  # pyright: ignore[reportUnknownVariableType]
    return ConcolicBool(res_concrete, res_symbolic)  # pyright: ignore[reportUnknownArgumentType]

  def _operation_helper(self, other, op_concrete, op_symbolic):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    conc, sym, sym_other = self._normalize_other(other)

    res_concrete: int = op_concrete(self.concrete, conc)  # pyright: ignore[reportUnknownVariableType]
    res_symbolic = op_symbolic(sym, sym_other)  # pyright: ignore[reportUnknownVariableType]
    return ConcolicValue(res_concrete, res_symbolic)  # pyright: ignore[reportUnknownArgumentType]

  @override
  def __hash__(self) -> int:
    return hash((self.concrete))

  def __lshift__(self, other):
    return self._operation_helper(other, lambda x, y: x << y, lambda x, y: x << y)  # pyright: ignore[reportUnknownArgumentType]

  def __rshift__(self, other):
    return self._operation_helper(other, lambda x, y: x >> y, lambda x, y: x >> y)  # pyright: ignore[reportUnknownArgumentType]

  def __or__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: x | y, lambda x, y: x | y)

  def __ror__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: y | x, lambda x, y: y | x)

  def __and__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: x & y, lambda x, y: x & y)

  def __rand__(self, value: Any, /):
    return self._operation_helper(value, lambda x, y: y & x, lambda x, y: y & x)

  def __add__(self, other):
    return self._operation_helper(other, lambda x, y: x + y, lambda x, y: x + y)

  def __radd__(self, other):
    return self._operation_helper(other, lambda x, y: y + x, lambda x, y: y + x)

  def __sub__(self, other):
    return self._operation_helper(other, operator.sub, operator.sub)

  def __rsub__(self, other):
    return self._operation_helper(
      other, lambda x, y: operator.sub(y, x), lambda x, y: y - x
    )

  def __mul__(self, other):
    return self._operation_helper(other, operator.mul, operator.mul)

  def __rmul__(self, other):
    return self._operation_helper(other, operator.mul, operator.mul)

  def __floordiv__(self, other):
    return self._operation_helper(other, operator.floordiv, z3.UDiv)

  def __rfloordiv__(self, other):
    return self._operation_helper(other, operator.floordiv, lambda x, y: z3.UDiv(y, x))

  @override
  def __eq__(self, other):  # pyright: ignore[reportIncompatibleMethodOverride]
    return self._cmp(other, lambda x, y: x == y, lambda x, y: x == y)  # pyright: ignore[reportImplicitOverride, reportIncompatibleMethodOverride]

  @override
  def __ne__(self, other):  # pyright: ignore[reportIncompatibleMethodOverride]
    return self._cmp(other, lambda x, y: x != y, lambda x, y: x != y)  # pyright: ignore[reportIncompatibleMethodOverride, reportImplicitOverride]

  def __gt__(self, other):
    return self._cmp(other, lambda x, y: x > y, z3.UGT)

  def __ge__(self, other):
    return self._cmp(other, lambda x, y: x >= y, z3.UGE)

  def __lt__(self, other):
    return self._cmp(other, lambda x, y: x < y, z3.ULT)

  def __le__(self, other):
    return self._cmp(other, lambda x, y: x <= y, z3.ULE)

