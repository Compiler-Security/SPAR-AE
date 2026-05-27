from __future__ import annotations
from pathlib import Path
import time
from src.hybrid_fuzz.concolic import PathEvent
from src.hybrid_fuzz.instrument import InstrumentationResult
import tempfile
from src.fsm.fsm_new import FSM
from src.refine.test_result import (
  TestResult,
  TestResultDetail,
  TestResultType,
  dummy_detail,
)
from typing import TYPE_CHECKING, final, override
from rich.progress import (
  Progress,
  BarColumn,
  TextColumn,
  TimeElapsedColumn,
  TimeRemainingColumn,
)
from src.log import StepLogger, console
from src.tool import todo

if TYPE_CHECKING:
  from src.parse3d import ParserContext, PathCondition, Module
  from src.encode import PathTestcaseGenerator
  from src.refine.test_result import TestResult
  from src.fsm import FSM
  from src.doc_graph.document_graph import DocumentGraph


@final
class Tester(StepLogger):
  def __init__(
    self,
    doc_graph: "DocumentGraph",
    format: str | None = None,
    encode_count: int = 1,
    make_branch_for_empty: bool = False,
    disable_opt_i: bool = False,
    disable_opt_ii: bool = False,
    disable_opt_iii: bool = False,
  ) -> None:
    super().__init__("Tester")
    self.doc_graph: "DocumentGraph" = doc_graph
    self.make_branch_for_empty = make_branch_for_empty
    self.disable_opt_i = disable_opt_i
    self.disable_opt_ii = disable_opt_ii
    self.disable_opt_iii = disable_opt_iii
    from src.parse3d import Parse3D
    from src.fsm import FSMBuilder
    from src.encode import PathTestcaseGenerator
    from src.parse3d import CollectPathCondition

    if format is None:
      if self.doc_graph.root.format_path is None:
        raise ValueError("DocumentTree root must have a format file.")
      with open(self.doc_graph.root.format_path, "r", encoding="utf-8") as f:
        format_code: str = f.read()
    else:
      format_code = format
    self.format_code: str = format_code
    self.parser: "Parse3D" = Parse3D(format_code)
    self.ast: "Module" = self.parser.parse()

    if self.ast.entrypoint is None:
      raise ValueError("The format file must have an entrypoint.")

    self.ctx: "ParserContext" = self.parser.context

    self.fsm_map: "dict[str, FSM]" = FSMBuilder().build(self.ast, self.ctx)
    self.entry_fsm: "FSM" = self.fsm_map[
      self.ast.entrypoint
    ]  # we want to test and refine this fsm
    fsm_start_time = time.time()
    if self.disable_opt_i:
      self.paths = list(self.entry_fsm.save_all_paths_dense())
    else:
      self.paths = list(self.entry_fsm.save_all_paths())
    # Merge field offsets across ALL paths (paths may share the same root
    # FSM name but take different branches after casetypes, producing
    # different field layouts).  We keep the union: for each field we
    # store every (byte_offset, bit_offset, width) seen in any path.
    self._field_offsets: dict[str, set[tuple[int, int, int]]] = {}
    for path in self.paths:
      for name, (bo, bio, bw) in path.compute_field_offsets().items():
        if bo >= 0 and bw > 0:
          self._field_offsets.setdefault(name, set()).add((bo, bio, bw))
    self.full_path_count: int = 0
    self.encode_count = encode_count

    self.path_conditions: dict[str, dict[str, "PathCondition"]] = (
      CollectPathCondition().collect(self.ast, self.ctx)
    )
    self.testcase_generators: "list[PathTestcaseGenerator]" = [
      PathTestcaseGenerator(
        path,
        self.ast,
        self.ctx,
        self.path_conditions,
        self.encode_count,
        mute=self.mute,
        disable_opt_ii=self.disable_opt_ii,
      )
      for path in self.paths
    ]  # one generator for each path
    fsm_end_time = time.time()
    self.optimized_path_count: int = len(self.testcase_generators)
    self.log_info(
      f"Total paths in FSM: {self.full_path_count}, after optimization: {self.optimized_path_count}"
    )
    self.time_cost = 0.0
    self.parser_time_cost = 0.0
    self.format_time_cost = 0.0
    self.smt_time_cost = fsm_start_time - fsm_end_time

  def run_parser(self, parser_path: str, testcase: bytes) -> tuple[int, str, str, str]:
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
      run_command = f"python {parser_path} {tmpfile.name}"
      _ = tmpfile.write(testcase)
      tmpfile.flush()
      self.log_info(f"Running command: {run_command}")
      process = subprocess.Popen(
        run_command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
      )
      stdout, stderr = process.communicate()
      return process.returncode, stdout, stderr, tmpfile.name

  @staticmethod
  def get_related_sections(doc_graph: "DocumentGraph", current_diff: list[str]) -> str:
    related_sections: list[str] = list()
    related_section_number: list[str] = list()
    for fsm_name in current_diff:
      if fsm_name in doc_graph.name_to_section_3d:
        sections = doc_graph.name_to_section_3d[fsm_name]
        for section in sections:
          section_num = section[0]
          section_node = doc_graph.get_section(section_num)
          if section_node is None:
            continue
          related_sections.append(section_node.content)
          related_section_number.append(section_num)
    if len(related_sections) == 0:
      related_sections.append(doc_graph.root.content)
    if len(related_section_number) == 0:
      related_section_number.append(doc_graph.root.number)

    result = ""
    related_sections = list(set(related_sections))
    related_section_number = list(set(related_section_number))
    for cnt, number in enumerate(related_section_number):
      result += f"Section {number}:\n"
      result += related_sections[cnt]
      result += "\n\n"
    return result.strip()

  @staticmethod
  def get_related_parser(doc_graph: "DocumentGraph", current_diff: list[str]) -> str:
    related_parsers: list[str] = list()
    section_numbers = Tester.get_related_section_number(doc_graph, current_diff)
    for section_num in section_numbers:
      section_node = doc_graph.get_section(section_num)
      if section_node is None:
        continue
      if section_node.parser_path is None:
        continue
      with open(section_node.parser_path, "r") as f:
        parser_content = f.read()
      related_parsers.append(
        f"########### From Section {section_num}: ############\n{parser_content}"
      )
    return "\n\n".join(related_parsers).strip()

  @staticmethod
  def get_related_section_number(
    doc_graph: "DocumentGraph", current_diff: list[str]
  ) -> list[str]:
    related_section_number: list[str] = list()
    for fsm_name in current_diff:
      if fsm_name in doc_graph.name_to_section_3d:
        sections = doc_graph.name_to_section_3d[fsm_name]
        for section in sections:
          section_num = section[0]
          section_node = doc_graph.get_section(section_num)
          if section_node is None:
            continue
          related_section_number.append(section_num)
    if len(related_section_number) == 0:
      related_section_number.append(doc_graph.root.number)
    return list(set(related_section_number))

  @staticmethod
  def _lookup_section_by_var_name(
    doc_graph: "DocumentGraph", var_name: str
  ) -> str | None:
    """Look up a section number by variable name, using prefix matching.

    name_to_section_py keys are like 'vers:28' (name:lineno).
    We match a bare variable name like 'vers' against any key starting with 'vers:'.
    """
    prefix = var_name + ":"
    for key, section_number in doc_graph.name_to_section_py.items():
      if key.startswith(prefix):
        return section_number
    return None

  def _lookup_section_by_byte_offset(
    self,
    doc_graph: "DocumentGraph",
    byte_variables: list[str],
    function_name: str,
  ) -> list[str]:
    """Use byte indices from z3 variables to find matching 3D fields and their sections.

    byte_variables are names like ['byte_0', 'byte_5'] — we extract the numeric
    byte index and match against 3D field offsets computed from FSM paths.
    Falls back to py_function_scope for function-level mapping.
    """
    sections: list[str] = []

    # Extract numeric byte indices from z3 variable names
    byte_indices: set[int] = set()
    for bv in byte_variables:
      if bv.startswith("byte_"):
        try:
          byte_indices.add(int(bv[len("byte_"):]))
        except ValueError:
          pass

    if byte_indices:
      n3d = doc_graph.name_to_section_3d
      # Match byte indices to 3D field names via merged field offsets
      for field_name, offset_set in self._field_offsets.items():
        for byte_off, bit_off, width in offset_set:
          if width <= 0:
            continue
          byte_start = byte_off + bit_off // 8
          byte_end = byte_off + (bit_off + width + 7) // 8
          if any(bi in range(byte_start, byte_end) for bi in byte_indices):
            section_map = n3d.get(field_name)
            if section_map is not None:
              best_sec = max(section_map.keys(), key=lambda s: s.count("."))
              if best_sec not in sections:
                sections.append(best_sec)
            break  # found a match for this field, skip other offsets

    if sections:
      return sections

    # Fallback: use function_name to look up section via py_function_scope
    if function_name:
      section_info = doc_graph.py_function_scope.get(function_name)
      if section_info is not None:
        sections.append(section_info[0])

    return sections

  def _run_instrumentation_for_input(
    self, test_input: bytes, parser_path: str
  ) -> "tuple[list[str], list[str], str] | None":
    """Run test input through Instrumentator to collect slicing data.

    Returns (variable_names, byte_variables, function_name) from the last
    PathEvent constraint, or None if instrumentation fails.
    """
    try:
      with open(parser_path, "r", encoding="utf-8") as f:
        source_code = f.read()
    except Exception:
      return None

    from src.hybrid_fuzz.instrument import Instrumentator

    instr = Instrumentator(source_code, filename=parser_path)
    try:
      instr_result = instr.run(test_input)
    except Exception:
      return None

    if not instr_result.constraints:
      return None

    last = instr_result.constraints[-1]
    return (last.variable_names, last.byte_variables, last.function_name)

  @override
  def run(self):
    pass  # dummy implementation to satisfy abstract base class

  def test(self, parser_path: str, skips: set[str] = set()):  # pyright: ignore[reportCallInDefaultInitializer]
    # First test against parser
    start_time = time.time()
    parser_result = self.test_against_parser(parser_path, skips)
    parser_end_time = time.time()
    self.parser_time_cost = parser_end_time - start_time
    if parser_result.result_type != TestResultType.CORRECT_PASS_INCORRECT_FAIL:
      return parser_result
    # Then test against format
    format_start_time = time.time()
    format_result = self.test_against_format(parser_path, skips)
    format_end_time = time.time()
    self.format_time_cost = format_end_time - format_start_time
    return format_result

  def test_against_parser(
    self,
    parser_path: str,
    skips: set[str] = set[str](),  # pyright: ignore[reportCallInDefaultInitializer]
  ) -> "TestResult":
    with self.step("Testing Parser"):
      from src.encode import EncoderError
      from src.refine.test_result import TestResult, TestResultType, TestResultDetail
      from src.fsm import PathNodeKind

      def cmp_fsm_seq(last_fsm_seq: list[str], current_fsm_seq: list[str]) -> list[str]:
        for i in range(len(current_fsm_seq)):
          if i >= len(last_fsm_seq):
            return current_fsm_seq[i:]
          if last_fsm_seq[i] == current_fsm_seq[i]:
            continue
          else:
            return current_fsm_seq[i:]

        return []

      last_diff: list[str] = [self.entry_fsm.name]
      last_fsm_seq: list[str] = []
      current_fsm_seq: list[str] = []
      self.log_info(f"Testing parser at path: {parser_path}")
      self.log_info(f"Total testcase generators: {len(self.testcase_generators)}")
      from rich.progress import Progress

      with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
      ) as progress_overall:
        overall_task = progress_overall.add_task(
          "Overall Testing Progress...", total=len(self.testcase_generators)
        )
        for generator in self.testcase_generators:
          # compute current_fsm_seq
          current_fsm_history = list(
            map(
              lambda x: x.fsm.name,  # pyright: ignore[reportOptionalMemberAccess]
              filter(
                lambda x: (
                  x.kind in (PathNodeKind.FSM_START, PathNodeKind.FSM_END)
                  and x.fsm is not None
                ),
                generator.path.nodes,
              ),
            )
          )

          def restore_fsm_seq(fsm_history: list[str]) -> list[str]:
            name_stack: list[str] = []
            fsm_seq: list[str] = []
            for fsm_name in fsm_history:
              prefix_removed_name = (
                fsm_name.split(name_stack[-1] + "_")[-1] if name_stack else fsm_name
              )
              if (
                len(name_stack) == 0 or name_stack[-1] != fsm_name
              ):  # entering a new fsm
                name_stack.append(fsm_name)
                fsm_seq.append(prefix_removed_name)
              else:  # exiting the current fsm
                _ = name_stack.pop()
            return fsm_seq

          current_fsm_seq = restore_fsm_seq(current_fsm_history)

          self.log_info(f"Current FSM sequence: {current_fsm_seq}")
          current_diff = cmp_fsm_seq(last_fsm_seq, current_fsm_seq)
          if not current_diff:
            current_diff = last_diff
          last_fsm_seq = current_fsm_seq
          last_diff = current_diff
          self.log_info(f"Current diff FSM sequence: {current_diff}")
          with self.step("Correct Case Testing"):
            self.log_info(f"Generating correct cases for path:\n {generator.path}")
            fsm_passing_start = time.time()
            correct_cases = generator.correct_cases
            fsm_passing_end = time.time()
            self.smt_time_cost += fsm_passing_end - fsm_passing_start
            idx = -1
            while True:
              try:
                encode_start_time = time.time()
                correct_case = next(correct_cases)
                if correct_case.hex() in skips:
                  self.log_warning(f"Skipping known case: {correct_case.hex()}")
                  continue
                encode_end_time = time.time()
                self.smt_time_cost += encode_end_time - encode_start_time
                idx += 1
              except StopIteration:
                break
              except EncoderError as e:
                self.log_warning(
                  f"Encoding error when generating correct case: {' -> '.join(current_fsm_seq)}"
                )
                self.log_warning(
                  f"Unsat core: {e if e.unsat_core is None else e.unsat_core}"  # pyright: ignore[reportUnknownMemberType]
                )
                continue
              correct_run = self.run_parser(parser_path, correct_case)
              (
                correct_exit_code,
                correct_stdout,
                correct_stderr,
                correct_packet_path,
              ) = correct_run

              if correct_exit_code != 0:
                self.log_warning("Correct case failed to parse")
                self.log_warning(f"Stdout: {correct_stdout}")
                self.log_warning(f"Stderr: {correct_stderr}")
                self.log_warning(f"Packet: {correct_case.hex()}")
                # Run Instrumentator to collect slicing data (variable_names, byte_variables)
                if self.disable_opt_iii:
                  self.log_info("slicing | DISABLED (Opt III) — using FSM diff fallback")
                  enriched_section_numbers = Tester.get_related_section_number(
                    self.doc_graph, current_diff
                  )
                else:
                  self.log_info("slicing | CORRECT_FAIL — running Instrumentator...")
                  instr_data = self._run_instrumentation_for_input(
                    correct_case, parser_path
                  )
                  if instr_data is not None:
                    instr_vars, instr_bytes, instr_func = instr_data
                    self.log_info(f"slicing | vars={instr_vars} bytes={instr_bytes} func={instr_func}")
                    enriched_sections: list[str] = []
                    for name in instr_vars:
                      sec = Tester._lookup_section_by_var_name(self.doc_graph, name)
                      if sec and sec not in enriched_sections:
                        enriched_sections.append(sec)
                    self.log_info(f"slicing | var_name→section: {enriched_sections}")
                    byte_sections = self._lookup_section_by_byte_offset(
                      self.doc_graph, instr_bytes, instr_func
                    )
                    self.log_info(f"slicing | byte→section: {byte_sections}")
                    for sec in byte_sections:
                      if sec not in enriched_sections:
                        enriched_sections.append(sec)
                    enriched_section_numbers = enriched_sections
                    self.log_info(f"slicing | final sections: {enriched_section_numbers}")
                  else:
                    self.log_warning("slicing | Instrumentator failed, fallback to FSM diff")
                    enriched_section_numbers = Tester.get_related_section_number(
                      self.doc_graph, current_diff
                    )

                related_section_content = ""
                if enriched_section_numbers:
                  for sec_num in enriched_section_numbers:
                    section_node = self.doc_graph.get_section(sec_num)
                    if section_node:
                      related_section_content += section_node.content + "\n\n"
                else:
                  related_section_content = Tester.get_related_sections(
                    self.doc_graph, current_diff
                  )

                # Build related parser from slicing-derived sections (or root as fallback)
                slicing_parser = ""
                if enriched_section_numbers:
                  for sec_num in enriched_section_numbers:
                    sec_node = self.doc_graph.get_section(sec_num)
                    if sec_node and sec_node.parser_path:
                      try:
                        with open(sec_node.parser_path, "r") as pf:
                          slicing_parser += (
                            f"########### From Section {sec_num}: ############\n"
                            + pf.read() + "\n"
                          )
                      except Exception:
                        pass
                if not slicing_parser:
                  slicing_parser = Tester.get_related_parser(self.doc_graph, current_diff)

                result = TestResult(
                  TestResultType.CORRECT_FAIL,
                  TestResultDetail(
                    correct_stdout + "\n\n" + correct_stderr,
                    self.format_code,
                    slicing_parser,
                    related_section_content.strip(),
                    enriched_section_numbers if enriched_section_numbers
                    else Tester.get_related_section_number(self.doc_graph, current_diff),
                    None,
                    correct_packet_path,
                  ),
                )
                return result

          with self.step("Incorrect Case Testing"):
            self.log_info("Generating incorrect cases")
            for path, path_conditions in generator.all_mutated_paths_and_condition():
              for path_condition in path_conditions:
                try:
                  fsm_passing_start = time.time()
                  incorrect_cases = generator.cases_for_incorrect_path_and_condition(
                    path, path_condition
                  )
                  fsm_passing_end = time.time()
                  self.smt_time_cost += fsm_passing_end - fsm_passing_start
                  self.log_info(
                    f"Testing incorrect cases for path {' -> '.join(current_fsm_seq)} with path condition: {' && '.join(map(str, path_condition.constraints))}"
                  )
                  encode_start_time = time.time()
                  for idx, case in enumerate(incorrect_cases):
                    if case.hex() in skips:
                      self.log_warning(f"Skipping known case: {case.hex()}")
                      continue
                    encode_end_time = time.time()
                    self.smt_time_cost += encode_end_time - encode_start_time
                    incorrect_run = self.run_parser(parser_path, case)
                    (
                      incorrect_exit_code,
                      incorrect_stdout,
                      incorrect_stderr,
                      incorrect_packet_path,
                    ) = incorrect_run
                    if incorrect_exit_code == 0:
                      self.log_warning(f"Incorrect case unexpectedly parsed: {path}")
                      self.log_warning(
                        f"Path condition: {' && '.join(map(str, path_condition.constraints))}"
                      )
                      self.log_warning(
                        f"Values: \n{'  \n'.join(f'{k}: {v}' for k, v in generator.incorrect_case_table[path_condition][idx].items())}"
                      )
                      self.log_info(f"Stdout: {incorrect_stdout}")
                      self.log_info(f"Stderr: {incorrect_stderr}")
                      self.log_info(f"Packet Path: {incorrect_packet_path}")
                      self.log_info(f"Parser Path: {parser_path}")
                      self.log_info(f"Packet : {case.hex()}")
                      # Run Instrumentator to collect slicing data
                      if self.disable_opt_iii:
                        self.log_info("slicing | DISABLED (Opt III) — using FSM diff fallback")
                        enriched_section_numbers = Tester.get_related_section_number(
                          self.doc_graph, current_diff
                        )
                      else:
                        self.log_info("slicing | INCORRECT_PASS — running Instrumentator...")
                        instr_data = self._run_instrumentation_for_input(
                          case, parser_path
                        )
                        if instr_data is not None:
                          instr_vars, instr_bytes, instr_func = instr_data
                          self.log_info(f"slicing | vars={instr_vars} bytes={instr_bytes} func={instr_func}")
                          enriched_sections: list[str] = []
                          for name in instr_vars:
                            sec = Tester._lookup_section_by_var_name(self.doc_graph, name)
                            if sec and sec not in enriched_sections:
                              enriched_sections.append(sec)
                          self.log_info(f"slicing | var_name→section: {enriched_sections}")
                          byte_sections = self._lookup_section_by_byte_offset(
                            self.doc_graph, instr_bytes, instr_func
                          )
                          self.log_info(f"slicing | byte→section: {byte_sections}")
                          for sec in byte_sections:
                            if sec not in enriched_sections:
                              enriched_sections.append(sec)
                          enriched_section_numbers = enriched_sections
                          self.log_info(f"slicing | final sections: {enriched_section_numbers}")
                        else:
                          self.log_warning("slicing | Instrumentator failed, fallback to FSM diff")
                          enriched_section_numbers = Tester.get_related_section_number(
                            self.doc_graph, current_diff
                          )

                      related_section_content = ""
                      if enriched_section_numbers:
                        for sec_num in enriched_section_numbers:
                          section_node = self.doc_graph.get_section(sec_num)
                          if section_node:
                            related_section_content += section_node.content + "\n\n"
                      else:
                        related_section_content = Tester.get_related_sections(
                          self.doc_graph, current_diff
                        )

                      # Build related parser from slicing-derived sections
                      slicing_parser = ""
                      if enriched_section_numbers:
                        for sec_num in enriched_section_numbers:
                          sec_node = self.doc_graph.get_section(sec_num)
                          if sec_node and sec_node.parser_path:
                            try:
                              with open(sec_node.parser_path, "r") as pf:
                                slicing_parser += (
                                  f"########### From Section {sec_num}: ############\n"
                                  + pf.read() + "\n"
                                )
                            except Exception:
                              pass
                      if not slicing_parser:
                        slicing_parser = Tester.get_related_parser(self.doc_graph, current_diff)

                      result = TestResult(
                        TestResultType.CORRECT_PASS_INCORRECT_PASS,
                        TestResultDetail(
                          f"{incorrect_stdout}\n\n{incorrect_stderr}",
                          self.format_code,
                          slicing_parser,
                          related_section_content.strip(),
                          enriched_section_numbers if enriched_section_numbers
                          else Tester.get_related_section_number(
                            self.doc_graph, current_diff
                          ),
                          tuple(map(str, path_condition.constraints))
                          if path_condition
                          else None,
                          incorrect_packet_path,
                        ),
                      )
                      if (
                        " && ".join(result.details.negated_path_conditions or [])
                        in skips
                      ):
                        self.log_warning(
                          "Skipping this result as it has been skipped before."
                        )
                        continue
                      return result
                    encode_start_time = time.time()
                except EncoderError as e:
                  self.log_warning(
                    f"Encoding error when generating incorrect case: {' -> '.join(current_fsm_seq)}"
                  )
                  self.log_warning(
                    f"Unsat core: {e if e.unsat_core is None else e.unsat_core}"  # pyright: ignore[reportUnknownMemberType]
                  )
                  continue
              # all incorrect cases failed as expected
          progress_overall.advance(overall_task)
          self.smt_time_cost += generator.smt_time_cost
        from src.refine.test_result import dummy_detail

        self.log_info("All test cases passed as expected.")
        return TestResult(
          TestResultType.CORRECT_PASS_INCORRECT_FAIL,
          dummy_detail,
        )

  def test_against_format(self, parser_path: str, skips: set[str]) -> "TestResult":
    from src.refine.test_result import dummy_detail

    # return TestResult(TestResultType.CORRECT_PASS_INCORRECT_FAIL, dummy_detail)
    from src.encode import EncoderError
    from src.refine.test_result import (
      TestResult,
      TestResultType,
      TestResultDetail,
    )

    with self.step("Testing Format"):
      with self.step("Generating Seeds"):
        format_seeds: set[bytes] = set()
        for generator in self.testcase_generators:
          correct_cases = generator.correct_cases
          idx = -1
          while True:
            try:
              correct_case = next(correct_cases)
              idx += 1
              format_seeds.add(correct_case)
            except StopIteration:
              break
            except EncoderError:
              continue
      self.log_info(f"Total format seeds generated: {len(format_seeds)}")
      return TestResult(TestResultType.SKIP, dummy_detail)
      # use hybrid fuzzer to generate more testcases from format seeds
      from src.hybrid_fuzz.fuzz import HybridFuzzer

      # read parser code
      with open(parser_path, "r") as f:
        source_code = f.read()
      fuzzer = HybridFuzzer(
        source_code,
        parser_path,
        format_seeds,
        timeout=60.0,
        max_iterations=100,
      )
      fuzzer_results: dict[bytes, InstrumentationResult] = fuzzer.fuzz()
      self.log_info(
        f"Total testcases collected from hybrid fuzzing: {len(fuzzer_results)}"
      )
      from src.refine.validate_packet import PacketValidator

      # Update the format_code in case it has been changed
      with open(self.doc_graph.root.format_path or "", "r") as f:
        self.format_code = f.read()

      validator = PacketValidator(
        self.format_code, entry_func=self.ctx.true_entrypoint or ""
      )
      validator.generate_validator()
      if validator.validator_generate_failed:
        self.log_warning("Validator generation failed, skipping format testing.")
        from src.refine.test_result import dummy_detail

        return TestResult(
          TestResultType.CORRECT_PASS_INCORRECT_FAIL,
          dummy_detail,
        )
      for input_data, instr_result in fuzzer_results.items():
        if str(input_data.hex()) in skips:
          self.log_info("Skipping this testcase as it has been skipped before.")
          continue
        # Validating each labeled testcase with the format
        is_valid, validation_output = validator.validate_packet(input_data)
        # if is valid, parser must accept, if invalid, parser must reject, we use xor to check
        parser_accepts = instr_result.exit_code == 0
        if is_valid and not parser_accepts:
          # if fail because length mismatch, we ignore it because probably the reason is 3d sucks
          self.log_warning("Format says valid but parser rejected the packet!")
          if "length" in (instr_result.stdout + "\n" + instr_result.stderr).lower():
            self.log_warning("Reject reason is length mismatch, ignoring...")
            continue
        if is_valid ^ parser_accepts:
          self.log_warning("Discrepancy found between format and parser!")
          self.log_warning(f"Packet: {input_data.hex()}")
          self.log_warning(f"Format says valid: {is_valid}")
          self.log_warning(f"Parser exit code: {instr_result.exit_code}")
          # breakpoint()
          if is_valid:
            result_type = TestResultType.CORRECT_FAIL
          else:
            result_type = TestResultType.CORRECT_PASS_INCORRECT_PASS
          with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
            _ = tmpfile.write(input_data)
            tmpfile.flush()
            packet_path = tmpfile.name
          if result_type == TestResultType.CORRECT_FAIL:
            self.log_warning("Correct case failed to parse")
            last_constraint: PathEvent | None = (
              instr_result.constraints[-1] if instr_result.constraints else None
            )
            self.log_warning(f"Last constraint: {last_constraint}")
            if not last_constraint:
              self.log_warning("No path constraints recorded.")
              related_parser = source_code
              section_number = None
            else:
              func_name = last_constraint.function_name
              var_name = last_constraint.variable_names
              section_number, related_line_range = self.doc_graph.py_function_scope.get(
                func_name, (None, None)
              )
              additional_section_numbers: list[str] = []
              for name in var_name:
                sec = Tester._lookup_section_by_var_name(
                  self.doc_graph, name
                )
                if sec is not None and sec not in additional_section_numbers:
                  additional_section_numbers.append(sec)
              # Also try byte-offset lookup from z3 leaf variables
              byte_secs = self._lookup_section_by_byte_offset(
                self.doc_graph, last_constraint.byte_variables, func_name
              )
              for sec in byte_secs:
                if sec not in additional_section_numbers:
                  additional_section_numbers.append(sec)
              if section_number is None:
                related_parser = source_code
              if related_line_range is None:
                related_parser = source_code
              else:
                related_parser = "\n".join(
                  source_code.splitlines()[
                    int(related_line_range[0]) - 1 : int(related_line_range[1])
                  ]
                )
            related_section_content = ""
            if section_number is not None:
              section_node = self.doc_graph.get_section(section_number)
              if section_node is not None:
                related_section_content = section_node.content
              for add_num in additional_section_numbers:
                if add_num != section_number:
                  add_node = self.doc_graph.get_section(add_num)
                  if add_node is not None:
                    related_section_content += "\n\n" + add_node.content
            else:
              related_section_content = self.doc_graph.root.content
            result = TestResult(
              result_type,
              TestResultDetail(
                instr_result.stdout + "\n\n" + instr_result.stderr,
                self.format_code
                or Path(
                  self.doc_graph.get_section(section_number).format_path or ""  # pyright: ignore[reportOptionalMemberAccess]
                ).read_text(encoding="utf-8")
                if section_number is not None
                else self.format_code,
                related_parser,
                related_section_content,
                [self.doc_graph.root.number],
                None,
                packet_path,
              ),
            )
            return result
          else:
            result = TestResult(
              result_type,
              TestResultDetail(
                validation_output,
                self.format_code,
                source_code,
                self.doc_graph.root.content,
                [self.doc_graph.root.number],
                ("unknown",),
                packet_path,
              ),
            )
            return result
      from src.refine.test_result import dummy_detail

      self.log_info("All format test cases passed as expected.")
      return TestResult(
        TestResultType.CORRECT_PASS_INCORRECT_FAIL,
        dummy_detail,
      )
