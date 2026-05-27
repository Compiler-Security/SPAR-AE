# from __future__ import annotations
# do not use __future__ annotations here to make tapify happy
from pathlib import Path
import time
from typing import TYPE_CHECKING, NoReturn, final, override

from src.encode import EncoderError
from src.refine import TestResult, TestResultType
from src.refine.refiner import FixedWhat
from src.refine.test_result import dummy_detail
from src.log import StepLogger, logger
from src.tool.debug_wrapper import debug_decorator_factory
import yaml

if TYPE_CHECKING:
  from src.ablation.without_rfc import DriverWORFC
  from src.doc_graph import DocumentGraph
  from src.refine import Round


# a wrapper to manage the whole running project
@final
class Driver(StepLogger):
  def __init__(
    self,
    protocol_name: str,
    rfc_path: str,
    data_directory: str,
    encode_count: int = 1,
    use_existing: str = "",
    no_debug: bool = False,
    only_generate_cases: bool = False,
    make_branch_for_empty: bool = False,
    use_parallel: bool = False,
    disable_opt_i: bool = False,
    disable_opt_ii: bool = False,
    disable_opt_iii: bool = False,
    run_wo_rfc: bool = False,
  ):
    """
    Driver to run the whole process of protocol parser generation and refinement.

    :param protocol_name: Name of the protocol.
    :param rfc_path: Path to the RFC file.
    :param data_directory: Path to the data directory.
    :param disable_opt_i: If True, use save_all_paths_dense (no path cover optimization).
    :param disable_opt_ii: If True, explore all combinations of constraint negation (exhaustive mode, no Optimization II).
    :param disable_opt_iii: If True, disable instrumentation-based slicing (fallback to FSM diff).
    :param run_wo_rfc: If True, also run the without-RFC ablation (generate format/parser without RFC text).
    """
    super().__init__("SPAR")
    with self.step("Initializing Driver"):
      self.protocol_name = protocol_name
      self.rfc_path = rfc_path
      if Path(rfc_path).stem != protocol_name:
        self.log_warning(
          f"Protocol name {protocol_name} does not match RFC file name {Path(rfc_path).stem}, renaming protocol name for consistency."
        )
        self.protocol_name = Path(rfc_path).stem
      self.data_directory = data_directory
      self.doc_graph: "DocumentGraph | None" = None
      self.doc_graph_builder = None
      self.skip_dict: dict[str, int] = {}
      self.skips: set[str] = set()
      self.initial_format: str | None = None
      self.initial_parser: str | None = None
      self.encode_count: int = encode_count
      self.use_existing: str = use_existing
      self.debug: bool = not no_debug
      self.only_generate_cases = only_generate_cases
      self.make_branch_for_empty: bool = make_branch_for_empty
      self.use_parallel = use_parallel
      self._run_method = debug_decorator_factory(self.debug)(self._run)
      self.sub_driver_wo_rfc: "DriverWORFC | None" = None
      self.paths_before_optimization: int = 0
      self.paths_after_optimization: int = 0
      self.disable_opt_i = disable_opt_i
      self.disable_opt_ii = disable_opt_ii
      self.disable_opt_iii = disable_opt_iii
      self.run_wo_rfc = run_wo_rfc
      self.mute = not self.debug

      # we want to save all testcases(in binary) generated for future fuzzing
      # for testcase, we will orgnize them by path structure, which will be (set[correct cases], dict[path_condition, set[incorrect cases]])
      # so in summary, we want dict[path, (set[correct cases], dict[path_condition, set[incorrect cases]])]
      #
      self.testcases: dict[str, tuple[set[bytes], dict[str, set[bytes]]]] = (
        dict()
      )  # path's repr -> (correct cases, {path_condition repr -> incorrect cases})

      self.runtime: float = 0.0
      self.refinement_rounds: int = 0
      self.solver_time_cost: float = 0.0
      self.llm_cost_dollar: float = 0.0
      self.llm_cost_initial_generation: float = 0.0
      self.llm_calling_tool_time: float = 0.0
      self.llm_chat_time: float = 0.0
      self.time_testing_against_format: float = 0.0
      self.time_testing_against_parser: float = 0.0

      self.log_info(
        f"Driver initialized for protocol {self.protocol_name} with RFC at {self.rfc_path} and data directory at {self.data_directory}, encode {self.encode_count} correct cases per path, use_existing={self.use_existing}, debug={self.debug}, only_generate_cases={self.only_generate_cases}, make_branch_for_empty={self.make_branch_for_empty}, use_parallel={self.use_parallel}, disable_opt_i={self.disable_opt_i}, disable_opt_ii={self.disable_opt_ii}, disable_opt_iii={self.disable_opt_iii}"
      )

  def build_graph(self):
    if self.doc_graph is not None:
      return  # already built
    # build the document graph
    from src.doc_graph import DocumentGraphBuilder

    builder = DocumentGraphBuilder(
      self.protocol_name,
      self.rfc_path,
      use_existing=self.use_existing,
    )
    self.doc_graph_builder = builder

    _ = builder.build(self.data_directory)
    # _ = builder.build_by_llm()
    # Early return if using existing graph
    if self.use_existing:
      self.doc_graph = builder.doc_graph
      return

    # genenrate format and parser
    from pathlib import Path

    dir_path = Path(self.data_directory)

    manual_path_3d = dir_path / "DSL" / "3d_syntax_check.txt"
    example_path_3d = dir_path / "example" / f"example_{self.protocol_name.lower()}.txt"
    if not example_path_3d.exists():
      match self.protocol_name.lower():
        case "ptcs":
          example_path_3d = dir_path / "example" / "example_sctp.txt"
        case "pgb-x":
          example_path_3d = dir_path / "example" / "example.txt"
        case "ptn":
          example_path_3d = dir_path / "example" / "example_ntp.txt"
        case _:
          example_path_3d = dir_path / "example" / "example.txt"

    manual_path_py = dir_path / "DSL" / "python_coding_style.txt"
    example_path_py = dir_path / "example" / "python_example.txt"

    if not manual_path_3d.exists() or not example_path_3d.exists():
      raise FileNotFoundError(
        f"3d_syntax_check.txt or example.txt not found in {dir_path / 'DSL'} or {dir_path / 'example'}"
      )
    if not manual_path_py.exists() or not example_path_py.exists():
      raise FileNotFoundError(
        f"python_coding_style.txt or python_example.txt not found in {dir_path / 'DSL'} or {dir_path / 'example'}"
      )

    builder.gen_format(
      manual_path_3d.absolute().as_posix(), example_path_3d.absolute().as_posix()
    )
    builder.gen_parser(
      manual_path_py.absolute().as_posix(), example_path_py.absolute().as_posix()
    )

    merge_manual_path_3d = manual_path_3d
    merge_example_path_3d = dir_path / "example" / "example_merge.txt"

    merge_manual_path_py = manual_path_py
    merge_example_path_py = dir_path / "example" / "example_merge_parser.txt"

    if not merge_example_path_3d.exists():
      raise FileNotFoundError(f"example_merge.txt not found in {dir_path / 'example'}")
    if not merge_example_path_py.exists():
      raise FileNotFoundError(
        f"example_merge_parser.txt not found in {dir_path / 'example'}"
      )
    builder.merge_format(
      merge_manual_path_3d.absolute().as_posix(),
      merge_example_path_3d.absolute().as_posix(),
    )
    builder.merge_parser(
      merge_manual_path_py.absolute().as_posix(),
      merge_example_path_py.absolute().as_posix(),
    )
    self.llm_cost_dollar += builder.llm_cost
    self.llm_cost_initial_generation = builder.llm_cost
    self.llm_calling_tool_time += builder.time_spent_not_chatting
    self.llm_chat_time += builder.time_spent_chatting
    self.log_info(f"LLM cost for building graph: ${builder.llm_cost:.4f}")
    # collect element mapping information
    builder.map_elements()
    # Finally merge content for doc graph
    from src.doc_graph import ContentMerger

    # builder.doc_graph = builder.doc_graph.bottom_up(ContentMerger())
    self.doc_graph = builder.doc_graph

  def test_against(self, parser_path: str):
    if self.encode_count <= 0:
      return TestResult(TestResultType.SKIP, dummy_detail)
    if self.doc_graph is None:
      raise ValueError("Document graph is not built yet.")
    from src.refine.tester import Tester
    # from src.parallel_work.parallel import ParallelTestManager as Tester

    if self.doc_graph_builder is None:
      raise ValueError("Document graph builder is not set.")
    tester = Tester(
      self.doc_graph_builder.doc_graph,
      encode_count=self.encode_count,
      make_branch_for_empty=self.make_branch_for_empty,
      disable_opt_i=self.disable_opt_i,
      disable_opt_ii=self.disable_opt_ii,
      disable_opt_iii=self.disable_opt_iii,
    )
    tester.mute = self.mute
    self.paths_after_optimization = len(tester.testcase_generators)
    self.paths_before_optimization = tester.full_path_count

    if not self.only_generate_cases:
      result = tester.test(parser_path, self.skips)
    else:
      result = TestResult(TestResultType.SKIP, dummy_detail)
    # skip storing testcases if result is bad
    self.solver_time_cost += tester.smt_time_cost
    self.time_testing_against_format += tester.format_time_cost
    self.time_testing_against_parser += tester.parser_time_cost
    if result.result_type not in (
      TestResultType.CORRECT_PASS_INCORRECT_FAIL,
      TestResultType.CORRECT_PASS,
      TestResultType.SKIP,
    ):
      return result
    return result

  def test_against_parallel(self, parser_path: str):
    if self.doc_graph is None:
      raise ValueError("Document graph is not built yet.")
    from src.parallel_work.parallel import ParallelTestManager as Tester

    if self.doc_graph_builder is None:
      raise ValueError("Document graph builder is not set.")
    tester = Tester(
      self.doc_graph_builder.doc_graph,
      self.doc_graph_builder.doc_graph_json_path,
      encode_count=self.encode_count,
      workers=10,
    )
    if not self.only_generate_cases:
      result = tester.execute(parser_path, self.skips)
    else:
      result = TestResult(TestResultType.SKIP, dummy_detail)
    correct_cases = tester.generate_correct_cases_parallel()
    return result

  def run_test(self):
    if self.doc_graph is None:
      raise ValueError("Document graph is not built yet.")

    from src.refine.test_result import TestResultType

    while (
      (
        result := (
          self.test_against_parallel if self.use_parallel else self.test_against
        )(self.doc_graph.root.parser_path or "")
      ).result_type
    ) not in (
      TestResultType.CORRECT_PASS_INCORRECT_FAIL,
      TestResultType.CORRECT_PASS,
      TestResultType.SKIP,
    ):
      return result
    return TestResult(TestResultType.CORRECT_PASS_INCORRECT_FAIL, dummy_detail)

  def _run(self):
    from src.log import add_file_handler
    from datetime import datetime

    log_file_dir = Path(f"{self.data_directory}/logs")
    log_file_dir.mkdir(parents=True, exist_ok=True)
    add_file_handler(
      f"{self.data_directory}/logs/{self.protocol_name}_driver_{datetime.now()}.log"
    )
    time_begin = time.time()
    with self.step("Driver Run"):
      if self.run_wo_rfc:
        self.log_info("Running without-RFC ablation study...")
        self.sub_driver_wo_rfc.run()
        self.log_info("Without-RFC ablation completed.")
        return
      with self.step("Preparing Document Graph"):
        if self.doc_graph is None:
          self.log_info("Document graph not found, building...")
          self.build_graph()
          self.log_info(
            f"Document graph built. Saved to {(Path(self.data_directory) / 'RFC' / self.protocol_name).absolute().as_posix()}.json"
          )
      assert self.doc_graph_builder is not None
      assert self.doc_graph is not None
      from src.refine import Refiner
      from src.refine.test_result import TestResultType

      self.initial_format = self.doc_graph.root.format_path
      self.initial_parser = self.doc_graph.root.parser_path
      if not self.initial_format or not self.initial_parser:
        raise ValueError("Initial format or parser path is not set in document graph.")
      self.log_info(
        f"Initial format: {self.initial_format}, Initial parser: {self.initial_parser}"
      )

      with self.step("Refinement Loop"):
        example_path_3d = (
          Path(self.data_directory)
          / "example"
          / f"example_{self.protocol_name.lower()}.txt"
        )
        if not example_path_3d.exists():
          match self.protocol_name.lower():
            case "ptcs":
              example_path_3d = (
                Path(self.data_directory) / "example" / "example_sctp.txt"
              )
            case "pgb-x":
              example_path_3d = Path(self.data_directory) / "example" / "example.txt"
            case "ptn":
              example_path_3d = (
                Path(self.data_directory) / "example" / "example_ntp.txt"
              )
            case _:
              example_path_3d = Path(self.data_directory) / "example" / "example.txt"
        self.log_info(f"Example path for 3d: {example_path_3d} ")
        if not example_path_3d.exists():
          raise FileNotFoundError(
            f"example_{self.protocol_name.lower()}.txt or example.txt not found in {Path(self.data_directory) / 'example'}"
          )
        refiner = Refiner(
          self.doc_graph_builder,
          self.data_directory + "/DSL/3d_syntax_check.txt",
          example_path_3d.absolute().as_posix(),
          self.data_directory + "/DSL/python_coding_style.txt",
          self.data_directory + "/example/python_example.txt",
        )
        self.log_info("Starting refinement loop...")
        # if a case is wrong for too many times, we skip it and store it for manual check
        self.skip_dict = {}
        self.skips = set()

        while (result := self.run_test()).result_type not in (
          TestResultType.CORRECT_PASS_INCORRECT_FAIL,
          TestResultType.CORRECT_PASS,
        ):
          self.log_warning(f"Test resulted in {result.result_type.name}, refining...")
          bug_descriptions = None
          if result.result_type is TestResultType.SKIP:
            continue
          with open(result.details.input_path, "rb") as f:
            input_data = f.read()
          if (bug_descriptions := refiner.identify_bug(result))[
            "buggy_code"
          ] in ("Neither", "Unknown"):
            self.skips.add(" && ".join(result.details.negated_path_conditions or []))
            self.skips.add(str(input_data.hex()))
          if result.details.negated_path_conditions is not None:
            self.skip_dict[" && ".join(result.details.negated_path_conditions)] = (
              self.skip_dict.get(" && ".join(result.details.negated_path_conditions), 0)
              + 1
            )
            if self.skip_dict[" && ".join(result.details.negated_path_conditions)] >= 5:
              self.log_warning(f"Skipping result {result} after 5 attempts.")
              self.skips.add(" && ".join(result.details.negated_path_conditions))
              self.skips.add(str(input_data.hex()))
              continue
          if input_data:
            self.skip_dict[str(input_data.hex())] = (
              self.skip_dict.get(str(input_data.hex()), 0) + 1
            )
            if self.skip_dict[str(input_data.hex())] >= 5:
              self.log_warning(f"Skipping result {result} after 5 attempts.")
              self.skips.add(" && ".join(result.details.negated_path_conditions or []))
              self.skips.add(str(input_data.hex()))
              continue
          self.log_info("Clearing stored testcases...")
          self.testcases.clear()
          # We want to always refine the root parser or format
          if result.details.related_format:
            result.details.related_format = self.doc_graph.root.format_path or ""
          if result.details.related_parser:
            result.details.related_parser = self.doc_graph.root.parser_path or ""
          refiner.refine(result, bug_descriptions=bug_descriptions)
      self.log_info("Refinement loop completed.")
      time_end = time.time()
      self.runtime = time_end - time_begin
      self.refinement_rounds = len(refiner.rounds)
      self.llm_calling_tool_time += refiner.time_calling_tool
      self.llm_cost_dollar += refiner.cost
      self.log_info("Packaging generated results...")
      self.packet_generated_results(rounds=refiner.rounds)

  @override
  def run(self):
    from src.ablation.without_rfc import DriverWORFC

    driver_worf = DriverWORFC(self.protocol_name, self.data_directory)
    self.sub_driver_wo_rfc = driver_worf
    self._run_method()

  def _run_method(self) -> NoReturn | None:
    raise NotImplementedError("_run_method is not made by debug_decorator_factory yet.")

  def packet_generated_results(
    self, doc_tree_file: str = "", rounds: "list[Round] | None" = None
  ):
    with self.step("Package Generated Results"):
      if not doc_tree_file:
        if self.doc_graph is None:
          raise ValueError("Document graph is not built yet.")
        else:
          from pathlib import Path

          if self.doc_graph_builder is None:
            raise ValueError("Document graph directory is not set.")
          doc_file_json = (
            Path(self.doc_graph_builder.doc_graph_directory)
            / f"{self.doc_graph_builder.get_protocol_name()}.json"
          )
      else:
        from pathlib import Path

        doc_file_json = Path(doc_tree_file)

      import json
      from src.doc_graph import DocumentGraph

      doc_graph: DocumentGraph = DocumentGraph.decode(
        json.dumps(json.load(open(doc_file_json)))
      )

      package_directory = Path(self.data_directory) / "packaged_results"
      package_directory.mkdir(parents=True, exist_ok=True)

      from uuid import uuid4

      if not self.doc_graph_builder:
        raise ValueError("Document graph builder is not set.")
      product_directory = (
        package_directory
        / f"{self.doc_graph_builder.get_protocol_name()}_{uuid4().hex[:8]}"
      )
      product_directory.mkdir(parents=True, exist_ok=True)

      format_path = Path(doc_graph.root.format_path or "")
      parser_path = Path(doc_graph.root.parser_path or "")

      if not format_path.exists() or not parser_path.exists():
        raise FileNotFoundError(
          f"Format file or parser file not found: {format_path}, {parser_path}"
        )
      for thing in (format_path, parser_path, doc_file_json):
        dest_path = product_directory / thing.name
        self.log_info(
          f"Format path: {format_path}, parser path: {parser_path}, doc graph path: {doc_file_json}"
        )
        self.log_info(f"Copying {thing} to {dest_path} ")
        with open(thing, "r") as src_file, open(dest_path, "w") as dest_file:
          dest_file.write(src_file.read())  # pyright: ignore[reportUnusedCallResult]
        logger.info(f"Copied {thing} to {dest_path} ")

