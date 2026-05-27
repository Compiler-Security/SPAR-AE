from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor, as_completed
from src.doc_graph import DocumentGraphBuilder
from src.doc_graph.document_graph import DocumentGraph
from collections.abc import Generator, Mapping, Sequence
import logging
from logging import handlers
import multiprocessing
from typing import TYPE_CHECKING, final, override
from src.log import StepLogger, console
from rich.progress import (
  Progress,
  SpinnerColumn,
  TextColumn,
  TimeElapsedColumn,
  BarColumn,
)

if TYPE_CHECKING:
  from src.fsm import Path, FSM
  from src.doc_graph import DocumentGraph
  from src.parse3d import Module, ParserContext, PathCondition, Expr
  from src.encode import PathTestcaseGenerator
  from src.refine import TestResult


@final
class ParallelTestManager(StepLogger):
  @override
  def run(self):
    pass  # dummy implementation

  def __init__(
    self,
    doc_graph: "DocumentGraph",
    doc_graph_path: str,
    encode_count: int = 1,
    workers: int = 64,
  ):
    super().__init__("ParallelTestManager")
    from src.parse3d import Expr

    Expr.use_cache = False  # disable expression caching for parallel execution

    self.doc_graph: DocumentGraph = doc_graph
    self.doc_graph_path: str = doc_graph_path
    self.encode_count = encode_count
    self.workers = workers
    from src.parse3d import Parse3D
    from src.fsm import FSMBuilder
    from src.encode import PathTestcaseGenerator
    from src.parse3d import CollectPathCondition

    if self.doc_graph.root.format_path is None:
      raise ValueError("DocumentTree root must have a format file.")
    with open(self.doc_graph.root.format_path, "r", encoding="utf-8") as f:
      format_code: str = f.read()
    self.format_code: str = format_code
    self.parser: "Parse3D" = Parse3D(format_code)
    self.ast: "Module" = self.parser.parse()

    if self.ast.entrypoint is None:
      raise ValueError("The format file must have an entrypoint.")

    self.ctx: "ParserContext" = self.parser.context

    self.fsm_map: "dict[str, FSM]" = FSMBuilder().build(self.ast, self.ctx)
    self.entry_fsm = self.fsm_map[
      self.ast.entrypoint
    ]  # we want to test and refine this fsm
    self.paths = self.entry_fsm.save_all_paths()
    self.encode_count = encode_count

    self.path_conditions: dict[str, dict[str, "PathCondition"]] = (
      CollectPathCondition().collect(self.ast, self.ctx)
    )
    self.testcase_generators: "list[PathTestcaseGenerator]" = [
      PathTestcaseGenerator(
        path, self.ast, self.ctx, self.path_conditions, self.encode_count, mute=True
      )
      for path in self.paths
    ]  # one generator for each path

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
    section_numbers = ParallelTestManager.get_related_section_number(
      doc_graph, current_diff
    )
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

  def split_works(self) -> Generator[list[PathTestcaseGenerator], None, None]:
    current_batch: list[PathTestcaseGenerator] = []
    for generator in self.testcase_generators:
      current_batch.append(generator)
      if len(current_batch) >= self.workers:
        yield current_batch
        current_batch = []
    if len(current_batch) > 0:
      yield current_batch

  @staticmethod
  def worker_generate_cases(
    worker_id: int,
    work_batch: list[PathTestcaseGenerator],
    case_queue: multiprocessing.Queue[dict[str, list[bytes]]],
  ) -> None:
    for generator in work_batch:
      correct_cases = generator.correct_cases
      case_queue.put(
        {
          generator.path.__str__(): correct_cases,
        }
      )

  def generate_correct_cases_parallel(self):
    correct_cases: dict[str, list[bytes]] = {}
    # generate correct cases in parallel
    manager = multiprocessing.Manager()
    case_queue: multiprocessing.Queue[dict[str, list[bytes]]] = manager.Queue()  # pyright: ignore[reportAssignmentType]
    with ProcessPoolExecutor(max_workers=self.workers) as executor:
      futures = []
      for worker_id, work_batch in enumerate(self.split_works()):
        future = executor.submit(
          self.worker_generate_cases,
          worker_id,
          work_batch,
          case_queue,
        )
        futures.append(future)  # pyright: ignore[reportUnknownMemberType]

      for future in as_completed(futures):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        try:
          _ = future.result()  # retrieve result to raise exceptions if any  # pyright: ignore[reportUnknownVariableType]
        except Exception as e:
          import traceback

          self.log_error(f"A worker process raised an exception: {e}")
          self.log_error(traceback.format_exc())
          continue
    for _ in range(len(self.testcase_generators)):
      case_dict = case_queue.get()
      correct_cases.update(case_dict)
    return correct_cases

  def generate_incorrect_cases_parallel(self):
    pass  # dummy implementation

  @staticmethod
  def run_parser(parser_path: str, testcase: bytes) -> tuple[int, str, str, str]:
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(delete=False) as tmpfile:
      run_command = f"python {parser_path} {tmpfile.name}"
      _ = tmpfile.write(testcase)
      tmpfile.flush()
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
  def test_against_parser(
    doc_graph_path: str,
    entrypoint_name: str,
    worker_id: int,
    generators: list[PathTestcaseGenerator],
    parser_path: str,
    result_queue: multiprocessing.Queue[TestResult],
    log_queue: multiprocessing.Queue[str],
    skips: set[str] | None = None,
  ) -> None:
    worker_logger = logging.getLogger(f"Worker-{worker_id}")
    qh = handlers.QueueHandler(log_queue)
    worker_logger.addHandler(qh)
    worker_logger.setLevel(logging.INFO)
    doc_graph = DocumentGraphBuilder.load_from_json(doc_graph_path)
    format_code = ""
    with open(doc_graph.root.format_path or "", "r", encoding="utf-8") as f:
      format_code = f.read()
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

    last_diff: list[str] = [entrypoint_name]
    last_fsm_seq: list[str] = []
    current_fsm_seq: list[str] = []
    worker_logger.info(msg=f"Testing parser at path: {parser_path}")
    worker_logger.info(msg=f"Total testcase generators: {len(generators)}")
    for generator in generators:
      # compute current_fsm_seq
      current_fsm_history = list(
        map(
          lambda x: x.fsm.name,  # pyright: ignore[reportOptionalMemberAccess]
          filter(
            lambda x: x.kind in (PathNodeKind.FSM_START, PathNodeKind.FSM_END)
            and x.fsm is not None,
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
          if len(name_stack) == 0 or name_stack[-1] != fsm_name:  # entering a new fsm
            name_stack.append(fsm_name)
            fsm_seq.append(prefix_removed_name)
          else:  # exiting the current fsm
            _ = name_stack.pop()
        return fsm_seq

      current_fsm_seq = restore_fsm_seq(current_fsm_history)

      worker_logger.info(f"Current FSM sequence: {current_fsm_seq}")
      current_diff = cmp_fsm_seq(last_fsm_seq, current_fsm_seq)
      if not current_diff:
        current_diff = last_diff
      last_fsm_seq = current_fsm_seq
      last_diff = current_diff
      worker_logger.info(f"Current diff FSM sequence: {current_diff}")
      worker_logger.info(f"Generating correct cases for path:\n {generator.path}")
      try:
        correct_cases = generator.correct_cases
        worker_logger.info(f"Generated {len(correct_cases)} correct cases.")
      except EncoderError as e:
        # TODO: report this encoding error to LLM to detect potential issues in the format specification
        worker_logger.warning(
          f"Encoding error when generating correct case: {' -> '.join(current_fsm_seq)}"
        )
        worker_logger.warning(
          f"Unsat core: {e if e.unsat_core is None else e.unsat_core}"  # pyright: ignore[reportUnknownMemberType]
        )
        continue

      for idx, correct_case in enumerate(correct_cases):
        correct_run = ParallelTestManager.run_parser(parser_path, correct_case)
        correct_exit_code, correct_stdout, correct_stderr, correct_packet_path = (
          correct_run
        )

        if correct_exit_code != 0:
          worker_logger.warning("Correct case failed to parse")
          worker_logger.warning(f"Stdout: {correct_stdout}")
          worker_logger.warning(f"Stderr: {correct_stderr}")
          worker_logger.warning(
            f"Values: \n{'  \n'.join(f'{k}: {v}' for k, v in generator.correct_case_table[idx].items())}"
          )
          result = TestResult(
            TestResultType.CORRECT_FAIL,
            TestResultDetail(
              correct_stdout + "\n\n" + correct_stderr,
              format_code,
              ParallelTestManager.get_related_parser(doc_graph, current_diff),
              ParallelTestManager.get_related_sections(doc_graph, current_diff),
              ParallelTestManager.get_related_section_number(doc_graph, current_diff),
              None,
              correct_packet_path,
            ),
          )
          result_queue.put(result)
          return  # no need to continue testing

      worker_logger.info("Generating incorrect cases")
      for path_condition, incorrect_cases in generator.incorrect_cases.items():
        worker_logger.info(
          f"Testing incorrect cases for path {' -> '.join(current_fsm_seq)} with path condition: {' && '.join(map(str, path_condition.constraints))}"
        )
        for path, incorrect_case in incorrect_cases.items():
          for idx, case in enumerate(incorrect_case):
            incorrect_run = ParallelTestManager.run_parser(parser_path, case)
            (
              incorrect_exit_code,
              incorrect_stdout,
              incorrect_stderr,
              incorrect_packet_path,
            ) = incorrect_run
            if incorrect_exit_code == 0:
              worker_logger.warning(f"Incorrect case unexpectedly parsed: {path}")
              worker_logger.warning(
                f"Path condition: {' && '.join(map(str, path_condition.constraints))}"
              )
              worker_logger.warning(
                f"Values: \n{'  \n'.join(f'{k}: {v}' for k, v in generator.incorrect_case_table[path_condition][idx].items())}"
              )
              worker_logger.info(f"Stdout: {incorrect_stdout}")
              worker_logger.info(f"Stderr: {incorrect_stderr}")
              worker_logger.info(f"Packet Path: {incorrect_packet_path}")
              worker_logger.info(f"Parser Path: {parser_path}")
              worker_logger.info(f"Packet : {case.hex()}")
              result = TestResult(
                TestResultType.CORRECT_PASS_INCORRECT_PASS,
                TestResultDetail(
                  f"{incorrect_stdout}\n\n{incorrect_stderr}",
                  format_code,
                  ParallelTestManager.get_related_parser(doc_graph, current_diff),
                  ParallelTestManager.get_related_sections(doc_graph, current_diff),
                  ParallelTestManager.get_related_section_number(
                    doc_graph, current_diff
                  ),
                  tuple(map(str, path_condition.constraints))
                  if path_condition
                  else None,
                  incorrect_packet_path,
                ),
              )
              if (
                skips
                and " && ".join(result.details.negated_path_conditions or []) in skips
              ):
                worker_logger.warning(
                  "Skipping this result as it has been skipped before."
                )
                continue
              result_queue.put(result)
              return  # no need to continue testing
    # all incorrect cases failed as expected
    from src.refine.test_result import dummy_detail

    worker_logger.info("All test cases passed as expected.")
    result_queue.put(
      TestResult(
        TestResultType.CORRECT_PASS_INCORRECT_FAIL,
        dummy_detail,
      )
    )

  def listen_logs(self, log_queue: multiprocessing.Queue[str]) -> None:
    listener_logger = logging.getLogger("Listener")
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
      "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    listener_logger.addHandler(handler)
    listener_logger.setLevel(logging.INFO)

    while True:
      try:
        record = log_queue.get()
        if record == "STOP":
          break
        listener_logger.info(record)
      except Exception:
        import sys
        import traceback

        self.log_error("Error in log listener:")
        traceback.print_exc(file=sys.stderr)

  def execute(self, parser_path: str, skips: set[str] | None = None) -> TestResult:
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from src.refine.test_result import TestResultType

    manager = multiprocessing.Manager()
    log_queue: multiprocessing.Queue[str] = manager.Queue()  # pyright: ignore[reportAssignmentType]
    listener_process = multiprocessing.Process(
      target=self.listen_logs, args=(log_queue,)
    )
    listener_process.start()

    result_queue: multiprocessing.Queue[TestResult] = manager.Queue()  # pyright: ignore[reportAssignmentType]

    with ProcessPoolExecutor(max_workers=self.workers) as executor:
      futures = []
      for worker_id, work_batch in enumerate(self.split_works()):
        future = executor.submit(
          self.test_against_parser,
          self.doc_graph_path,
          self.entry_fsm.name,
          worker_id,
          work_batch,
          parser_path,
          result_queue,
          log_queue,
          skips,
        )
        futures.append(future)  # pyright: ignore[reportUnknownMemberType]

      with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
      ) as progress:
        task = progress.add_task("[green]Testing in parallel...", total=len(futures))  # pyright: ignore[reportUnknownArgumentType]
        for future in as_completed(futures):  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
          try:
            future.result()  # retrieve result to raise exceptions if any
            # check if there is a test failure in the result queue
            result = None
            while not result_queue.empty():
              result = result_queue.get()
              if result.result_type not in (
                TestResultType.CORRECT_PASS_INCORRECT_FAIL,
                TestResultType.SKIP,
              ):
                log_queue.put(
                  f"A test failure has been detected by a worker process: {result.result_type}"
                )
                # forcefully shutdown all workers
                for process in executor._processes.values():
                  process.kill()
                executor.shutdown(wait=True, cancel_futures=True)
                # stop the listener
                log_queue.put("STOP")
                listener_process.join()
                return result
            progress.update(task, advance=1)
          except Exception as e:
            import traceback

            self.log_error(f"A worker process raised an exception: {e}")
            self.log_error(traceback.format_exc())

    # all workers are done, stop the listener
    log_queue.put("STOP")
    listener_process.join()

    # process results

    all_passed = True
    last_result: TestResult | None = None
    while not result_queue.empty():
      result = result_queue.get()
      if result.result_type != TestResultType.CORRECT_PASS_INCORRECT_FAIL:
        all_passed = False
        return result
      last_result = result
    if all_passed:
      self.log_info("All tests passed.")
      if last_result is None:
        from src.refine.test_result import dummy_detail, TestResult

        return TestResult(
          TestResultType.CORRECT_PASS_INCORRECT_FAIL,
          dummy_detail,
        )
      return last_result
    else:
      assert False, "Should not reach here"
