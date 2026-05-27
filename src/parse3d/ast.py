from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, final, override
from z3.z3 import ArithRef, IntVal  # pyright: ignore[reportUnknownVariableType]

if TYPE_CHECKING:
  from src.parse3d.tok import Tok3D
  from z3 import BoolRef, ArithRef, IntNumRef
  from collections.abc import Sequence, Mapping


class Ast(ABC):
  @override
  def __repr__(self) -> str:
    # a recursive pretty printer
    def _repr_with_indent(obj: object, indent_level: int) -> str:
      indent = "  " * indent_level
      if isinstance(obj, Constraint):
        return f"{obj.expr}"
      if isinstance(obj, TypeExpr):
        if obj.args:
          args = ", ".join(_repr_with_indent(arg, indent_level + 1) for arg in obj.args)
          return f"{obj.name}({args})"
        if isinstance(obj, PrimitiveType):
          complete_bits = obj.name.replace("UINT", "").replace("BE", "")
          if obj.bits != int(complete_bits):
            return f"{obj.name}<{obj.bits}>"
          return obj.name
        return obj.name
      if isinstance(obj, Ast):
        items = [
          f"\n{indent}  {k}={_repr_with_indent(v, indent_level + 1)}"  # pyright: ignore[reportAny]
          for k, v in filter(  # pyright: ignore[reportAny]
            lambda x: not (
              obj.__class__.__name__ == "FieldDecl"
              and x[0] == "belongs_to"  # avoid printing belongs_to to prevent recursion
            ),
            obj.__dict__.items(),
          )
        ]
        return f"{obj.__class__.__name__}({''.join(items)}\n{indent})"
      if isinstance(obj, dict):
        if not obj:
          return "{}"
        items = [
          f"\n{indent}  {repr(k)}: {_repr_with_indent(v, indent_level + 1)}"  # pyright: ignore[reportUnknownArgumentType]
          for k, v in obj.items()  # pyright: ignore[reportUnknownVariableType]
        ]
        return f"{{{''.join(items)}\n{indent}}}"
      if isinstance(obj, list):
        if not obj:
          return "[]"
        items = [f"\n{indent}  {_repr_with_indent(v, indent_level + 1)}" for v in obj]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        return f"[{','.join(items)}\n{indent}]"
      return repr(obj)

    return _repr_with_indent(self, 0)

  @property
  def line(self) -> int:
    return self.line_col()[0]

  @property
  def col(self) -> int:
    return self.line_col()[1]

  @abstractmethod
  def line_col(self) -> tuple[int, int]:
    raise NotImplementedError("Subclasses must implement line_col")


@final
class Module(Ast):
  __match_args__ = ("definitions", "entrypoint")

  @override
  def line_col(self) -> tuple[int, int]:
    return (0, 0)

  def __init__(
    self, definitions: "dict[str, Struct| CaseType]", entrypoint: "str | None" = None
  ):
    super().__init__()
    self.definitions: "dict[str, Struct | CaseType]" = definitions
    self.entrypoint: str | None = entrypoint
    # check entrypoint is valid
    if self.entrypoint is not None and self.entrypoint not in definitions:
      raise ValueError(f"Entrypoint {self.entrypoint} not found in definitions")

  def has_entrypoint(self) -> bool:
    return self.entrypoint is not None

  def get_entrypoint_struct(self) -> Struct:
    if self.entrypoint is None:
      raise ValueError("No entrypoint defined")
    entry_def = self.definitions[self.entrypoint]
    if not isinstance(entry_def, Struct):
      raise ValueError(f"Entrypoint {self.entrypoint} is not a struct")
    return entry_def

  def get_definition(self, name: str) -> Ast:
    if name not in self.definitions:
      raise ValueError(f"Definition {name} not found")
    return self.definitions[name]

  def get_struct(self, name: str) -> Struct:
    definition = self.get_definition(name)
    if not isinstance(definition, Struct):
      raise ValueError(f"Definition {name} is not a struct")
    return definition

  def get_casetype(self, name: str) -> CaseType:
    definition = self.get_definition(name)
    if not isinstance(definition, CaseType):
      raise ValueError(f"Definition {name} is not a casetype")
    return definition

  def get_casetypes(self) -> dict[str, CaseType]:
    return {
      name: defn
      for name, defn in self.definitions.items()
      if isinstance(defn, CaseType)
    }

  def get_structs(self) -> dict[str, Struct]:
    return {
      name: defn for name, defn in self.definitions.items() if isinstance(defn, Struct)
    }

  def is_struct(self, name: str) -> bool:
    definition = self.definitions.get(name)
    if definition is None:
      raise ValueError(f"Definition {name} not found")
    return isinstance(definition, Struct)

  def is_casetype(self, name: str) -> bool:
    definition = self.definitions.get(name)
    if definition is None:
      raise ValueError(f"Definition {name} not found")
    return isinstance(definition, CaseType)


