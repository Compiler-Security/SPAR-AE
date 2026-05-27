from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.parse3d.ast import (
        ArithExpr,
        CmpExpr,
        Constraint,
        CaseBranch,
        CaseType,
        EmptyType,
        Expr,
        FieldDecl,
        FunctionCall,
        Ident,
        IntLiteral,
        LogicalExpr,
        ParenExpr,
        PrimitiveType,
        Struct,
        StructNameType,
        StructType,
        TypeExpr,
    )
    from src.parse3d.ast import ArrayType


@dataclass
class EvalFieldMatch:
    position: int
    field_name_gt: str | None
    field_name_gen: str | None
    type_gt: str
    type_gen: str | None
    type_match: bool
    type_detail: str | None
    constraint_gt: str | None
    constraint_gen: str | None
    constraint_match: bool | None
    constraint_detail: str | None
    nested: EvalResult | None = None


@dataclass
class EvalResult:
    definition_name_gt: str
    definition_name_gen: str
    definition_kind: str
    field_matches: list[EvalFieldMatch] = field(default_factory=list)
    total_fields: int = 0
    matched_fields: int = 0
    has_type_mismatch: bool = False
    has_constraint_mismatch: bool = False

    @property
    def match_ratio(self) -> float:
        if self.total_fields == 0:
            return 1.0
        return self.matched_fields / self.total_fields

    @property
    def passed(self) -> bool:
        return (
            not self.has_type_mismatch
            and not self.has_constraint_mismatch
            and self.total_fields == len(self.field_matches)
        )

    def __repr__(self) -> str:
        return (
            f"EvalResult(gt={self.definition_name_gt}, gen={self.definition_name_gen}, "
            f"kind={self.definition_kind}, ratio={self.match_ratio:.2f}, "
            f"matched={self.matched_fields}/{self.total_fields})"
        )


@dataclass
class EvalSummary:
    gt_entrypoint: str
    gen_entrypoint: str | None
    has_entrypoint: bool
    definition_results: list[EvalResult] = field(default_factory=list)
    fully_matched_defs: int = 0
    partially_matched_defs: int = 0
    total_types_visited: int = 0

    @property
    def overall_score(self) -> float:
        if not self.definition_results:
            return 0.0
        return sum(r.match_ratio for r in self.definition_results) / len(
            self.definition_results
        )

    @property
    def strict_pass(self) -> bool:
        return self.has_entrypoint and all(
            r.passed for r in self.definition_results
        )

    def __repr__(self) -> str:
        return (
            f"EvalSummary(score={self.overall_score:.2f}, "
            f"strict_pass={self.strict_pass}, "
            f"defs={self.total_types_visited}, "
            f"full_match={self.fully_matched_defs})"
        )


