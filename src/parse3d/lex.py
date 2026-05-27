from __future__ import annotations
import builtins
import typing
import sys
import os

sys.path.append(os.path.abspath("../../"))

if typing.TYPE_CHECKING:
  from src.parse3d.tok import Tok3DType, Tok3D


class LexicalError(Exception):
  def __init__(self, message: str, line: int, col: int):
    super().__init__(f"Lexical error at line {line}, column {col}: {message}")
    self.line: int = line
    self.col: int = col
    self.message: str = message


class Lex3D:
  def __init__(self, text: str):
    self.text: str = text
    self.pos: int = 0
    self.current_char: str | None = self.text[self.pos] if self.text else None
    self.line: int = 1
    self.col: int = 1
    self.length: int = len(text)
    self.keywords: set[str] = {
      "typedef",
      "struct",
      "casetype",
      "case",
      "switch",
      "entrypoint",
      "byte-size",
      "unit",
      "and",
      "or",
      "not",
      "where",
    }
    self.arith_ops: set[str] = {"+", "-", "*", "/", "%"}
    self.cmp_ops: set[str] = {"==", "!=", "<", "<=", ">", ">="}
    self.log_ops: set[str] = {"&&", "||"}
    from src.parse3d.tok import Tok3DType

    self.single_char_tokens: dict[str, Tok3DType] = {
      "{": Tok3DType.LBRACE,
      "}": Tok3DType.RBRACE,
      "(": Tok3DType.LPAREN,
      ")": Tok3DType.RPAREN,
      "[": Tok3DType.LBRACKET,
      "]": Tok3DType.RBRACKET,
      ";": Tok3DType.SEMICOLON,
      ",": Tok3DType.COMMA,
      ":": Tok3DType.COLON,
    }

    self.log_ops_alias: dict[str, str] = {
      "and": "&&",
      "or": "||",
      "not": "!",
    }

  def error(self) -> typing.NoReturn:
    raise LexicalError(f"Invalid character : {self.current_char}", self.line, self.col)

  def skip_whitespace(self) -> None:
    while self.current_char is not None and self.current_char.isspace():
      self.advance()

  def skip_comment(self) -> None:
    if self.current_char == "/" and self.peek() == "/":
      while self.current_char is not None and self.current_char != "\n":  # pyright: ignore[reportUnnecessaryComparison]
        self.advance()
      self.advance()  # Skip the newline character
    elif self.current_char == "/" and self.peek() == "*":
      self.advance()  # Skip the '/'
      self.advance()  # Skip the '*'
      while self.current_char is not None:  # pyright: ignore[reportUnnecessaryComparison]
        if self.current_char == "*" and self.peek() == "/":  # pyright: ignore[reportUnnecessaryComparison]
          self.advance()  # Skip the '*'
          self.advance()  # Skip the '/'
          break
        if self.current_char is None:  # pyright: ignore[reportUnnecessaryComparison]
          raise LexicalError("Unterminated multi-line comment", self.line, self.col)
        self.advance()

  def advance(self) -> None:
    if self.current_char == "\n":  # Checks the character at the OLD position
      self.line += 1
      self.col = 0
    self.pos += 1
    self.col += 1  # This is always executed
    if self.pos >= self.length:
      self.current_char = None
    else:
      self.current_char = self.text[
        self.pos
      ]  # Updates to the character at the NEW position

  def peek(self) -> str | None:
    peek_pos = self.pos + 1
    if peek_pos >= self.length:
      return None
    else:
      return self.text[peek_pos]

  def integer(self) -> "Tok3D":
    result = ""
    start_col = self.col
    while self.current_char is not None and self.current_char.isdigit():
      result += self.current_char
      self.advance()
    from src.parse3d.tok import Tok3DType, Tok3D

    return Tok3D(Tok3DType.INT, result, self.line, start_col)

  def hex_integer(self) -> "Tok3D":
    result = ""
    start_col = self.col
    if self.current_char == "0" and self.peek() in ("x", "X"):
      result += self.current_char  # '0'
      self.advance()
      result += self.current_char  # 'x' or 'X'
      self.advance()
    while self.current_char is not None and (
      self.current_char.isdigit() or self.current_char.lower() in "abcdef"
    ):
      result += self.current_char
      self.advance()
    from src.parse3d.tok import Tok3DType, Tok3D

    return Tok3D(Tok3DType.INT, str(int(result, 16)), self.line, start_col)

  def byte_size(self) -> "Tok3D":
    line = self.line
    col = self.col
    pos = self.pos
    result = ""
    start_col = self.col
    if self.current_char == "b":
      result += self.current_char
      self.advance()
      expected = "yte-size"
      for char in expected:
        if self.current_char == char:
          self.advance()
        else:
          self.line = line
          self.col = col
          self.pos = pos
          self.current_char = self.text[self.pos] if self.pos < self.length else None
          raise LexicalError("Not byte-size token", line, col)

      from src.parse3d.tok import Tok3D, Tok3DType

      return Tok3D(Tok3DType.BYTE_SIZE, "byte-size", self.line, start_col)
    else:
      self.line = line
      self.col = col
      self.pos = pos
      self.current_char = self.text[self.pos] if self.pos < self.length else None
      raise LexicalError("Not byte-size token", line, col)

  def identifier(self) -> "Tok3D":
    from src.parse3d.tok import Tok3DType

    result: str = ""
    start_col: int = self.col
    while self.current_char is not None and (
      self.current_char.isalnum() or self.current_char == "_"
    ):
      result += self.current_char
      self.advance()
    tok_type = Tok3DType.KWD if result in self.keywords else Tok3DType.IDENT
    from src.parse3d.tok import Tok3D

    from uuid import uuid4

    # if result clashes with python's built-in functions or methods, we want to report an error
    if result in dir(builtins):
      result = f"{result}_{uuid4().hex[:8]}"  # Avoid clash by appending a unique suffix
      # raise LexicalError(
      #   f"Identifier '{result}' clashes with Python built-in names",
      #   self.line,
      #   start_col,
      # )

    return Tok3D(tok_type, result, self.line, start_col)

  def get_next_token(self) -> "Tok3D | None":
    from src.parse3d.tok import Tok3DType, Tok3D

    curr_place = (self.line, self.col)
    changed = True
    while changed:
      self.skip_whitespace()
      self.skip_comment()
      changed = curr_place != (self.line, self.col)
      curr_place = (self.line, self.col)
    while self.current_char is not None:
      if self.current_char == "b":
        try:
          return self.byte_size()
        except LexicalError:
          pass  # Not a byte-size, fall through to identifier

      if self.current_char.isalpha() or self.current_char == "_":
        ident = self.identifier()
        if ident.val in self.log_ops_alias:
          return Tok3D(
            Tok3DType.LOGOP,
            self.log_ops_alias[ident.val],
            ident.line,
            ident.col,
          )
        return ident

      if self.current_char == "0" and self.peek() in ("x", "X"):
        return self.hex_integer()
      if self.current_char.isdigit():
        return self.integer()
      if self.current_char in self.single_char_tokens:
        tok_type = self.single_char_tokens[self.current_char]
        tok = Tok3D(tok_type, self.current_char, self.line, self.col)
        self.advance()
        return tok

      # Handle multi-character operators
      if self.current_char in {"+", "-", "*", "/", "%"}:
        start_col = self.col
        op = self.current_char
        self.advance()
        if op in self.arith_ops:
          return Tok3D(Tok3DType.ARITHOP, op, self.line, start_col)
        else:
          self.error()

      if self.current_char in {"=", "!", "<", ">"}:
        start_col = self.col
        op = self.current_char
        next_char = self.peek()
        if next_char == "=":
          op += next_char
          self.advance()
          if op in self.cmp_ops:
            self.advance()
            return Tok3D(Tok3DType.CMPOP, op, self.line, start_col)
        self.advance()
        if op in self.cmp_ops:
          return Tok3D(Tok3DType.CMPOP, op, self.line, start_col)
        elif op in self.log_ops_alias.values():
          return Tok3D(Tok3DType.LOGOP, self.log_ops_alias[op], self.line, start_col)
        elif op == '=':
          self.error()
        # if op in self.cmp_ops:
        #   return Tok3D(Tok3DType.CMPOP, op, self.line, start_col)
        # else:
        #   self.error()

      if self.current_char in {"&", "|"}:
        start_col = self.col
        op = self.current_char
        next_char = self.peek()
        if next_char is not None and next_char == op:  # && or ||
          op += next_char
          self.advance()
          self.advance()
          if op in self.log_ops:
            return Tok3D(Tok3DType.LOGOP, op, self.line, start_col)
          else:
            self.error()
        else:
          self.error()

      self.error()

    return None

  def tokenize(self) -> list["Tok3D"]:
    tokens: list["Tok3D"] = []
    while True:
      token = self.get_next_token()
      if token is None:
        break
      tokens.append(token)
    return tokens
