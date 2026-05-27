from __future__ import annotations
from enum import Enum
from typing import TYPE_CHECKING, TypedDict, override
from typing_extensions import final
from src.log import StepLogger


if TYPE_CHECKING:
  from src.doc_graph import DocumentGraphBuilder
  from src.refine.test_result import TestResult
  from src.doc_graph import DocumentGraph


class FixedWhat(Enum):
  FORMAT = "3D Format"
  PARSER = "Python Parser"
  NEITHER = "Neither"


class Round(TypedDict):
  bug_descriptions: dict[str, str]
  format_code: str
  parser_code: str
  fixed_code: str
  fixed_what: FixedWhat


@final
class Refiner(StepLogger):
  def __init__(
    self,
    doc_graph_builder: "DocumentGraphBuilder",
    manual_path_3d: str,
    example_path_3d: str,
    manual_path_py: str,
    example_path_py: str,
  ):
    super().__init__("Refiner")
    self.doc_graph_builder = doc_graph_builder
    if self.doc_graph_builder.doc_graph is None:  # pyright: ignore[reportUnnecessaryComparison]
      raise ValueError("DocumentGraphBuilder must have a built DocumentGraph.")
    # read file contents
    with open(manual_path_3d, "r", encoding="utf-8") as f:
      self.manual_3d = f.read()
    with open(example_path_3d, "r", encoding="utf-8") as f:
      self.example_3d = f.read()
    with open(manual_path_py, "r", encoding="utf-8") as f:
      self.manual_py = f.read()
    with open(example_path_py, "r", encoding="utf-8") as f:
      self.example_py = f.read()
    self.rounds: list[Round] = []
    self.cost: float = 0.0
    self.time_cost: float = 0.0
    self.time_calling_tool: float = 0.0

  @property
  def doc_graph(self) -> "DocumentGraph":
    if self.doc_graph_builder.doc_graph is None:  # pyright: ignore[reportUnnecessaryComparison]
      raise ValueError("DocumentGraphBuilder must have a built DocumentGraph.")
    return self.doc_graph_builder.doc_graph

  @override
  def run(self) -> None:
    pass  # dummy implementation

  def identify_bug(self, test_result: "TestResult") -> dict[str, str]:
    from src.agent import IdentifyBugAgent
    from src.refine.test_result import TestResultType

    agent = IdentifyBugAgent()

    with open(test_result.details.input_path, "rb") as f:
      input_data = f.read()

    self.log_info(f"Test result type: {test_result.result_type}")
    self.log_info("Related parser code:\n" + test_result.details.related_parser)
    self.log_info("Related format code:\n" + test_result.details.related_format)
    self.log_info("Related section content:\n" + test_result.details.related_section)
    self.log_info(
      "Related section numbers: "
      + ", ".join(test_result.details.related_section_number)
    )
    self.log_info(f"Input data (hex): {input_data.hex()}")
    self.log_info(f"Parser output: {test_result.details.parser_output}")
    self.log_info(
      f"Negated path conditions: {test_result.details.negated_path_conditions}"
    )
    if test_result.result_type is TestResultType.CORRECT_FAIL:
      bug_description = agent.identify_correct_fail(
        test_result.details.related_format,
        test_result.details.related_parser,
        test_result.details.related_section,
        test_result.details.parser_output,
        input_data.hex(),
      )
    elif test_result.result_type is TestResultType.CORRECT_PASS_INCORRECT_PASS:
      bug_description = agent.identify_incorrect_pass(
        test_result.details.related_format,
        test_result.details.related_parser,
        test_result.details.related_section,
        test_result.details.parser_output,
        input_data.hex(),
        " and ".join(test_result.details.negated_path_conditions or []),
      )
    else:
      raise ValueError(f"Unknown test result type: {test_result.result_type}")
    self.cost += agent.thinking_agent.cost
    self.time_cost += agent.thinking_agent.time_chat
    return bug_description

  def refine_parser(self, bug_descriptions: dict[str, str], section_num: str):
    from src.agent import RefinePyAgent

    with self.step("Python Parser"):
      self.log_info(f"Refining Python parser (bug in section {section_num}, using root code)...")
      # Always use root (merged) code so the fixer has full context.
      # section_num only identifies which RFC section the bug relates to.
      root_node = self.doc_graph.root
      if root_node.parser_path is None:
        raise ValueError("Root section does not have an associated parser.")
      with open(root_node.parser_path, "r", encoding="utf-8") as f:
        buggy_code = f.read()
      self.log_info("Starting Python parser refinement agent...")
      self.log_info("Buggy code:\n" + buggy_code)
      agent = RefinePyAgent(
        self.manual_py,
        self.example_py,
        buggy_code,
        bug_descriptions["instruction"],
        self.doc_graph_builder.data_directory,
      )
      success = False
      while not success:
        try:
          _ = agent.start()
          success = True
        except Exception as e:
          self.log_warning(f"Error during refinement: {e}. Retrying...")
          agent.reset_cost_and_time()
          continue
      refined_code_path = agent.product
      root_node.update_parser_path(refined_code_path)
      self.doc_graph.root.parser_path = refined_code_path
      self.log_info(
        f"Refined Python parser saved to {refined_code_path}, updating document graph..."
      )
      self.doc_graph_builder.write_back_to_file()
      self.log_info("Document graph updated.")
      self.cost += agent.cost
      self.time_cost += agent.time_chat
      self.time_calling_tool += agent.time_calling_register_function
      return refined_code_path

  def refine_format(self, bug_descriptions: dict[str, str], section_num: str):
    from src.agent import Refine3DAgent

    with self.step("3D Format"):
      self.log_info(message=f"Refining 3D format (bug in section {section_num}, using root code)...")
      # Always use root (merged) code so the fixer has full context.
      root_node = self.doc_graph.root
      if root_node.format_path is None:
        raise ValueError("Root section does not have an associated format.")
      with open(root_node.format_path, "r", encoding="utf-8") as f:
        buggy_code = f.read()
      self.log_info("Starting 3D format refinement agent...")
      self.log_info("Buggy code:\n" + buggy_code)
      agent = Refine3DAgent(
        self.manual_3d,
        self.example_3d,
        buggy_code,
        bug_descriptions["instruction"],
        self.doc_graph_builder.data_directory,
      )
      success = False
      while not success:
        try:
          _ = agent.start()
          success = True
        except Exception as e:
          self.log_warning(f"Error during refinement: {e}. Retrying...")
          continue
      refined_code_path = agent.product
      root_node.update_format_path(refined_code_path)
      self.doc_graph.root.format_path = refined_code_path
      self.log_info(
        f"Refined 3D format saved to {refined_code_path}, updating document graph..."
      )
      self.doc_graph_builder.write_back_to_file()
      self.log_info("Document graph updated.")
      self.cost += agent.cost
      self.time_cost += agent.time_chat
      self.time_calling_tool += agent.time_calling_register_function
      return refined_code_path

  def refine(
    self, test_result: "TestResult", bug_descriptions: dict[str, str] | None = None
  ):
    with self.step("Refinement"):
      self.log_info("Starting refinement process...")
      if bug_descriptions is None:
        self.log_warning("Bug descriptions not provided, identifying bug...")
        bug_descriptions = self.identify_bug(test_result)
      self.log_info("Bug descriptions identified.")
      this_round = Round(
        bug_descriptions=bug_descriptions,
        format_code="",
        parser_code="",
        fixed_code="",
        fixed_what=FixedWhat.NEITHER,
      )
      this_round["format_code"] = test_result.details.related_format
      this_round["parser_code"] = test_result.details.related_parser
      refined_code_path = ""
      self.log_info(
        f"Identified bug descriptions:\n {'\n'.join(f'{k}: {v}' for k, v in bug_descriptions.items())}"
      )
      self.log_info(
        "Related sections (for RFC context): "
        + ", ".join(test_result.details.related_section_number)
      )
      root_section_num = self.doc_graph.root.number
      if "3D" in bug_descriptions["buggy_code"]:
        refined_code_path = self.refine_format(bug_descriptions, root_section_num)
        this_round["fixed_what"] = FixedWhat.FORMAT
      elif "Parser" in bug_descriptions["buggy_code"]:
        refined_code_path = self.refine_parser(bug_descriptions, root_section_num)
        this_round["fixed_what"] = FixedWhat.PARSER
      else:
        self.log_warning(
          f"Unknown buggy code type: {bug_descriptions['buggy_code']}"
        )
        this_round["fixed_what"] = FixedWhat.NEITHER
      if refined_code_path:
        with open(refined_code_path, "r", encoding="utf-8") as f:
          this_round["fixed_code"] = f.read()
      self.rounds.append(this_round)
      self.log_info("Recorded refinement round.")