class AutoEvaluator:
    def __init__(self, gt_text: str, gen_text: str):
        from src.parse3d.parse import Parse3D

        self.gt_module = Parse3D(gt_text).parse()
        self.gen_module = Parse3D(gen_text).parse()
        self._visited: set[tuple[int, int]] = set()
        self._compared: set[tuple[int, int]] = set()
        self._definition_results: list[EvalResult] = []

    def evaluate(self) -> EvalSummary:
        gt_entrypoint = self.gt_module.get_entrypoint_struct()
        gt_entry_name = gt_entrypoint.name

        gen_entry_name: str | None = None
        has_entrypoint = self.gen_module.has_entrypoint()

        if has_entrypoint:
            gen_entry = self.gen_module.get_entrypoint_struct()
            gen_entry_name = gen_entry.name
        else:
            return EvalSummary(
                gt_entrypoint=gt_entry_name,
                gen_entrypoint=None,
                has_entrypoint=False,
            )

        self._definition_results = []
        self._compare_definition(gt_entrypoint, gen_entry)

        fully = sum(1 for r in self._definition_results if r.passed)
        partial = sum(
            1
            for r in self._definition_results
            if not r.passed and r.match_ratio > 0
        )

        return EvalSummary(
            gt_entrypoint=gt_entry_name,
            gen_entrypoint=gen_entry_name,
            has_entrypoint=True,
            definition_results=list(self._definition_results),
            fully_matched_defs=fully,
            partially_matched_defs=partial,
            total_types_visited=len(self._definition_results),
        )

    # -- Definition dispatch --------------------------------------------------

    def _compare_definition(
        self,
        gt_def: Struct | CaseType,
        gen_def: Struct | CaseType,
        parent_field_gt: str | None = None,
        parent_field_gen: str | None = None,
    ) -> EvalResult:
        from src.parse3d.ast import CaseType, Struct

        pair_id = (id(gt_def), id(gen_def))

        # Recursion guard: if already on the call stack, return shallow match
        if pair_id in self._visited:
            max_f = max(
                len(gt_def.fields) if isinstance(gt_def, Struct) else len(gt_def.cases),
                len(gen_def.fields) if isinstance(gen_def, Struct) else len(gen_def.cases),
            )
            return EvalResult(
                definition_name_gt=parent_field_gt or gt_def.name,
                definition_name_gen=parent_field_gen or gen_def.name,
                definition_kind="struct" if isinstance(gt_def, Struct) else "casetype",
                total_fields=max_f,
                matched_fields=max_f,
            )

        # Already fully compared this pair — skip (prevents duplicate entries)
        if pair_id in self._compared:
            max_f = max(
                len(gt_def.fields) if isinstance(gt_def, Struct) else len(gt_def.cases),
                len(gen_def.fields) if isinstance(gen_def, Struct) else len(gen_def.cases),
            )
            return EvalResult(
                definition_name_gt=parent_field_gt or gt_def.name,
                definition_name_gen=parent_field_gen or gen_def.name,
                definition_kind="struct" if isinstance(gt_def, Struct) else "casetype",
                total_fields=max_f,
                matched_fields=max_f,
            )

        self._visited.add(pair_id)
        try:
            if isinstance(gt_def, Struct) and isinstance(gen_def, Struct):
                return self._compare_struct(
                    gt_def, gen_def, parent_field_gt, parent_field_gen
                )
            if isinstance(gt_def, CaseType) and isinstance(gen_def, CaseType):
                return self._compare_casetype(gt_def, gen_def)

            return EvalResult(
                definition_name_gt=parent_field_gt or gt_def.name,
                definition_name_gen=parent_field_gen or gen_def.name,
                definition_kind="struct" if isinstance(gt_def, Struct) else "casetype",
                has_type_mismatch=True,
            )
        finally:
            self._visited.discard(pair_id)

    # -- Struct ---------------------------------------------------------------

    def _compare_struct(
        self,
        gt: Struct,
        gen: Struct,
        parent_field_gt: str | None = None,
        parent_field_gen: str | None = None,
    ) -> EvalResult:
        from src.parse3d.ast import PrimitiveType

        pair_id = (id(gt), id(gen))
        self._compared.add(pair_id)

        rename_map: dict[str, str] = {}
        max_len = max(len(gt.fields), len(gen.fields))
        for i in range(min(len(gt.fields), len(gen.fields))):
            if gt.fields[i].name != gen.fields[i].name:
                rename_map[gen.fields[i].name] = gt.fields[i].name

        # Build type info for Z3 unsigned bounds
        var_types: dict[str, tuple[str, int]] = {}
        for fd in gt.fields:
            typ = fd.typ
            if isinstance(typ, PrimitiveType):
                var_types[fd.name] = (typ.name, typ.bits)

        field_matches: list[EvalFieldMatch] = []
        matched_count = 0
        has_type_mismatch = False
        has_constraint_mismatch = False

        for i in range(max_len):
            if i < len(gt.fields) and i < len(gen.fields):
                fm = self._compare_field(gt.fields[i], gen.fields[i], i, rename_map, var_types)
                if fm.type_match and fm.constraint_match is not False:
                    matched_count += 1
                if not fm.type_match:
                    has_type_mismatch = True
                if fm.constraint_match is False:
                    has_constraint_mismatch = True
                field_matches.append(fm)
            elif i < len(gt.fields):
                gf = gt.fields[i]
                field_matches.append(
                    EvalFieldMatch(
                        position=i,
                        field_name_gt=gf.name,
                        field_name_gen=None,
                        type_gt=self._type_str(gf.typ),
                        type_gen=None,
                        type_match=False,
                        type_detail="Missing field in generated",
                        constraint_gt=str(gf.constraint) if gf.constraint else None,
                        constraint_gen=None,
                        constraint_match=None,
                        constraint_detail="Missing field in generated",
                    )
                )
                has_type_mismatch = True
            else:
                gf = gen.fields[i]
                field_matches.append(
                    EvalFieldMatch(
                        position=i,
                        field_name_gt=None,
                        field_name_gen=gf.name,
                        type_gt="(none)",
                        type_gen=self._type_str(gf.typ),
                        type_match=False,
                        type_detail="Extra field in generated",
                        constraint_gt=None,
                        constraint_gen=str(gf.constraint) if gf.constraint else None,
                        constraint_match=None,
                        constraint_detail="Extra field in generated",
                    )
                )
                has_type_mismatch = True

        gt_name = parent_field_gt or gt.name
        gen_name = parent_field_gen or gen.name

        parent_result = EvalResult(
            definition_name_gt=gt_name,
            definition_name_gen=gen_name,
            definition_kind="struct",
            field_matches=field_matches,
            total_fields=max_len,
            matched_fields=matched_count,
            has_type_mismatch=has_type_mismatch,
            has_constraint_mismatch=has_constraint_mismatch,
        )
        self._definition_results.append(parent_result)
        return parent_result

    # -- CaseType -------------------------------------------------------------

    def _compare_casetype(self, gt: CaseType, gen: CaseType) -> EvalResult:
        from src.parse3d.ast import FieldDecl, PrimitiveType

        pair_id = (id(gt), id(gen))
        self._compared.add(pair_id)

        # Compare case variables (parameters) positionally
        cv_rename_map: dict[str, str] = {}
        for i in range(min(len(gt.case_variables), len(gen.case_variables))):
            if gt.case_variables[i].name != gen.case_variables[i].name:
                cv_rename_map[gen.case_variables[i].name] = gt.case_variables[i].name

        # Build type info for case variable Z3 unsigned bounds
        cv_var_types: dict[str, tuple[str, int]] = {}
        for cv in gt.case_variables:
            if isinstance(cv.typ, PrimitiveType):
                cv_var_types[cv.name] = (cv.typ.name, cv.typ.bits)

        # Sort cases by integer value
        sorted_gt = sorted(gt.cases.items(), key=lambda kv: int(kv[0]))
        sorted_gen = sorted(gen.cases.items(), key=lambda kv: int(kv[0]))

        field_matches: list[EvalFieldMatch] = []
        matched_count = 0
        has_type_mismatch = False
        has_constraint_mismatch = False
        max_len = max(len(sorted_gt), len(sorted_gen))

        for i in range(max_len):
            if i < len(sorted_gt) and i < len(sorted_gen):
                gt_val, gt_branch = sorted_gt[i]
                gen_val, gen_branch = sorted_gen[i]

                if gt_val != gen_val:
                    fm = EvalFieldMatch(
                        position=i,
                        field_name_gt=f"case {gt_val}",
                        field_name_gen=f"case {gen_val}",
                        type_gt=self._type_str(gt_branch.field.typ),
                        type_gen=self._type_str(gen_branch.field.typ),
                        type_match=False,
                        type_detail=f"Case value mismatch: expected {gt_val}, got {gen_val}",
                        constraint_gt=str(gt_branch.field.constraint) if gt_branch.field.constraint else None,
                        constraint_gen=str(gen_branch.field.constraint) if gen_branch.field.constraint else None,
                        constraint_match=None,
                        constraint_detail="Case value mismatch",
                    )
                    has_type_mismatch = True
                    field_matches.append(fm)
                    continue

                # _compare_field handles type comparison, constraint comparison,
                # and recursive descent into nested struct/casetype references
                fm = self._compare_field(
                    gt_branch.field, gen_branch.field, i, cv_rename_map, cv_var_types
                )
                if fm.type_match and fm.constraint_match is not False:
                    matched_count += 1
                if not fm.type_match:
                    has_type_mismatch = True
                if fm.constraint_match is False:
                    has_constraint_mismatch = True
                field_matches.append(fm)

            elif i < len(sorted_gt):
                gt_val, gt_branch = sorted_gt[i]
                fm = EvalFieldMatch(
                    position=i,
                    field_name_gt=f"case {gt_val}",
                    field_name_gen=None,
                    type_gt=self._type_str(gt_branch.field.typ),
                    type_gen=None,
                    type_match=False,
                    type_detail="Missing case in generated",
                    constraint_gt=str(gt_branch.field.constraint) if gt_branch.field.constraint else None,
                    constraint_gen=None,
                    constraint_match=None,
                    constraint_detail="Missing case in generated",
                )
                has_type_mismatch = True
                field_matches.append(fm)
            else:
                gen_val, gen_branch = sorted_gen[i]
                fm = EvalFieldMatch(
                    position=i,
                    field_name_gt=None,
                    field_name_gen=f"case {gen_val}",
                    type_gt="(none)",
                    type_gen=self._type_str(gen_branch.field.typ),
                    type_match=False,
                    type_detail="Extra case in generated",
                    constraint_gt=None,
                    constraint_gen=str(gen_branch.field.constraint) if gen_branch.field.constraint else None,
                    constraint_match=None,
                    constraint_detail="Extra case in generated",
                )
                has_type_mismatch = True
                field_matches.append(fm)

        parent_result = EvalResult(
            definition_name_gt=gt.name,
            definition_name_gen=gen.name,
            definition_kind="casetype",
            field_matches=field_matches,
            total_fields=max_len,
            matched_fields=matched_count,
            has_type_mismatch=has_type_mismatch,
            has_constraint_mismatch=has_constraint_mismatch,
        )
        self._definition_results.append(parent_result)
        return parent_result

    # -- Field ----------------------------------------------------------------

    def _compare_field(
        self,
        gt_fd: FieldDecl,
        gen_fd: FieldDecl,
        pos: int,
        rename_map: dict[str, str],
        var_types: dict[str, tuple[str, int]] | None = None,
    ) -> EvalFieldMatch:
        type_ok, type_detail = self._compare_types(
            gt_fd.typ, gen_fd.typ, rename_map
        )
        constraint_ok, constraint_detail = self._compare_constraint(
            gt_fd.constraint, gen_fd.constraint, rename_map, var_types
        )

        fm = EvalFieldMatch(
            position=pos,
            field_name_gt=gt_fd.name,
            field_name_gen=gen_fd.name,
            type_gt=self._type_str(gt_fd.typ),
            type_gen=self._type_str(gen_fd.typ),
            type_match=type_ok,
            type_detail=type_detail,
            constraint_gt=str(gt_fd.constraint) if gt_fd.constraint else None,
            constraint_gen=str(gen_fd.constraint) if gen_fd.constraint else None,
            constraint_match=constraint_ok,
            constraint_detail=constraint_detail,
        )

        # Recurse into nested struct/casetype references
        self._recurse_into_type(gt_fd.typ, gen_fd.typ, fm)

        return fm

    def _recurse_into_type(
        self,
        gt_typ: TypeExpr,
        gen_typ: TypeExpr,
        fm: EvalFieldMatch,
    ) -> None:
        from src.parse3d.ast import (
            ArrayType,
            CaseType,
            Struct,
            StructNameType,
            StructType,
        )

        # Unwrap ArrayType to reach the element type
        gt_inner = gt_typ.elem_type if isinstance(gt_typ, ArrayType) else gt_typ
        gen_inner = gen_typ.elem_type if isinstance(gen_typ, ArrayType) else gen_typ

        gt_def = None
        gen_def = None
        gt_field_name = fm.field_name_gt
        gen_field_name = fm.field_name_gen

        if isinstance(gt_inner, StructNameType):
            gt_def = gt_inner.struct
        elif isinstance(gt_inner, StructType):
            gt_def = gt_inner.struct
            gt_field_name = gt_field_name or gt_inner.struct.name

        if isinstance(gen_inner, StructNameType):
            gen_def = gen_inner.struct
        elif isinstance(gen_inner, StructType):
            gen_def = gen_inner.struct
            gen_field_name = gen_field_name or gen_inner.struct.name

        if gt_def is not None and gen_def is not None:
            if isinstance(gt_def, (Struct, CaseType)) and isinstance(
                gen_def, (Struct, CaseType)
            ):
                fm.nested = self._compare_definition(
                    gt_def, gen_def, gt_field_name, gen_field_name
                )

    # -- Type comparison ------------------------------------------------------

    def _compare_types(
        self,
        gt_typ: TypeExpr,
        gen_typ: TypeExpr,
        rename_map: dict[str, str],
    ) -> tuple[bool, str | None]:
        from src.parse3d.ast import (
            ArrayType,
            CaseType,
            EmptyType,
            PrimitiveType,
            Struct,
            StructNameType,
            StructType,
        )

        # PrimitiveType
        if isinstance(gt_typ, PrimitiveType) and isinstance(gen_typ, PrimitiveType):
            if gt_typ.name == gen_typ.name and gt_typ.bits == gen_typ.bits:
                return True, None
            return (
                False,
                f"Primitive mismatch: {gt_typ.name}<{gt_typ.bits}> vs {gen_typ.name}<{gen_typ.bits}>",
            )

        # ArrayType
        if isinstance(gt_typ, ArrayType) and isinstance(gen_typ, ArrayType):
            elem_ok, elem_detail = self._compare_types(
                gt_typ.elem_type, gen_typ.elem_type, rename_map
            )
            if not elem_ok:
                return False, f"Array element type: {elem_detail}"

            # For UINT8BE arrays, byte-size and element-count are equivalent
            # since 1 byte = 1 element. 3D only allows [N] for uint8 types.
            elem_is_uint8 = (
                isinstance(gt_typ.elem_type, PrimitiveType)
                and gt_typ.elem_type.name == "UINT8BE"
            )
            if not elem_is_uint8 and gt_typ.is_byte_size != gen_typ.is_byte_size:
                gt_kind = "byte-size" if gt_typ.is_byte_size else "element-count"
                gen_kind = "byte-size" if gen_typ.is_byte_size else "element-count"
                return (
                    False,
                    f"Array kind mismatch: {gt_kind} vs {gen_kind}",
                )

            if not self._expr_equals(gt_typ.size, gen_typ.size, rename_map):
                return (
                    False,
                    f"Array size mismatch: {gt_typ.size} vs {gen_typ.size}",
                )

            return True, None

        # StructNameType (reference to named struct/casetype)
        if isinstance(gt_typ, StructNameType) and isinstance(
            gen_typ, StructNameType
        ):
            gt_def = gt_typ.struct
            gen_def = gen_typ.struct

            if gt_def is None:
                return False, "GT StructNameType unresolved"
            if gen_def is None:
                return False, "Generated StructNameType unresolved"

            if type(gt_def) is not type(gen_def):
                return (
                    False,
                    f"Referenced definition kind mismatch: {type(gt_def).__name__} vs {type(gen_def).__name__}",
                )

            # Compare args for parameterized types
            if len(gt_typ.args) != len(gen_typ.args):
                return (
                    False,
                    f"Type arg count mismatch: {len(gt_typ.args)} vs {len(gen_typ.args)}",
                )

            for i, (gt_arg, gen_arg) in enumerate(zip(gt_typ.args, gen_typ.args)):
                if not self._expr_equals(gt_arg, gen_arg, rename_map):
                    return (
                        False,
                        f"Type arg {i} mismatch: {gt_arg} vs {gen_arg}",
                    )

            # Both point to same kind of definition; recursive comparison
            # happens in _recurse_into_type, not here
            return True, None

        # Inline StructType
        if isinstance(gt_typ, StructType) and isinstance(gen_typ, StructType):
            # Recursive comparison happens via _recurse_into_type
            return True, None

        # EmptyType
        if isinstance(gt_typ, EmptyType) and isinstance(gen_typ, EmptyType):
            return True, None

        # Mismatched type categories
        gt_kind = type(gt_typ).__name__
        gen_kind = type(gen_typ).__name__
        return (
            False,
            f"Type category mismatch: {gt_kind}({self._type_str(gt_typ)}) vs {gen_kind}({self._type_str(gen_typ)})",
        )

    # -- Constraint equivalence -----------------------------------------------

    def _compare_constraint(
        self,
        gt_c: Constraint | None,
        gen_c: Constraint | None,
        rename_map: dict[str, str],
        var_types: dict[str, tuple[str, int]] | None = None,
    ) -> tuple[bool | None, str | None]:
        if gt_c is None and gen_c is None:
            return True, None
        if gt_c is None and gen_c is not None:
            return None, f"Extra constraint in generated: {gen_c}"
        if gt_c is not None and gen_c is None:
            return None, f"Missing constraint, expected: {gt_c}"

        assert gt_c is not None and gen_c is not None

        # Try quick structural comparison first
        if str(gt_c) == str(gen_c):
            return True, None

        try:
            gt_z3 = gt_c.get_expr().to_bool_z3()
            gen_z3 = gen_c.get_expr().to_bool_z3()
        except Exception as e:
            return False, f"Z3 conversion error: {e}"

        # Apply variable renaming if names differ
        if rename_map:
            try:
                gt_z3, gen_z3 = self._apply_z3_rename(gt_z3, gen_z3, rename_map)
            except Exception as e:
                return False, f"Z3 rename error: {e}"

        try:
            from z3 import Int, Solver, sat, unsat

            s = Solver()

            # Add unsigned type bounds for all variables referenced in the constraints.
            # After z3.substitute rename, both expressions use GT variable names.
            if var_types:
                gt_vars = gt_c.get_expr().get_vars()
                for var_name in gt_vars:
                    if var_name in var_types:
                        _type_name, bits = var_types[var_name]
                        v = Int(var_name)
                        s.add(v >= 0)
                        s.add(v < (1 << bits))

            s.add(gt_z3 != gen_z3)
            result = s.check()

            if result == unsat:
                return True, None
            elif result == sat:
                return False, f"Constraints not equivalent: '{gt_c}' vs '{gen_c}'"
            else:
                return False, "Z3 returned unknown"
        except Exception as e:
            return False, f"Z3 solver error: {e}"

    def _apply_z3_rename(
        self, gt_z3, gen_z3, rename_map: dict[str, str]
    ):
        from z3 import Int, substitute

        subs: list[tuple] = []
        for gen_name, gt_name in rename_map.items():
            subs.append((Int(gen_name), Int(gt_name)))

        if subs:
            gen_z3 = substitute(gen_z3, subs)

        return gt_z3, gen_z3

    # -- Expression structural comparison -------------------------------------

    def _expr_equals(
        self,
        gt_expr: Expr,
        gen_expr: Expr,
        rename_map: dict[str, str],
    ) -> bool:
        from src.parse3d.ast import (
            ArithExpr,
            FunctionCall,
            Ident,
            IntLiteral,
            ParenExpr,
        )

        # Fast path: textual match
        if str(gt_expr) == str(gen_expr):
            return True

        if type(gt_expr) is not type(gen_expr):
            return False

        if isinstance(gt_expr, IntLiteral) and isinstance(gen_expr, IntLiteral):
            return gt_expr.value.val == gen_expr.value.val

        if isinstance(gt_expr, Ident) and isinstance(gen_expr, Ident):
            gt_name = gt_expr.name.val
            gen_name = gen_expr.name.val
            if gt_name == gen_name:
                return True
            return rename_map.get(gen_name) == gt_name

        if isinstance(gt_expr, ArithExpr) and isinstance(gen_expr, ArithExpr):
            return (
                gt_expr.op.val == gen_expr.op.val
                and self._expr_equals(gt_expr.left, gen_expr.left, rename_map)
                and self._expr_equals(gt_expr.right, gen_expr.right, rename_map)
            )

        if isinstance(gt_expr, FunctionCall) and isinstance(gen_expr, FunctionCall):
            if gt_expr.name != gen_expr.name:
                return False
            if len(gt_expr.args) != len(gen_expr.args):
                return False
            return all(
                self._expr_equals(ga, ra, rename_map)
                for ga, ra in zip(gt_expr.args, gen_expr.args)
            )

        if isinstance(gt_expr, ParenExpr) and isinstance(gen_expr, ParenExpr):
            return self._expr_equals(gt_expr.expr, gen_expr.expr, rename_map)

        return False

    # -- Helpers --------------------------------------------------------------

    @staticmethod
    def _type_str(typ: TypeExpr) -> str:
        from src.parse3d.ast import (
            ArrayType,
            EmptyType,
            PrimitiveType,
            StructNameType,
            StructType,
        )

        if isinstance(typ, PrimitiveType):
            complete_bits = typ.name.replace("UINT", "").replace("BE", "")
            if typ.bits != int(complete_bits):
                return f"{typ.name}<{typ.bits}>"
            return typ.name
        if isinstance(typ, ArrayType):
            size_str = f":byte-size {typ.size}" if typ.is_byte_size else str(typ.size)
            return f"{AutoEvaluator._type_str(typ.elem_type)}[{size_str}]"
        if isinstance(typ, StructNameType):
            if typ.args:
                args_str = ", ".join(str(a) for a in typ.args)
                return f"{typ.name}({args_str})"
            return typ.name
        if isinstance(typ, StructType):
            return f"inline struct({typ.struct.name})"
        if isinstance(typ, EmptyType):
            return "unit"
        return typ.name