@final
class Struct(Ast):
  __match_args__ = ("name", "fields", "parameters", "args_constraints")

  def __init__(
    self,
    name: "Tok3D",
    fields: list[FieldDecl],
    parameters: list[FieldDecl] | None = None,
    parameter_constraints: list[Constraint] | None = None,
  ):
    super().__init__()
    self.name: str = name.val
    self.fields: list[FieldDecl] = fields
    self.parameters: list[FieldDecl] = parameters or []
    self.parameter_constraints: list[Constraint] = (
      parameter_constraints or []
    )  # used for `where [constraint]` syntax
    self._line: int = name.line
    self._col: int = name.col

  @override
  def line_col(self) -> tuple[int, int]:
    return (self._line, self._col)

  def get_field(self, field_name: str) -> FieldDecl:
    for field in self.fields:
      if field.name == field_name:
        return field
    raise ValueError(f"Field {field_name} not found in struct {self.name}")

  def get_fields(self) -> list[FieldDecl]:
    return self.fields

  def has_field(self, field_name: str) -> bool:
    for field in self.fields:
      if field.name == field_name:
        return True
    return False

  def get_args(self) -> list[FieldDecl]:
    return self.parameters

  def has_args(self) -> bool:
    return len(self.parameters) > 0

  def get_args_constraints(self) -> list[Constraint]:
    return self.parameter_constraints


@final
class Entrypoint(Ast):
  __match_args__ = ("struct",)

  @override
  def line_col(self) -> tuple[int, int]:
    return self.struct.line_col()

  def __init__(self, struct: Struct):
    super().__init__()
    self.struct: Struct = struct


@final
class CaseType(Ast):
  __match_args__ = ("name", "case_variables", "cases", "switch_var", "args_constraints")

  @override
  def line_col(self) -> tuple[int, int]:
    return (self._line, self._col)

  def __init__(
    self,
    name: Tok3D,
    case_variables: list[FieldDecl],
    cases: dict[str, CaseBranch],
    switch_var: Tok3D,
    args_constraints: list[Constraint] | None = None,
  ):
    super().__init__()
    self.name: str = name.val
    self._line: int = name.line
    self._col: int = name.col
    self.case_variables: list[FieldDecl] = case_variables
    self.cases: dict[str, CaseBranch] = cases
    self.switch_var: Ident = Ident(switch_var)
    self.parameter_constraints: list[Constraint] = args_constraints or []
    # check all case values are unique
    case_values: set[str] = set()
    for case in cases.values():
      if case.value.val in case_values:
        raise ValueError(f"Duplicate case value {case.value.val} in casetype {name}")
      case_values.add(case.value.val)

  @property
  def parameters(self) -> list[FieldDecl]:
    return self.case_variables

  @property
  def switch_var_name(self) -> str:
    return self.switch_var.name.val


@final
class CaseBranch(Ast):
  __match_args__ = ("value", "field")

  @override
  def line_col(self) -> tuple[int, int]:
    return (self.value.line, self.value.col)

  def __init__(self, value: "Tok3D", field: "FieldDecl"):
    super().__init__()
    self.value: Tok3D = value
    self.field: "FieldDecl" = field


