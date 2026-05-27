def main():
    from tap import tapify
    from dataclasses import dataclass

    @dataclass
    class Args:
        ground_truth: str
        generated: str

    args = tapify(Args, underscores_to_dashes=True, description="Evaluate a generated 3D format against a ground truth.")

    with open(args.ground_truth) as f:
        gt_text = f.read()
    with open(args.generated) as f:
        gen_text = f.read()

    from src.refine.auto_evaluator import AutoEvaluator

    evaluator = AutoEvaluator(gt_text, gen_text)
    summary = evaluator.evaluate()

    print(f"Ground truth:   {summary.gt_entrypoint}")
    print(f"Generated:      {summary.gen_entrypoint}")
    print(f"Overall score:  {summary.overall_score:.3f}")
    print(f"Strict pass:    {summary.strict_pass}")
    print(f"Definitions:    {summary.total_types_visited} ({summary.fully_matched_defs} full, {summary.partially_matched_defs} partial)")
    print()

    for r in summary.definition_results:
        tag = "PASS" if r.passed else f"MISMATCH ({r.match_ratio:.0%})"
        print(f"── {r.definition_kind} {r.definition_name_gt} / {r.definition_name_gen}  {tag}")
        for fm in r.field_matches:
            gt_name = fm.field_name_gt or "(none)"
            gen_name = fm.field_name_gen or "(none)"
            print(f"  [{fm.position}] {gt_name}  vs  {gen_name}")
            print(f"      type:       {_status(fm.type_match)}   gt={fm.type_gt}   gen={fm.type_gen}")
            if fm.type_detail:
                print(f"                 ── {fm.type_detail}")

            c_stat = _constraint_status(fm.constraint_match)
            c_gt = fm.constraint_gt or "(none)"
            c_gen = fm.constraint_gen or "(none)"
            print(f"      constraint: {c_stat}   gt={c_gt}")
            print(f"                   {'' :>{len(c_stat)}}   gen={c_gen}")
            if fm.constraint_detail:
                print(f"                 ── {fm.constraint_detail}")

            if fm.nested:
                _print_nested(fm.nested, indent="      ")
        print()


def _status(ok: bool) -> str:
    return "OK " if ok else "MISMATCH"


def _constraint_status(match: bool | None) -> str:
    if match is True:
        return "OK "
    if match is False:
        return "MISMATCH"
    return "ABSENT"


def _print_nested(nested, indent: str) -> None:
    tag = "PASS" if nested.passed else f"MISMATCH ({nested.match_ratio:.0%})"
    print(f"{indent}↳ {nested.definition_kind} {nested.definition_name_gt} / {nested.definition_name_gen}  {tag}")
    for fm in nested.field_matches:
        gt_name = fm.field_name_gt or "(none)"
        gen_name = fm.field_name_gen or "(none)"
        print(f"{indent}  [{fm.position}] {gt_name}  vs  {gen_name}")
        print(f"{indent}      type:       {_status(fm.type_match)}   gt={fm.type_gt}   gen={fm.type_gen}")
        if fm.type_detail:
            print(f"{indent}                 ── {fm.type_detail}")
        c_stat = _constraint_status(fm.constraint_match)
        c_gt = fm.constraint_gt or "(none)"
        c_gen = fm.constraint_gen or "(none)"
        print(f"{indent}      constraint: {c_stat}   gt={c_gt}")
        print(f"{indent}                   {'' :>{len(c_stat)}}   gen={c_gen}")
        if fm.constraint_detail:
            print(f"{indent}                 ── {fm.constraint_detail}")
        if fm.nested:
            _print_nested(fm.nested, indent=indent + "  ")


if __name__ == "__main__":
    main()
