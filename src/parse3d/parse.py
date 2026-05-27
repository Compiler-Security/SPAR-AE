from __future__ import annotations
from src.parse3d.ast import (
  ArithExpr,
  CmpExpr,
  FunctionCall,
  Ident,
  IntLiteral,
  LogicalExpr,
  ParenExpr,
)
from typing import TYPE_CHECKING, NoReturn


if TYPE_CHECKING:
  from src.parse3d.ast import (
    Ast,
    Struct,
    Entrypoint,
    CaseType,
    Module,
    FieldDecl,
    CaseBranch,
    TypeExpr,
    LogicalExpr,
    CmpExpr,
    ArithExpr,
    Constraint,
    Ident,
    IntLiteral,
    FunctionCall,
    ParenExpr,
  )
  from src.parse3d.tok import Tok3D


class Parse3D:
  def __init__(self, text: str):
    from src.parse3d.lex import Lex3D
    from src.parse3d.ctx import ParserContext

    self.lexer: "Lex3D" = Lex3D(text)
    self.tokens: list["Tok3D"] = self.lexer.tokenize()
    self.context: "ParserContext" = ParserContext()

  def change_text(self, text: str) -> None:
    from src.parse3d.lex import Lex3D
    from src.parse3d.ctx import ParserContext

    self.lexer = Lex3D(text)
    self.tokens = self.lexer.tokenize()
    self.context = ParserContext()

  @staticmethod
  def token_is(token: "Tok3D", method: str, val: "str | None" = None) -> bool:
    if not hasattr(token, method):
      raise ValueError(f"Token does not have method {method}")

    """
    is_method will be defined in tok.py, by running _attach_is_methods(Tok3D). is_<type> methods
    are dynamically attached to the Tok3D class for each member of the Tok3DType enum.
    Each generated method, when called on an instance of Tok3D, returns True if
    the instance's typ attribute matches the enum member associated with that method, and False otherwise.
    """
    is_method = getattr(token, method)  # pyright: ignore[reportAny]
    if not callable(is_method):  # pyright: ignore[reportAny]
      raise ValueError(f"Token method {method} is not callable")
    if not is_method():
      return False
    if val is not None and token.val != val:
      return False
    return True

  def consume_if_token_is(
    self, method: str, val: str | None = None
  ) -> "Tok3D | NoReturn":
    if not self.tokens:
      raise ValueError("Unexpected end of input")
    tok = self.tokens[0]
    if self.token_is(tok, method, val):
      return self.advance()
    raise ValueError(f"Expected token {method} {val}, got {tok}")

  def advance(self) -> Tok3D:
    if not self.tokens:
      raise ValueError("Unexpected end of input")
    return self.tokens.pop(0)

  def parse(self) -> "Module":
    module = self.handle_module()
    from src.parse3d.resolve import Resolver

    Resolver().visit(module, self.context)
    return module

  def handle_module(self) -> "Module":
    definitions: "dict[str, Struct | CaseType]" = {}
    entrypoint: str | None = None
    from src.parse3d.ast import Module, Entrypoint, Struct, CaseType

    while self.tokens:
      definition = self.handle_definition()
      self.context.reproduce_order.append(
        definition.name
        if not isinstance(definition, Entrypoint)
        else definition.struct.name
      )
      if isinstance(definition, Entrypoint):
        if entrypoint is not None:
          raise ValueError("Multiple entrypoints defined")
        entrypoint = definition.struct.name
        definitions[entrypoint] = definition.struct
      elif isinstance(definition, Struct):
        if definition.name in definitions:
          raise ValueError(f"Duplicate definition of {definition.name}")
        definitions[definition.name] = definition
      elif isinstance(definition, CaseType):  # pyright: ignore[reportUnnecessaryIsInstance]
        if definition.name in definitions:
          raise ValueError(f"Duplicate definition of {definition.name}")
        definitions[definition.name] = definition
      else:
        raise ValueError(f"Unknown definition type: {definition}")
      _ = self.consume_if_token_is("is_semicolon")  # consume ';' after each definition

    # update context

    self.context.defined_structs.update(
      {name: defn for name, defn in definitions.items() if isinstance(defn, Struct)}
    )
    self.context.defined_casetypes.update(
      {name: defn for name, defn in definitions.items() if isinstance(defn, CaseType)}
    )
    self.context.entrypoint = entrypoint
    self.context.true_entrypoint = (
      self.context.typedefs.get(entrypoint, entrypoint) if entrypoint else None
    )

    return Module(definitions, entrypoint)

  def handle_definition(self) -> "Entrypoint | Struct | CaseType":
    if not self.tokens:
      raise ValueError("Unexpected end of input while parsing definition")
    tok = self.tokens[0]
    if self.token_is(tok, "is_kwd", "typedef"):
      return self.handle_typedef()
    elif self.token_is(tok, "is_kwd", "entrypoint"):
      return self.handle_entrypoint()
    elif self.token_is(tok, "is_kwd", "casetype"):
      return self.handle_casetype()
    else:
      raise ValueError(f"Unexpected token {tok} while parsing definition")

  def handle_typedef(self) -> "Struct":
    _ = self.consume_if_token_is("is_kwd", "typedef")
    struct = self.handle_struct()
    def_name = self.consume_if_token_is("is_ident")
    # handle aliasing
    self.context.defined_structs[struct.name] = struct
    self.context.defined_structs[def_name.val] = struct
    self.context.typedefs[def_name.val] = struct.name 
    struct.name = def_name.val
    from copy import deepcopy

    struct_rename = deepcopy(struct)
    struct_rename.name = def_name.val
    return struct_rename

  def handle_struct(self) -> "Struct":
    from src.parse3d.ast import Struct

    if not self.tokens:
      raise ValueError("Unexpected end of input while parsing struct")
    if self.tokens[0].val == "typedef":
      _ = self.advance()  # consume 'typedef'

    # check next token is 'struct'
    _ = self.consume_if_token_is("is_kwd", "struct")

    next_tok = self.tokens[0]
    if not self.token_is(next_tok, "is_ident"):
      from uuid import uuid4
      from src.parse3d.tok import Tok3DType, Tok3D

      name_tok = Tok3D(
        Tok3DType.IDENT,
        f"<anoymous-{str(uuid4())[:4]}>",  # generate a random name for anonymous struct
        next_tok.line,
        next_tok.col,
      )
      name = name_tok.val
    else:
      name_tok = self.consume_if_token_is("is_ident")  # name
      name = name_tok.val

    params = []
    # handle possible parameters
    if self.token_is(self.tokens[0], "is_lparen"):
      _ = self.consume_if_token_is("is_lparen")
      if self.token_is(self.tokens[0], "is_rparen"):
        _ = self.consume_if_token_is("is_rparen")
        ...  # no parameters, nothing to do
      else:
        # parse parameters
        params: list["FieldDecl"] = []
        param0 = self.handle_field_decl()
        params.append(param0)
        while self.tokens and not self.token_is(self.tokens[0], "is_rparen"):
          _ = self.consume_if_token_is("is_comma")
          param = self.handle_field_decl()
          params.append(param)
        _ = self.consume_if_token_is("is_rparen")  # struct name(params **)**

    # handle possible where clause
    constraints = []
    if self.token_is(self.tokens[0], "is_kwd", "where"):
      constraints = self.handle_where_clause()

    _ = self.consume_if_token_is("is_lbrace")

    fields: list["FieldDecl"] = []
    while self.tokens and not self.token_is(self.tokens[0], "is_rbrace"):
      field = self.handle_field_decl()
      fields.append(field)
      _ = self.consume_if_token_is(
        "is_semicolon"
      )  # consume ';' after each field, do this because i want to reuse handle_field_decl

    _ = self.consume_if_token_is("is_rbrace")

    self.context.defined_structs[name] = Struct(
      name_tok,
      fields,
      params,
      constraints,
    )
    for field in fields:
      field.belongs_to = self.context.defined_structs[name]
    return self.context.defined_structs[name]

  def handle_entrypoint(self) -> "Entrypoint":
    from src.parse3d.ast import Entrypoint

    # consume 'entrypoint'
    _ = self.advance()
    if self.token_is(self.tokens[0], "is_kwd", "struct"):
      struct = self.handle_struct()
    elif self.token_is(self.tokens[0], "is_kwd", "typedef"):
      struct = self.handle_typedef()
    else:
      raise ValueError("Expected 'struct' or 'typedef' after 'entrypoint'")
    return Entrypoint(struct)

  def handle_where_clause(self) -> "list[Constraint]":
    from src.parse3d.ast import (
      Constraint,
      CmpExpr,
      LogicalExpr,
      ParenExpr,
    )

    _ = self.consume_if_token_is("is_kwd", "where")
    constraint = self.handle_logical_expr()
    if isinstance(constraint, ParenExpr):
      expr = constraint.inner
      while isinstance(expr, ParenExpr):
        expr = expr.inner
    else:
      expr = constraint
    if not isinstance(
      expr,
      (Constraint, CmpExpr, LogicalExpr),
    ):
      raise ValueError("Where clause must be a constraint expression")

    return [Constraint(expr)]

  def handle_casetype(self) -> "CaseType":
    from src.parse3d.ast import CaseType

    # consume 'casetype'
    _ = self.advance()
    name_tok = self.consume_if_token_is("is_ident")  # casetype **name**
    _ = self.consume_if_token_is("is_lparen")
    if self.token_is(self.tokens[0], "is_rparen"):
      raise ValueError("Casetype must have at least one case variable")
    # parse case variables
    case_variables: list["FieldDecl"] = []
    field0 = self.handle_field_decl()
    case_variables.append(field0)
    while self.tokens and not self.token_is(self.tokens[0], "is_rparen"):
      _ = self.consume_if_token_is("is_comma")
      field = self.handle_field_decl()
      case_variables.append(field)
    _ = self.consume_if_token_is("is_rparen")  # casetype name(case_variables **)**

    # parse possible where clause
    constraints = []
    if self.token_is(self.tokens[0], "is_kwd", "where"):
      constraints = self.handle_where_clause()

    _ = self.consume_if_token_is("is_lbrace")
    cases: dict[str, CaseBranch] = {}
    _ = self.consume_if_token_is("is_kwd", "switch")
    _ = self.consume_if_token_is("is_lparen")
    switch_var = self.consume_if_token_is("is_ident")
    _ = self.consume_if_token_is("is_rparen")
    _ = self.consume_if_token_is("is_lbrace")
    while self.tokens and not self.token_is(self.tokens[0], "is_rbrace"):
      case = self.handle_case()
      if case.value.val in cases:
        raise ValueError(f"Duplicate case value {case.value.val}")
      cases[case.value.val] = case
    _ = self.consume_if_token_is("is_rbrace")
    _ = self.consume_if_token_is("is_rbrace")

    if not self.tokens:
      raise ValueError("Unexpected end of input after casetype definition")
    next_tok = self.tokens[0]
    if not self.token_is(next_tok, "is_ident"):
      case_type = CaseType(
        name_tok, case_variables, cases, switch_var, args_constraints=constraints
      )
      for case_var in case_variables:
        case_var.belongs_to = case_type
      for case in cases.values():
        case.field.belongs_to = case_type
      return case_type
    else:
      def_name = next_tok.val
      _ = self.advance()
      # handle aliasing
      self.context.defined_casetypes[def_name] = CaseType(
        name_tok, case_variables, cases, switch_var, args_constraints=constraints
      )
      for case_var in case_variables:
        case_var.belongs_to = self.context.defined_casetypes[def_name]
      for case in cases.values():
        case.field.belongs_to = self.context.defined_casetypes[def_name]
      return self.context.defined_casetypes[def_name]

  def handle_field_decl(self) -> "FieldDecl":
    from src.parse3d.ast import (
      FieldDecl,
      PrimitiveType,
      ArrayType,
      IntLiteral,
      Ident,
      ParenExpr,
      ArithExpr,
    )

    type_expr = self.handle_type_expr()
    name_tok = self.consume_if_token_is("is_ident")
    name = name_tok.val
    next_token = self.tokens[0]
    bitwidth = None
    bitwidth_tok = None
    if self.token_is(next_token, "is_semicolon"):
      return FieldDecl(name, type_expr)
    elif self.token_is(next_token, "is_colon"):
      _ = self.advance()
      bitwidth_tok = self.consume_if_token_is("is_int")
      bitwidth = int(bitwidth_tok.val)
      if not isinstance(type_expr, PrimitiveType):
        raise ValueError("Bitwidth can only be specified for primitive types")
      if bitwidth <= 0:
        raise ValueError("Bitwidth must be positive")
      type_expr.bits = bitwidth

    next_token = self.tokens[0]
    if self.token_is(next_token, "is_semicolon"):
      return FieldDecl(name, type_expr)
    elif self.token_is(next_token, "is_lbrace"):
      constraint = self.handle_constraint()
      if self.token_is(self.tokens[0], "is_semicolon"):
        return FieldDecl(name, type_expr, constraint)
    elif self.token_is(next_token, "is_lbracket"):
      is_byte_size = False
      _ = self.consume_if_token_is("is_lbracket")

      if len(self.tokens) < 2:
        raise ValueError("Unexpected end of input while parsing array size")
      if self.token_is(self.tokens[0], "is_colon") and self.token_is(
        self.tokens[1], "is_byte_size"
      ):
        _ = self.consume_if_token_is("is_colon")
        _ = self.consume_if_token_is("is_byte_size")
        is_byte_size = True

      size_expr = self.handle_logical_expr()

      if not isinstance(size_expr, (IntLiteral, Ident, ParenExpr, ArithExpr)):
        raise ValueError("Array size must be an integer literal or expression")

      _ = self.consume_if_token_is("is_rbracket")

      array_type = ArrayType(type_expr, size_expr, is_byte_size)
      return FieldDecl(name, array_type)
    else:
      return FieldDecl(name, type_expr)
    raise ValueError(f"Expected ';' or '{{', got {next_token}")

  def handle_case(self) -> "CaseBranch":
    from src.parse3d.ast import CaseBranch

    _ = self.consume_if_token_is("is_kwd", "case")
    value_tok = self.consume_if_token_is("is_int")  # only support int case
    _ = self.consume_if_token_is("is_colon")
    field = self.handle_field_decl()
    _ = self.consume_if_token_is("is_semicolon")
    return CaseBranch(value_tok, field)

  def handle_type_expr(self) -> "TypeExpr":
    from src.parse3d.ast import (
      PrimitiveType,
      StructNameType,
      EmptyType,
      StructType,
    )

    tok = self.tokens[0]
    if self.token_is(tok, "is_ident"):
      type_name = self.consume_if_token_is("is_ident")
      if type_name.val in {
        "UINT8BE",
        "UINT16BE",
        "UINT32BE",
        "UINT64BE",
      }:
        bits = int(type_name.val[4:-2])
        return PrimitiveType(type_name, bits)
      else:
        struct_name = type_name
        if not self.tokens:
          raise ValueError("Unexpected end of input after type name")
        if self.token_is(self.tokens[0], "is_lparen"):
          _ = self.consume_if_token_is("is_lparen")
          args: list[
            ArithExpr
            | IntLiteral
            | Ident
            | LogicalExpr
            | CmpExpr
            | FunctionCall
            | ParenExpr
          ] = []
          if not self.token_is(self.tokens[0], "is_rparen"):
            arg0: (
              ArithExpr
              | IntLiteral
              | Ident
              | LogicalExpr
              | CmpExpr
              | FunctionCall
              | ParenExpr
            ) = self.handle_arith_expr()
            args.append(arg0)
            while self.tokens and not self.token_is(self.tokens[0], "is_rparen"):
              _ = self.consume_if_token_is("is_comma")
              arg: (
                ArithExpr
                | IntLiteral
                | Ident
                | LogicalExpr
                | CmpExpr
                | FunctionCall
                | ParenExpr
                | TypeExpr
              ) = self.handle_arith_expr()
              args.append(arg)
          _ = self.consume_if_token_is("is_rparen")
          for arg in args:
            arg.is_argument = True
          return StructNameType(struct_name, args=args)  # not resolved yet
        return StructNameType(struct_name)  # not resolved yet
    elif self.token_is(tok, "is_kwd", "unit"):
      unit = self.advance()  # consume 'unit'
      return EmptyType(unit.line, unit.col)
    elif self.token_is(tok, "is_kwd", "struct"):
      struct = self.handle_struct()
      return StructType(struct)
    else:
      raise ValueError(f"Unexpected token {tok} while parsing type expression")

  def handle_constraint(self) -> "Constraint":
    from src.parse3d.ast import Constraint, CmpExpr, LogicalExpr

    _ = self.consume_if_token_is("is_lbrace")
    expr = self.handle_logical_expr()
    _ = self.consume_if_token_is("is_rbrace")
    if not isinstance(expr, (CmpExpr, LogicalExpr, ParenExpr)):
      raise ValueError("Constraint must be a comparison or logical expression")
    if isinstance(expr, ParenExpr):
      inner_expr = expr.inner
      while isinstance(inner_expr, ParenExpr):
        inner_expr = inner_expr.inner
      expr = inner_expr
      if not isinstance(expr, (CmpExpr, LogicalExpr)):
        raise ValueError("Constraint must be a comparison or logical expression")
    return Constraint(expr)

  def handle_logical_expr(
    self,
  ) -> (
    "LogicalExpr | CmpExpr | ArithExpr | IntLiteral | Ident | FunctionCall | ParenExpr"
  ):
    from src.parse3d.ast import LogicalExpr

    left = self.handle_cmp_expr()
    while self.tokens and self.token_is(self.tokens[0], "is_logop"):
      op_tok = self.consume_if_token_is("is_logop")
      right = self.handle_cmp_expr()
      left = LogicalExpr(op_tok, left, right)
    return left

  def handle_cmp_expr(
    self,
  ) -> (
    "CmpExpr | ArithExpr | IntLiteral | Ident | LogicalExpr | FunctionCall | ParenExpr"
  ):
    from src.parse3d.ast import CmpExpr

    left = self.handle_arith_expr()
    while self.tokens and self.token_is(self.tokens[0], "is_cmpop"):
      op_tok = self.consume_if_token_is("is_cmpop")
      right = self.handle_arith_expr()
      left = CmpExpr(op_tok, left, right)
    return left

  def handle_arith_expr(
    self,
  ) -> (
    "ArithExpr | IntLiteral | Ident | LogicalExpr | CmpExpr | FunctionCall | ParenExpr"
  ):
    from src.parse3d.ast import ArithExpr

    left = self.handle_primary()
    while self.tokens and self.token_is(self.tokens[0], "is_arithop"):
      op_tok = self.consume_if_token_is("is_arithop")
      right = self.handle_primary()
      left = ArithExpr(op_tok, left, right)
    return left

  def handle_primary(
    self,
  ) -> (
    "IntLiteral | Ident | LogicalExpr | CmpExpr | ArithExpr | FunctionCall | ParenExpr"
  ):
    from src.parse3d.ast import IntLiteral, Ident, ParenExpr

    tok = self.tokens[0]
    if self.token_is(tok, "is_int"):
      int_tok = self.consume_if_token_is("is_int")
      return IntLiteral(int_tok)
    elif self.token_is(tok, "is_ident"):
      # could be function call
      if len(self.tokens) > 1 and self.token_is(self.tokens[1], "is_lparen"):
        return self.handle_function_call()
      ident_tok = self.consume_if_token_is("is_ident")
      return Ident(ident_tok)
    elif self.token_is(tok, "is_lparen"):
      _ = self.consume_if_token_is("is_lparen")
      expr = self.handle_logical_expr()
      _ = self.consume_if_token_is("is_rparen")
      return ParenExpr(expr)
    else:
      raise ValueError(f"Unexpected token {tok} while parsing primary expression")

  def handle_function_call(self) -> "FunctionCall":
    from src.parse3d.ast import FunctionCall, ArithExpr, IntLiteral, Ident

    func_name_tok = self.consume_if_token_is("is_ident")
    func_name = func_name_tok
    _ = self.consume_if_token_is("is_lparen")
    args: list["ArithExpr | IntLiteral | Ident | FunctionCall"] = []
    if not self.token_is(self.tokens[0], "is_rparen"):
      arg0 = self.handle_arith_expr()
      if not isinstance(arg0, (ArithExpr, IntLiteral, Ident, FunctionCall)):
        raise ValueError("Function argument must be an arithmetic expression")
      args.append(arg0)
      while self.tokens and not self.token_is(self.tokens[0], "is_rparen"):
        _ = self.consume_if_token_is("is_comma")
        arg = self.handle_arith_expr()
        if not isinstance(arg, (ArithExpr, IntLiteral, Ident, FunctionCall)):
          raise ValueError("Function argument must be an arithmetic expression")
        args.append(arg)
    _ = self.consume_if_token_is("is_rparen")
    return FunctionCall(func_name, args)