class TypeExpr(Ast):
  def __init__(
    self,
    name: str,
    args: Sequence[
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
    """
    This class is defiend to handle:
    entrypoint typedef struct _BFDControlPacket {
      MandatorySection mandatory;
      UINT8BE AuthType { AuthType <= 5 };
      AuthSection(AuthType) authSection; <-- THIS LINE
    } BFDControlPacket;
    """
    super().__init__()
    self.name: str = name
    self.args: Sequence[
      ArithExpr
      | IntLiteral
      | Ident
      | LogicalExpr
      | CmpExpr
      | FunctionCall
      | ParenExpr
      | TypeExpr
    ] = args if args is not None else []

  @override
  def line_col(self) -> tuple[int, int]:
    raise NotImplementedError("TypeExpr does not have line and column information")


@final
class PrimitiveType(TypeExpr):
  __match_args__ = ("name", "bits")

  def __init__(self, name: Tok3D, bits: int):
    if name.val not in {
      "UINT8BE",
      "UINT16BE",
      "UINT32BE",
      "UINT64BE",
    }:
      raise ValueError(f"Invalid primitive type: {name.val}")
    super().__init__(name.val)
    self._line = name.line
    self._col = name.col
    self.bits: int = bits

  @override
  def line_col(self) -> tuple[int, int]:
    return (self._line, self._col)


@final
class EmptyType(TypeExpr):
  __match_args__ = ()

  def __init__(self, line: int, col: int):
    super().__init__("empty")
    self._line: int = line
    self._col: int = col

  @override
  def line_col(self) -> tuple[int, int]:
    return (self._line, self._col)


@final
class StructType(TypeExpr):
  __match_args__ = ("struct",)

  def __init__(self, struct: Struct):
    super().__init__(struct.name)
    self.struct: Struct = struct

  @override
  def line_col(self) -> tuple[int, int]:
    return self.struct.line_col()


@final
class StructNameType(TypeExpr):
  __match_args__ = ("name", "struct", "args")

  def __init__(
    self,
    name: Tok3D,
    struct: Struct | CaseType | None = None,
    args: "Sequence[ArithExpr | IntLiteral | Ident | LogicalExpr | CmpExpr | FunctionCall | ParenExpr] | None" = None,
  ):
    # incase args are not marked as argument
    for arg in args or []:
      arg.is_argument = False
    super().__init__(name.val, args)
    self.struct: Struct | CaseType | None = struct
    self._line: int = name.line
    self._col: int = name.col

  @override
  def line_col(self) -> tuple[int, int]:
    return (self._line, self._col)

  def is_resolved(self) -> bool:
    return self.struct is not None

  def add_struct(self, struct: Struct | CaseType) -> None:
    if self.struct is not None:
      raise ValueError(f"Struct {self.name} is already resolved")
    self.struct = struct


@final
class ArrayType(TypeExpr):
  __match_args__ = ("elem_type", "size", "is_byte_size")

  def __init__(
    self,
    elem_type: TypeExpr,
    size: ArithExpr | IntLiteral | Ident | FunctionCall | ParenExpr,
    is_byte_size: bool = True,
  ):
    from uuid import uuid4

    super().__init__(f"array_{uuid4().__str__()[:4]}", [elem_type])
    self.elem_type: TypeExpr = elem_type
    self._is_byte_size: bool = is_byte_size
    self.size: ArithExpr | IntLiteral | Ident | FunctionCall | ParenExpr = size

  @property
  def is_byte_size(self) -> bool:
    return self._is_byte_size

  @override
  def line_col(self) -> tuple[int, int]:
    return self.elem_type.line_col()


@final
class FieldDecl(Ast):
  __match_args__ = ("name", "typ", "constraint")

  @override
  def line_col(self) -> tuple[int, int]:
    return self.typ.line_col()

  def __init__(
    self,
    name: str,
    typ: "TypeExpr",
    constraint: "Constraint | None" = None,
    belongs_to: Struct | CaseType | FieldDecl | None = None,
  ):
    super().__init__()
    self.belongs_to = belongs_to
    self.name: str = name
    self.typ: "TypeExpr" = typ
    self.constraint: "Constraint | None" = constraint

  @property
  def canonical_name(self) -> str:
    if self.belongs_to is None:
      return self.name
    return f"{self.belongs_to.name}.{self.name}"

  def has_constraint(self) -> bool:
    return self.constraint is not None

  def get_constraint(self) -> "Constraint":
    if self.constraint is None:
      raise ValueError(f"Field {self.name} has no constraint")
    return self.constraint

  def constraint_is_dependent(self) -> bool:
    if self.constraint is None:
      return False
    constraint_vars = list(self.constraint.get_expr().get_vars().keys())
    field_var = self.name
    if len(constraint_vars) == 0:
      return False
    if len(constraint_vars) == 1:
      return constraint_vars[0] != field_var
    return True


@final
class Constraint(Ast):
  __match_args__ = ("expr",)

  @override
  def line_col(self) -> tuple[int, int]:
    return self.expr.line_col()

  def __init__(self, expr: LogicalExpr | CmpExpr):
    super().__init__()
    self.expr: LogicalExpr | CmpExpr = expr

  def get_expr(self) -> LogicalExpr | CmpExpr:
    return self.expr

  @override
  def __str__(self) -> str:
    return f"{self.expr}"

  @override
  def __repr__(self) -> str:
    return self.__str__()


class Expr(Ast, ABC):
  use_cache: bool = True

  def __init__(self):
    super().__init__()
    self.z3_expr: "BoolRef | ArithRef | None" = None  # cache for z3 expression
    self.vars: "Mapping[str, ArithRef] | None" = None  # cache for variables
    self.is_argument: bool = False  # whether this expression is an argument to a function, used for FSM path renaming, to name it less a level, e.g., fsm1.param1 instead of fsm1.fsm2.param1, so that the name will match the parameter name the caller.

  @override
  def __setattr__(self, name: str, value: Any, /) -> None:  # pyright: ignore[reportExplicitAny, reportAny]
    if name in {"z3_expr", "vars"} and not self.use_cache:
      # do not set cache attributes if use_cache is False
      object.__setattr__(self, name, None)
    else:
      object.__setattr__(self, name, value)

  @override
  def line_col(self) -> tuple[int, int]:
    raise NotImplementedError("Subclasses must implement line_col")

  @abstractmethod
  @override
  def __str__(self) -> str:
    raise NotImplementedError("Subclasses must implement __str__")

  """
  to_bool_z3 and to_arith_z3 are used to convert the expression to z3 BoolRef or ArithRef.
  If the expression is not convertible to the requested type, it should raise a TypeError.
  1. LogicalExpr can be converted to BoolRef, but not ArithRef.
  2. CmpExpr can be converted to BoolRef, but not ArithRef.
  3. ArithExpr can be converted to ArithRef, but not BoolRef.
  4. IntLiteral can be converted to ArithRef, but not BoolRef.
  5. Ident can be converted to ArithRef, but not BoolRef.
  6. FunctionCall can be converted to ArithRef, but not BoolRef.
  7. ParenExpr can be converted to either BoolRef or ArithRef, depending on the inner expression.
  8. The get_vars method should return a dictionary of variable names to their corresponding IntNumRef in z3.
  9. The negate method should return a list of Expr that represents the negation of the expression.
  10. The negate method should handle De Morgan's laws for LogicalExpr.
  11. The negate method should handle negation of CmpExpr by inverting the comparison operator.
  """

  @abstractmethod
  def to_bool_z3(self) -> "BoolRef":
    raise TypeError("This expression cannot be converted to BoolRef")

  @abstractmethod
  def to_arith_z3(self) -> "ArithRef":
    raise TypeError("This expression cannot be converted to ArithRef")

  @abstractmethod
  def get_vars(self) -> "Mapping[str, ArithRef]": ...

  @abstractmethod
  def negate(self) -> "Sequence[Expr]": ...


@final
class LogicalExpr(Expr):
  __match_args__ = ("op", "left", "right")

  @override
  def line_col(self) -> tuple[int, int]:
    # the beginning of the logical expression
    return self.left.line_col()

  def __init__(
    self,
    op: "Tok3D",
    left: "CmpExpr | ParenExpr | LogicalExpr | IntLiteral | Ident | FunctionCall | ArithExpr",
    right: "CmpExpr | ParenExpr | LogicalExpr | IntLiteral | Ident | FunctionCall | ArithExpr",
  ):
    super().__init__()
    from src.parse3d.tok import Tok3DType

    if op.typ != Tok3DType.LOGOP:
      raise ValueError(f"Invalid logical operator: {op}")
    self.left: "LogicalExpr | CmpExpr | ParenExpr | IntLiteral | Ident | FunctionCall | ArithExpr" = left
    self.op: "Tok3D" = op
    self.right: "LogicalExpr | CmpExpr | ParenExpr | IntLiteral | Ident | FunctionCall | ArithExpr" = right

  @override
  def __str__(self) -> str:
    # replace || with or, && with and
    op_str = "or" if self.op.val == "||" else "and"
    return f"{self.left} {op_str} {self.right}"

  @override
  def __repr__(self) -> str:
    return self.__str__()

  @override
  def to_bool_z3(self) -> "BoolRef":
    if self.z3_expr is not None:
      return self.z3_expr  # pyright: ignore[reportReturnType]
    from z3 import Or, And  # pyright: ignore[reportUnknownVariableType]
    from typing import cast  # basedpyright is based

    z3_expr = None
    left_z3 = self.left.to_bool_z3()
    right_z3 = self.right.to_bool_z3()

    if self.op.val == "||":
      z3_expr = cast("BoolRef", Or(left_z3, right_z3))
      self.z3_expr = z3_expr
      return z3_expr
    elif self.op.val == "&&":
      z3_expr = cast("BoolRef", And(left_z3, right_z3))
      self.z3_expr = z3_expr
      return z3_expr
    else:
      raise ValueError(f"Unsupported logical operator: {self.op.val}")

  @override
  def to_arith_z3(self) -> "ArithRef":
    raise TypeError("LogicalExpr cannot be converted to ArithRef")

  @override
  def get_vars(self) -> "Mapping[str, ArithRef]":
    if self.vars is None:
      vars = {**self.left.get_vars(), **self.right.get_vars()}
      self.vars = vars
      return vars
    return self.vars

  @override
  def negate(self) -> "Sequence[LogicalExpr]":
    from src.parse3d.tok import Tok3D, Tok3DType
    from z3 import Solver, sat  # pyright: ignore[reportAny]

    # Determine the new operator based on De Morgan's laws
    if self.op.val == "||":
      new_op_val = "&&"
    elif self.op.val == "&&":
      new_op_val = "||"
    else:
      raise ValueError(f"Unsupported logical operator for negation: {self.op.val}")

    # Recursively negate the left and right sides
    left_negate = self.left.negate()
    right_negate = self.right.negate()

    negated_expressions: "list[LogicalExpr]" = []
    # Combine the negated parts using a list comprehension for conciseness
    for ln in left_negate:
      for rn in right_negate:
        if not isinstance(ln, (LogicalExpr, CmpExpr, ParenExpr)):
          raise TypeError(
            f"Left operand must be LogicalExpr, CmpExpr, or ParenExpr, got {type(ln)}"
          )
        if not isinstance(rn, (LogicalExpr, CmpExpr, ParenExpr)):
          raise TypeError(
            f"Right operand must be LogicalExpr, CmpExpr, or ParenExpr, got {type(rn)}"
          )

        # filter out unsat expressions using z3
        s = Solver()
        new_expr = LogicalExpr(
          Tok3D(Tok3DType.LOGOP, new_op_val, self.op.line, self.op.col), ln, rn
        )
        s.add(new_expr.to_bool_z3())  # pyright: ignore[reportUnknownMemberType]
        if s.check() == sat:  # pyright: ignore[reportUnknownMemberType]
          negated_expressions.append(new_expr)

    return negated_expressions


@final
class CmpExpr(Expr):
  __match_args__ = ("op", "left", "right")

  @override
  def line_col(self) -> tuple[int, int]:
    return self.left.line_col()

  def __init__(self, op: Tok3D, left: Expr, right: Expr):
    from src.parse3d.tok import Tok3DType

    super().__init__()
    if op.typ != Tok3DType.CMPOP:
      raise ValueError(f"Invalid comparison operator: {op}")
    self.left: Expr = left
    self.op: Tok3D = op
    self.right: Expr = right

  @override
  def __str__(self) -> str:
    return f"{self.left} {self.op.val} {self.right}"

  @override
  def __repr__(self) -> str:
    return self.__str__()

  @override
  def to_bool_z3(self) -> "BoolRef":
    if self.z3_expr is not None:
      return self.z3_expr  # pyright: ignore[reportReturnType]
    from operator import eq, ne, lt, le, gt, ge

    op_map: dict[str, Callable[..., BoolRef]] = {
      "==": eq,
      "!=": ne,
      "<": lt,
      "<=": le,
      ">": gt,
      ">=": ge,
    }
    left_z3: "ArithRef" = self.left.to_arith_z3()
    right_z3: "ArithRef" = self.right.to_arith_z3()
    if self.op.val not in op_map:
      raise ValueError(f"Unsupported comparison operator: {self.op.val}")
    z3_expr = op_map[self.op.val](left_z3, right_z3)
    self.z3_expr = z3_expr
    return z3_expr

  @override
  def to_arith_z3(self) -> "ArithRef":
    raise TypeError("CmpExpr cannot be converted to ArithRef")

  @override
  def get_vars(self) -> "Mapping[str, ArithRef]":
    if self.vars is None:
      vars = {**self.left.get_vars(), **self.right.get_vars()}
      self.vars = vars
      return vars
    return self.vars

  @override
  def negate(self) -> "Sequence[Expr]":
    from src.parse3d.tok import Tok3D, Tok3DType

    # Invert the comparison operator
    negated_op_map = {
      "==": ["<", ">"],
      "!=": ["=="],
      "<": [">", "=="],
      "<=": [">"],
      ">": ["<", "=="],
      ">=": ["<"],
    }
    if self.op.val not in negated_op_map:
      raise ValueError(f"Unsupported comparison operator for negation: {self.op.val}")

    negated_ops = negated_op_map[self.op.val]
    negated_toks = [
      Tok3D(Tok3DType.CMPOP, negated_op_val, self.op.line, self.op.col)
      for negated_op_val in negated_ops
    ]

    return [CmpExpr(negated_tok, self.left, self.right) for negated_tok in negated_toks]


@final
class ArithExpr(Expr):
  __match_args__ = ("op", "left", "right")

  @override
  def line_col(self) -> tuple[int, int]:
    return self.left.line_col()

  def __init__(self, op: Tok3D, left: Expr, right: Expr):
    from src.parse3d.tok import Tok3DType

    super().__init__()
    if op.typ != Tok3DType.ARITHOP:
      raise ValueError(f"Invalid arithmetic operator: {op}")
    self.left: Expr = left
    self.op: Tok3D = op
    self.right: Expr = right

  @override
  def __str__(self) -> str:
    return f"{self.left} {self.op.val} {self.right}"

  @override
  def __repr__(self) -> str:
    return self.__str__()

  @override
  def to_bool_z3(self) -> "BoolRef":
    raise TypeError(f"ArithExpr {self} cannot be converted to BoolRef")

  @override
  def to_arith_z3(self) -> "ArithRef":
    if self.z3_expr is not None:
      return self.z3_expr  # pyright: ignore[reportReturnType]
    from operator import add, sub, mul, truediv, mod

    op_map: dict[str, Callable[..., ArithRef]] = {
      "+": add,
      "-": sub,
      "*": mul,
      "/": truediv,
      "%": mod,
    }

    left_z3 = self.left.to_arith_z3()
    right_z3 = self.right.to_arith_z3()

    if self.op.val not in op_map:
      raise ValueError(f"Unsupported arithmetic operator: {self.op.val}")
    z3_expr = op_map[self.op.val](left_z3, right_z3)
    self.z3_expr = z3_expr
    return z3_expr

  @override
  def get_vars(self) -> "Mapping[str, ArithRef]":
    if self.vars is None:
      vars = {**self.left.get_vars(), **self.right.get_vars()}
      self.vars = vars
      return vars
    return self.vars

  @override
  def negate(self) -> "Sequence[Expr]":
    raise TypeError("ArithExpr cannot be negated")


@final
class IntLiteral(Expr):
  __match_args__ = ("value",)

  @override
  def line_col(self) -> tuple[int, int]:
    return (self.value.line, self.value.col)

  def __init__(self, value: Tok3D):
    from src.parse3d.tok import Tok3DType

    super().__init__()

    if value.typ != Tok3DType.INT:
      raise ValueError(f"Invalid integer literal: {value}")
    self.value: Tok3D = value

  def get_int_var(self) -> "ArithRef":
    from typing import cast

    return cast("ArithRef", IntVal(int(self.value.val)))

  @override
  def __str__(self) -> str:
    return self.value.val

  @override
  def __repr__(self) -> str:
    return self.__str__()

  @override
  def to_bool_z3(self) -> "BoolRef":
    raise TypeError("IntLiteral cannot be converted to BoolRef")

  @override
  def to_arith_z3(self) -> "ArithRef":
    return self.get_int_var()

  @override
  def get_vars(self) -> "dict[str, IntNumRef]":
    return {}

  @override
  def negate(self) -> "Sequence[Expr]":
    raise TypeError("IntLiteral cannot be negated")


@final
class Ident(Expr):
  __match_args__ = ("name",)

  @override
  def line_col(self) -> tuple[int, int]:
    return (self.name.line, self.name.col)

  def __init__(self, name: Tok3D):
    from src.parse3d.tok import Tok3DType

    super().__init__()
    if name.typ != Tok3DType.IDENT:
      raise ValueError(f"Invalid identifier: {name}")
    self.name: Tok3D = name

  @override
  def __str__(self) -> str:
    return self.name.val

  @override
  def __repr__(self) -> str:
    return self.__str__()

  @override
  def to_bool_z3(self) -> "BoolRef":
    raise TypeError(f"Ident {self.name.val} cannot be converted to BoolRef")

  @override
  def to_arith_z3(self) -> "ArithRef":
    if self.z3_expr is None:
      z3_expr = self.get_vars()[self.name.val]
      self.z3_expr = z3_expr
      return z3_expr
    if not isinstance(self.z3_expr, ArithRef):
      raise TypeError(f"Ident {self.name.val} z3_expr is not ArithRef")
    return self.z3_expr

  @override
  def get_vars(self) -> "Mapping[str, ArithRef]":
    from z3 import Int  # pyright: ignore[reportUnknownVariableType]

    if self.vars is None:
      from z3 import Int  # pyright: ignore[reportUnknownVariableType]

      vars = {self.name.val: Int(self.name.val)}  # pyright: ignore[reportUnknownVariableType]
      self.vars = vars
      return vars  # pyright: ignore[reportUnknownVariableType]
    return self.vars

  @override
  def negate(self) -> "Sequence[Expr]":
    raise TypeError("Ident cannot be negated")


@final
class FunctionCall(Expr):
  __match_args__ = ("name", "args")

  @override
  def line_col(self) -> tuple[int, int]:
    return (self._line, self._col)

  def __init__(
    self, name: Tok3D, args: list[ArithExpr | IntLiteral | Ident | FunctionCall]
  ):
    super().__init__()
    self.name: str = name.val
    self._line: int = name.line
    self._col: int = name.col
    self.args: list[ArithExpr | IntLiteral | Ident | FunctionCall] = args
    self.uuid_map: "dict[str, str]" = {}
    _ = self.make_vars()

  def make_vars(self) -> Mapping[str, ArithRef]:
    if self.vars is None:
      from z3 import Int  # pyright: ignore[reportUnknownVariableType]

      vars: Mapping[str, ArithRef] = {}
      for arg in self.args:
        vars.update(arg.get_vars())
      # make length vars for array types, using @ to avoid name conflict
      if self.name in {"length_array", "length_byte_size_array"}:
        vars[self.make_template_var("len", self.args[0])] = Int(
          self.make_template_var("len", self.args[0])
        )
      # make sizeof var for sizeof, using @ to avoid name conflict
      elif self.name == "sizeof":
        vars[self.make_template_var("sizeof", self.args[0])] = Int(
          self.make_template_var("sizeof", self.args[0])
        )
      self.vars = vars
      return vars
    return self.vars

  @override
  def __str__(self) -> str:
    args_str = ", ".join(str(arg) for arg in self.args)
    return f"{self.name}({args_str})"

  @override
  def __repr__(self) -> str:
    return self.__str__()

  @override
  def to_bool_z3(self) -> "BoolRef":
    raise TypeError("FunctionCall cannot be converted to BoolRef")

  def make_template_var(self, name: str, arg: Expr) -> str:
    if not isinstance(arg, (IntLiteral, Ident)):
      raise TypeError(
        "FunctionCall template variable can only be made from IntLiteral or Ident"
      )

    if f"@{name}_{arg}" in self.uuid_map:
      return self.uuid_map[f"@{name}_{arg}"]

    template_name = f"@{name}({arg})[placeholder]"
    self.uuid_map[f"@{name}_{arg}"] = template_name
    return template_name

  def get_template_var(self, name: "str", arg: "Expr") -> "ArithRef":
    if not isinstance(arg, (IntLiteral, Ident)):
      raise TypeError(
        "FunctionCall template variable can only be made from IntLiteral or Ident"
      )

    if f"@{name}_{arg}" not in self.uuid_map:
      raise ValueError(f"Template variable @{name}_{arg} not found")
    vars = self.make_vars()
    return vars[self.uuid_map[f"@{name}_{arg}"]]

  @override
  def to_arith_z3(self) -> "ArithRef":
    z3_expr = self.z3_expr
    if z3_expr is None:
      if len(self.args) == 0:
        raise ValueError("Supported FunctionCall must have at least one argument")

      _ = self.make_vars()
      match self.name:
        case "sizeof":
          if len(self.args) != 1:
            raise ValueError("sizeof function takes exactly one argument")
          z3_expr = self.get_template_var("sizeof", self.args[0])
          # sizeof constraint cannot be decided if a path in the AST is not taken
          # so currently, we return the variable to handle it later, when each path is computed
        case "length_array":
          if len(self.args) != 1:
            raise ValueError("length_array function takes exactly one argument")
          z3_expr = self.get_template_var("len", self.args[0])
        case "length_byte_size_array":
          if len(self.args) != 1:
            raise ValueError(
              "length_byte_size_array function takes exactly one argument"
            )
          z3_expr = self.get_template_var("len", self.args[0])
        case _:
          raise NotImplementedError(f"Function {self.name} not implemented")
      self.z3_expr = z3_expr
    return z3_expr  # pyright: ignore[reportReturnType]

  @override
  def get_vars(self) -> "Mapping[str, ArithRef]":
    return self.make_vars()

  @override
  def negate(self) -> "Sequence[Expr]":
    raise TypeError("FunctionCall cannot be negated")


@final
class ParenExpr(Expr):
  __match_args__ = ("expr",)

  @override
  def line_col(self) -> tuple[int, int]:
    return self.expr.line_col()

  def __init__(self, expr: Expr):
    super().__init__()
    self.expr: Expr = expr

  @property
  def inner(self) -> Expr:
    return self.expr

  @property
  def is_bool(self) -> bool:
    if isinstance(self.expr, (LogicalExpr, CmpExpr)):
      return True
    elif isinstance(self.expr, (ParenExpr)):
      return self.expr.is_bool
    return False

  @property
  def is_arith(self) -> bool:
    if isinstance(self.expr, (ArithExpr, IntLiteral, Ident, FunctionCall)):
      return True
    elif isinstance(self.expr, (ParenExpr)):
      return self.expr.is_arith
    return False

  @property
  def can_negate(self) -> bool:
    if isinstance(self.expr, (LogicalExpr, CmpExpr)):
      return True
    elif isinstance(self.expr, (ParenExpr)):
      return self.expr.can_negate
    return False

  @override
  def __str__(self) -> str:
    return f"({self.expr})"

  @override
  def __repr__(self) -> str:
    return self.__str__()

  @override
  def to_bool_z3(self) -> "BoolRef":
    return self.expr.to_bool_z3()

  @override
  def to_arith_z3(self) -> "ArithRef":
    return self.expr.to_arith_z3()

  @override
  def get_vars(self) -> "Mapping[str, ArithRef]":
    return self.expr.get_vars()

  @override
  def negate(self) -> "Sequence[Expr]":
    return [ParenExpr(e) for e in self.expr.negate()]


@final
class Nop(Ast):  # A no-op AST node, used as a placeholder
  __match_args__ = ()

  @override
  def line_col(self) -> tuple[int, int]:
    raise NotImplementedError("Nop does not have line and column information")

  def __init__(self):
    super().__init__()
    pass
