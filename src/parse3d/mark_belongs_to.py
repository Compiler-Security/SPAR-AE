from __future__ import annotations
from typing import TYPE_CHECKING
from src.parse3d.ast_visitor import AstVisitor

if TYPE_CHECKING:
  from src.parse3d.ast import Struct, CaseType, FieldDecl


class MarkBelongsTo(AstVisitor): ...
