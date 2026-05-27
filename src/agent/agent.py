from __future__ import annotations
from collections.abc import Sequence
import functools
from pathlib import Path
import re
import shutil
import time
from typing import Any, Callable, TypedDict, final, override
import uuid
from pydantic import BaseModel
from autogen.agentchat import ChatResult
from autogen.agentchat.assistant_agent import AssistantAgent
from autogen.llm_config import LLMConfig
from src.log import StepLogger

import autogen
import json
import inspect

from src.secret import config_list, config_list_reasoner, ConfigList
from src.tool import todo


@final
class TerminationTracker:
  def __init__(
    self,
    termination_func: Callable[[dict[str, Any]], bool],  # pyright: ignore[reportExplicitAny]
    other: PairLoopAgent,
  ):
    self.termination_func = termination_func
    self.triggered: bool = False
    self.other: PairLoopAgent = other

  def __call__(self, msg: dict[str, Any]) -> bool:  # pyright: ignore[reportExplicitAny]
    result = self.termination_func(msg)
    if result is True:
      self.triggered = True
      self.other.created_product = True
    return result

  def reset(self):
    self.triggered = False


# ----------------------- Singular agent definition starts here ----------------------- #


# A singular agent that can be used to ask questions or think
class SingularAgent:
  def reset_cost_and_time(self):
    self.cost = 0.0
    self.time_chat = 0.0

  def __init__(
    self,
    config_list: list[ConfigList],
    response_format: str | dict[str, Any] | None = None,  # pyright: ignore[reportExplicitAny]
  ):
    self._response_format = response_format
    self.client: AssistantAgent = autogen.AssistantAgent(
      name="Agent",
      llm_config=LLMConfig(config_list=config_list, response_format=response_format),  # pyright: ignore[reportArgumentType]
      code_execution_config=False,
      human_input_mode="NEVER",
      function_map=None,
    )
    self.cost: float = 0.0
    self.time_chat: float = 0.0

  def invoke(self, input_data: str):
    response: str | dict[str, Any] | None = None  # pyright: ignore[reportExplicitAny]\
    # try invking until success or max retry
    max_retry = 10
    for _ in range(max_retry):
      try:
        time_start = time.time()
        response = self.client.generate_reply(json.loads(input_data)["messages"])  # pyright: ignore[reportAny]
        time_end = time.time()
        break
      except Exception as e:
        continue
        # print(f"Error: {e}, retrying...")
    if response is None:
      raise RuntimeError("Failed to get response from OpenAI API")
    self.time_chat += time_end - time_start  # pyright: ignore[reportOperatorIssue, reportPossiblyUnboundVariable]
    if self.client.get_total_usage() is not None:
      self.cost += self.client.get_total_usage().get("total_cost", 0.0)  # pyright: ignore[reportOptionalMemberAccess]
    print(f"Cost: {self.cost:.4f}")
    print(f"Time spent on chat: {self.time_chat:.2f} seconds")
    return response

  def ask(self, prompt: str, system_message: str = ""):
    body = json.dumps(
      {
        "messages": [{"role": "user", "content": prompt}]
        if system_message == ""
        else [
          {"role": "system", "content": system_message},
          {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
      }
    )
    try:
      response = self.invoke(body)
      # AutoGen's generate_reply returns the raw content string even when
      # response_format is set to a Pydantic model.  Try JSON-parse when a
      # format is configured, so callers get structured data directly.
      if isinstance(response, str) and self._response_format is not None:
        try:
          return json.loads(response)
        except Exception:
          pass
      return response
    except Exception as e:
      print(f"Error: {e}")
      return ""


@final
class AskAgent(SingularAgent):
  def __init__(self, response_format: str | dict[str, Any] | None = None):  # pyright: ignore[reportExplicitAny]
    super().__init__(config_list, response_format=response_format)


@final
class ThinkingAgent(SingularAgent):
  def __init__(self, response_format: str | dict[str, Any] | None = None):  # pyright: ignore[reportExplicitAny]
    super().__init__(config_list_reasoner, response_format=response_format)


# ----------------------- Singular agent definition ends here ----------------------- #
class BugDescription(BaseModel):
  """Pydantic model for the LLM's bug identification response."""
  buggy_code: str = "Unknown"
  explanation: str = "Unknown"
  instruction: str = "Unknown"
  rfc_reference: str = "Unknown"


@final
class IdentifyBugAgent:
  def __init__(self):
    self.thinking_agent = ThinkingAgent(response_format=BugDescription)

  def system_prompt_correct_fail(self) -> str:
    from src.tool import identify_bug_system_prompt_correct_fail

    return identify_bug_system_prompt_correct_fail()

  def user_prompt_correct_fail(
    self, three_d_code: str, py_code: str, rfc: str, parser_log: str, input_hex: str
  ) -> str:
    from src.tool import identify_bug_user_prompt_correct_fail

    return identify_bug_user_prompt_correct_fail(
      three_d_code, py_code, rfc, parser_log, input_hex
    )

  def system_prompt_incorrect_pass(self) -> str:
    from src.tool import identify_bug_system_prompt_incorrect_pass

    return identify_bug_system_prompt_incorrect_pass()

  def user_prompt_incorrect_pass(
    self,
    three_d_code: str,
    py_code: str,
    rfc: str,
    parser_log: str,
    input_hex: str,
    negated_constraint: str,
  ) -> str:
    from src.tool import identify_bug_user_prompt_incorrect_pass

    return identify_bug_user_prompt_incorrect_pass(
      three_d_code,
      py_code,
      rfc,
      parser_log,
      input_hex,
      negated_constraint,
    )

  def _parse_response(self, response: Any) -> dict[str, str]:  # pyright: ignore[reportExplicitAny]
    import logging
    _log = logging.getLogger("IdentifyBugAgent")

    _log.info(f"Response type: {type(response).__name__}")
    if isinstance(response, BugDescription):
      _log.info(f"BugDescription fields: buggy_code={response.buggy_code!r}, "
                f"instruction={response.instruction[:80]!r}...")
      return {
        "buggy_code": response.buggy_code,
        "explanation": response.explanation,
        "instruction": response.instruction,
        "rfc_reference": response.rfc_reference,
      }
    if isinstance(response, dict):
      _log.info(f"Dict keys: {list(response.keys())}")
      _log.info(f"Dict buggy_code: {response.get('buggy_code', 'MISSING')!r}")
      return {
        "buggy_code": str(response.get("buggy_code", "Unknown")),
        "explanation": str(response.get("explanation", "Unknown")),
        "instruction": str(response.get("instruction", "Unknown")),
        "rfc_reference": str(response.get("rfc_reference", "Unknown")),
      }
    _log.warning(f"Unexpected response type: {type(response).__name__}, value: {str(response)[:200]}")
    return {
      "buggy_code": "Unknown",
      "explanation": str(response),
      "instruction": "Unknown",
      "rfc_reference": "Unknown",
    }

  def identify_correct_fail(
    self, three_d_code: str, py_code: str, rfc: str, parser_log: str, input_hex: str
  ) -> dict[str, str]:
    response = self.thinking_agent.ask(
      prompt=self.user_prompt_correct_fail(three_d_code, py_code, rfc, parser_log, input_hex),
      system_message=self.system_prompt_correct_fail(),
    )
    return self._parse_response(response)

  def identify_incorrect_pass(
    self,
    three_d_code: str,
    py_code: str,
    rfc: str,
    parser_log: str,
    input_hex: str,
    negated_constraint: str,
  ) -> dict[str, str]:
    response = self.thinking_agent.ask(
      prompt=self.user_prompt_incorrect_pass(
        three_d_code, py_code, rfc, parser_log, input_hex, negated_constraint,
      ),
      system_message=self.system_prompt_incorrect_pass(),
    )
    return self._parse_response(response)


@final
class PairHierarchyAgent:
  def __init__(self):
    self.ask_agent = AskAgent()

  def system_prompt(self) -> str:
    from src.tool import pair_hierarchy_system_prompt

    return pair_hierarchy_system_prompt()

  def user_prompt(self, section1: str, section2: str) -> str:
    from src.tool import pair_hierarchy_user_prompt

    return pair_hierarchy_user_prompt(section1, section2)

  def get_hierarchy_relation(
    self, section1: str, section2: str
  ) -> tuple[str, str] | None:
    response = self.ask_agent.ask(
      prompt=self.user_prompt(section1, section2),
      system_message=self.system_prompt(),
    )
    if isinstance(response, dict):
      return response.get("relation", None)
    # try to parse the response as json
    # first remove TERMINATE token at the end if exists
    if isinstance(response, str):  # pyright: ignore[reportUnnecessaryIsInstance]
      if response.endswith("TERMINATE"):
        response = response[: -len("TERMINATE")].strip()
      if response.startswith("```") and response.endswith("```"):
        response = "\n".join(response.split("\n")[1:-1])
      try:
        response_json = json.loads(response)  # pyright: ignore[reportAny]
        return response_json.get("relation", None)  # pyright: ignore[reportAny]
      except Exception:
        message = (
          f"Failed to parse hierarchy relation response as json. Response: {response}"
        )
        raise RuntimeError(message)


@final
class SplitRoughAgent:
  def __init__(self) -> None:
    self.ask_agent = AskAgent()

  class SplitEntry(TypedDict):
    section_name: str
    start_line_number: int
    end_line_number: int
    should_related_to_implementation: bool

  class SplitsResponse(TypedDict):
    splits: list[SplitRoughAgent.SplitEntry]
    root_section: int

  def system_prompt(self) -> str:
    from src.tool import split_rough_system_prompt

    return split_rough_system_prompt()

  def user_prompt(self, rfc_text: str) -> str:
    from src.tool import split_rough_user_prompt

    return split_rough_user_prompt(rfc_text)

  def get_splits(self, rfc_text: str) -> SplitRoughAgent.SplitsResponse:
    response = self.ask_agent.ask(
      prompt=self.user_prompt(rfc_text),
      system_message=self.system_prompt(),
    )

    def convert_dict_to_split_response(
      response: dict[str, Any],  # pyright: ignore[reportExplicitAny]
    ) -> SplitRoughAgent.SplitsResponse:
      splits: list[SplitRoughAgent.SplitEntry] = []
      for entry in response.get("splits", []):  # pyright: ignore[reportAny]
        splits.append(
          {
            "section_name": entry[0],
            "start_line_number": entry[1],
            "end_line_number": entry[2],
            "should_related_to_implementation": entry[3],
          }
        )
      return SplitRoughAgent.SplitsResponse(
        splits=splits,
        root_section=response.get("root_section", 0),  # pyright: ignore[reportAny]
      )

    if isinstance(response, dict):
      return convert_dict_to_split_response(response)
    # try to parse the response as json
    try:
      # remove TERMINATE token at the end if exists
      if isinstance(response, str) and response.endswith("TERMINATE"):  # pyright: ignore[reportUnnecessaryIsInstance]
        response = response[: -len("TERMINATE")].strip()
      # remove possible code block markdown
      if (
        isinstance(response, str)  # pyright: ignore[reportUnnecessaryIsInstance]
        and response.startswith("```")
        and response.endswith("```")
      ):
        response = "\n".join(response.split("\n")[1:-1])

      response_json = json.loads(response)  # pyright: ignore[reportAny]
      return convert_dict_to_split_response(response_json)  # pyright: ignore[reportAny]
    except Exception:
      message = (
        f"Failed to parse hierarchy rough splits response as json. Response: {response}"
      )
      raise RuntimeError(message)


@final
class SummaryAgent:
  def __init__(self):
    self.ask_agent = AskAgent()

  def system_prompt(self): ...


# ----------------------- Now we define the agent loop ----------------------- #


class PairLoopAgent(StepLogger):
  def reset_cost_and_time(self):
    self.cost = 0.0
    self.time_chat = 0.0

  def __init__(
    self,
    task_prompt: str,
    system_prompt: str,
    executor_system_message: str,
    is_termination_msg: Callable[[dict[str, Any]], bool],  # pyright: ignore[reportExplicitAny]
    register_function: Callable[..., Any],  # pyright: ignore[reportExplicitAny]
    function_description: str,
    max_turns: int,
    config_list: Sequence[ConfigList],
    logger_step_name: str = "PairLoopAgent",
    chat_result_directory: str = "",
    response_format: dict[str, Any] | None = None,  # pyright: ignore[reportExplicitAny]
  ):
    StepLogger.__init__(self, logger_step_name)
    self.logger_step_name: str = logger_step_name
    self.chat_result_directory: str = chat_result_directory
    self.termination_tracker: TerminationTracker = TerminationTracker(
      is_termination_msg, self
    )
    self.engineer: AssistantAgent = autogen.AssistantAgent(
      name="Developer",
      llm_config=LLMConfig(config_list=config_list),  # pyright: ignore[reportArgumentType]
      is_termination_msg=self.termination_tracker,
      max_consecutive_auto_reply=max_turns,
      system_message=system_prompt,
    )

    self.executor: autogen.UserProxyAgent = autogen.UserProxyAgent(
      name="Executor",
      system_message=executor_system_message,
      human_input_mode="NEVER",
      code_execution_config={
        "last_n_messages": 1,
        "work_dir": "coding",
        "use_docker": False,
      },
    )
    self.chat_result: ChatResult | None = None
    self.triggered: bool = False
    self.created_product: bool = False
    from uuid import uuid4

    self.product_directory_name: str = f"product_{uuid4().hex[:6]}"

    # we want to use register_function to handle the generation product, through file system or other ways. How to get the product will be handled by subclasses.

    # wrap the register_function to measure time, need to support any signature of register_function, and pass the arguments to the original register_function
    def make_register_measure_function(func: Callable[..., Any]) -> Callable[..., Any]:  # pyright: ignore[reportExplicitAny]
      # original signature
      original_sig = inspect.signature(func)

      @functools.wraps(func)
      def register_function_time_measure(*args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportAny, reportExplicitAny]
        start_time = time.time()
        result = func(*args, **kwargs)  # pyright: ignore[reportAny]
        end_time = time.time()
        self.time_calling_register_function += end_time - start_time
        return result  # pyright: ignore[reportAny]

      # use setattr to set the __signature__ of the wrapped function to the original function's signature, so that it can be correctly recognized by autogen
      setattr(register_function_time_measure, "__signature__", original_sig)

      return register_function_time_measure

    self.register_function: Callable[[Any], Any] = make_register_measure_function(  # pyright: ignore[reportExplicitAny]
      register_function
    )
    self.task_prompt: str = task_prompt
    self.system_prompt: str = system_prompt
    self.executor_system_message: str = executor_system_message
    self.is_termination_msg: Callable[[dict[str, Any]], bool] = self.termination_tracker  # pyright: ignore[reportExplicitAny]
    self.function_description: str = function_description
    self.max_turns: int = max_turns
    _ = self.engineer.register_for_llm(
      name=self.register_function.__name__,
      description=function_description,
    )(self.register_function)
    _ = self.executor.register_for_execution(name=self.register_function.__name__)(
      self.register_function
    )
    self.cost: float = 0.0
    self.time_calling_register_function: float = 0.0
    self.time_chat: float = 0.0

  @override
  def run(self) -> None:
    pass  # dummy implementation

  def start(self):
    with self.step(self.logger_step_name):
      time_start = time.time()
      self.chat_result = self.executor.initiate_chat(
        self.engineer, message=self.task_prompt, silent=True
      )
      time_end = time.time()
      self.time_chat = time_end - time_start - self.time_calling_register_function
      from pathlib import Path
      import json

      if self.chat_result_directory != "":
        crd = Path(self.chat_result_directory)
        crd.mkdir(parents=True, exist_ok=True)
        uid = uuid.uuid4().hex[:6]
        chat_result_path = crd / self.logger_step_name / f"chat_result_{uid}.json"
        chat_result_path.parent.mkdir(parents=True, exist_ok=True)
        with open(chat_result_path, "w") as f:
          json.dump(self.chat_result.chat_history, f, indent=2)
        self.log_info(f"Chat result saved to {chat_result_path.absolute().as_posix()}")
        self.log_info(f"Cost: {self.chat_result.cost}")
        self.cost += self.chat_result.cost.get(
          "usage_including_cached_inference", {}
        ).get("total_cost", 0.0)
        self.log_info(
          f"Time spent on chat (excluding register_function time): {self.time_chat:.2f} seconds"
        )
        self.log_info(
          f"Time spent on register_function: {self.time_calling_register_function:.2f} seconds"
        )

  def is_successful(self) -> bool:
    return self.termination_tracker.triggered


class Generate3DAgent(PairLoopAgent):
  @staticmethod
  def _is_termination_msg(msg: dict[str, Any]) -> bool:  # pyright: ignore[reportExplicitAny]
    from src.tool import termination_for_3d

    return termination_for_3d(msg)

  @staticmethod
  def get_task_prompt(rfc: str) -> str:
    from src.tool import task_prompt_generate_3d

    return task_prompt_generate_3d(rfc)

  @staticmethod
  def get_developer_prompt(manual: str, example: str) -> str:
    from src.tool import developer_prompt_generate_3d

    return developer_prompt_generate_3d(manual, example)

  @staticmethod
  def _register_function(code: str, module_name: str) -> tuple[str, str]:
    from src.tool import simple_parse

    return simple_parse(code, module_name)

  def __init__(
    self,
    manual: str,
    example: str,
    rfc: str,
    chat_result_directory: str,
    max_turns: int = 15,
    config_list: list[ConfigList] = config_list,
  ):
    super().__init__(
      task_prompt=self.get_task_prompt(rfc),
      system_prompt=self.get_developer_prompt(manual, example),
      executor_system_message="Executor. Execute the 3d code written by the Developer using the custom function simple_parse. You can only execute code using the provided function!! Please ***donot infer and execute the 3D code directly***!",
      is_termination_msg=Generate3DAgent._is_termination_msg,
      register_function=Generate3DAgent._register_function,
      function_description="A function that takes 3D code as input, and returns 'EverParse succeeded!' if the code is syntactically correct, otherwise returns the error message.",
      max_turns=max_turns,
      config_list=config_list,
      chat_result_directory=chat_result_directory,
      logger_step_name="Generate3DAgent",
    )

  @property
  def product(self) -> str:
    if not self.created_product:
      raise RuntimeError("No product created yet")
    # find the latest created directory in data/3d_syntaxs
    dir_path = Path("data/3d_syntaxs")
    if not dir_path.exists():
      raise RuntimeError("No product found")
    dirs = [d for d in dir_path.iterdir() if d.is_dir()]
    if not dirs:
      raise RuntimeError("No product found")
    latest_dir = max(dirs, key=lambda d: d.stat().st_ctime)
    # find the .3d file in the directory
    files = list(latest_dir.glob("*.3d"))
    if not files:
      raise RuntimeError("No product found")
    return files[0].as_posix()

  # todo("_register_function and how to extract generated format")


class GeneratePythonAgent(PairLoopAgent):
  @staticmethod
  def _is_termination_msg(msg: dict[str, Any]) -> bool:  # pyright: ignore[reportExplicitAny]
    from src.tool import termination_for_py

    return termination_for_py(msg)

  @staticmethod
  def get_task_prompt(rfc: str) -> str:
    from src.tool import task_prompt_generate_py

    return task_prompt_generate_py(rfc)

  @staticmethod
  def get_developer_prompt(manual: str, example: str) -> str:
    from src.tool import developer_prompt_generate_py

    return developer_prompt_generate_py(manual, example)

  @property
  def product(self) -> str:
    # find the latest created directory in data/python_parser

    # if havent created any parser yet, raise error
    if not self.created_product:
      raise RuntimeError("No product created yet")
    dir_path = Path("data/python_parser")
    if not dir_path.exists():
      raise RuntimeError("No product found")
    dirs = [d for d in dir_path.iterdir() if d.is_dir()]
    if not dirs:
      raise RuntimeError("No product found")
    latest_dir = max(dirs, key=lambda d: d.stat().st_ctime)
    # find the .py file in the directory
    files = list(latest_dir.glob("*.py"))
    if not files:
      raise RuntimeError("No product found")
    return files[0].as_posix()

  def _register_function(self, code: str, module_name: str) -> str:
    def get_all_function_names(code: str) -> list[str]:
      # detect all top-level function definitions, ignoring nested functions and methods
      pattern = r"^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(.*?\):"
      return re.findall(pattern, code, re.MULTILINE)

    def ensure_calling_main(code: str) -> bool:
      # check if there is a call to main() in the code
      from ast import parse, NodeVisitor, Call, Name

      @final
      class MainCallVisitor(NodeVisitor):
        def __init__(self):
          self.found = False

        @override
        def visit_Call(self, node: Call):
          if isinstance(node.func, Name) and node.func.id == "main":
            self.found = True
          self.generic_visit(node)

      tree = parse(code)
      visitor = MainCallVisitor()
      visitor.visit(tree)
      return visitor.found

    try:
      last_parser = self.product
    except RuntimeError:
      last_parser = None
    if last_parser is not None:
      with open(last_parser, "r") as f:
        last_parser_code = f.read()
      last_parser_functions = get_all_function_names(last_parser_code)
    else:
      last_parser_functions = []

    try:
      module_name = module_name.upper()
      base_directory = Path("data/python_parser")
      base_directory.mkdir(parents=True, exist_ok=True)
      dir_path = base_directory / f"{module_name}_{uuid.uuid4().hex[:6]}"
      dir_path.mkdir(parents=True, exist_ok=True)
      filename = f"{module_name}.py"
      filepath = (dir_path / filename).absolute()
      with open(filepath, "w") as f:
        f.write(code)  # pyright: ignore[reportUnusedCallResult]
        print(f"Finish writing Python code under {filepath}")
      # Check syntax by attempting to compile the code
      _ = compile(code, "<string>", "exec")

      this_functiosns = get_all_function_names(code)
      missing_functions: list[str] = []
      if last_parser is not None:
        missing_functions = [
          func for func in last_parser_functions if func not in this_functiosns
        ]
      if missing_functions:
        shutil.rmtree(dir_path)
        return f"Error: Missing required functions: {', '.join(missing_functions)}"

      if not ensure_calling_main(code):
        shutil.rmtree(dir_path)
        return "Error: The code must include a call to main() to execute the parser. Insert 'main()' or an if __name__ == '__main__': main() block at the end of the code."
      self.created_product: bool = True
      return "Syntax Correct"
    except SyntaxError as e:
      shutil.rmtree(dir_path)  # pyright: ignore[reportPossiblyUnboundVariable]
      return f"Syntax Error: {e.msg} at line {e.lineno}, offset {e.offset}"

  def __init__(
    self,
    manual: str,
    example: str,
    rfc: str,
    chat_result_directory: str,
    max_turns: int = 15,
    config_list: list[ConfigList] = config_list,
  ):
    def make_register_function(code: str, module_name: str) -> str:
      return self._register_function(code, module_name)

    super().__init__(
      task_prompt=self.get_task_prompt(rfc),
      system_prompt=self.get_developer_prompt(manual, example),
      executor_system_message="Executor. Execute the Python code written by the Developer using the custom function _register_function. You can only execute code using the provided function!! Please ***donot infer and execute the Python code directly***!",
      is_termination_msg=GeneratePythonAgent._is_termination_msg,
      register_function=make_register_function,
      function_description="A function that takes Python code as input, and returns 'Syntax Correct' if the code is syntactically correct, otherwise returns the error message.",
      max_turns=max_turns,
      config_list=config_list,
      chat_result_directory=chat_result_directory,
      logger_step_name="GeneratePythonAgent",
    )


class MergeFormatAgent(PairLoopAgent):
  @staticmethod
  def _is_termination_msg(msg: dict[str, Any]) -> bool:  # pyright: ignore[reportExplicitAny]
    from src.tool import termination_for_3d

    return termination_for_3d(msg)

  @staticmethod
  def _register_function(code: str, module_name: str) -> tuple[str, str]:
    from src.tool import simple_parse

    return simple_parse(code, module_name)

  @staticmethod
  def get_task_prompt(format1: str, format2: str, summary1: str, summary2: str) -> str:
    from src.tool import task_prompt_merge_3d

    return task_prompt_merge_3d(format1, format2, summary1, summary2)

  @staticmethod
  def get_developer_prompt(manual: str, example: str) -> str:
    from src.tool import developer_prompt_merge_3d

    return developer_prompt_merge_3d(manual, example)

  def __init__(
    self,
    manual: str,
    example: str,
    format1: str,
    format2: str,
    summary1: str,
    summary2: str,
    chat_result_directory: str,
    max_turns: int = 15,
    config_list: list[ConfigList] = config_list,
  ):
    super().__init__(
      task_prompt=self.get_task_prompt(format1, format2, summary1, summary2),
      system_prompt=self.get_developer_prompt(manual, example),
      executor_system_message="Executor. Execute the 3d code written by the Developer using the custom function simple_parse. You can only execute code using the provided function!! Please ***donot infer and execute the 3D code directly***!",
      is_termination_msg=MergeFormatAgent._is_termination_msg,
      register_function=MergeFormatAgent._register_function,
      function_description="A function that takes 3D code as input, and returns 'EverParse succeeded!' if the code is syntactically correct, otherwise returns the error message.",
      max_turns=max_turns,
      config_list=config_list,
      chat_result_directory=chat_result_directory,
      logger_step_name="MergeFormatAgent",
    )

  @property
  def product(self) -> str:
    # find the latest created directory in data/3d_syntaxs
    self.created_product: bool = True
    if not self.created_product:
      raise RuntimeError("No product created yet")
    dir_path = Path("data/3d_syntaxs")
    if not dir_path.exists():
      raise RuntimeError("No product found")
    dirs = [d for d in dir_path.iterdir() if d.is_dir()]
    if not dirs:
      raise RuntimeError("No product found")
    latest_dir = max(dirs, key=lambda d: d.stat().st_ctime)
    # find the .3d file in the directory
    files = list(latest_dir.glob("*.3d"))
    if not files:
      raise RuntimeError("No product found")
    return files[0].absolute().as_posix()


class MergePythonAgent(PairLoopAgent):
  @staticmethod
  def _is_termination_msg(msg: dict[str, Any]) -> bool:  # pyright: ignore[reportExplicitAny]
    from src.tool import termination_for_py

    return termination_for_py(msg)

  @property
  def product(self) -> str:
    # find the latest created directory in data/python_parser
    if not self.created_product:
      raise RuntimeError("No product created yet")
    dir_path = Path("data/python_parser")
    if not dir_path.exists():
      raise RuntimeError("No product found")
    dirs = [d for d in dir_path.iterdir() if d.is_dir()]
    if not dirs:
      raise RuntimeError("No product found")
    latest_dir = max(dirs, key=lambda d: d.stat().st_ctime)
    # find the .py file in the directory
    files = list(latest_dir.glob("*.py"))
    if not files:
      raise RuntimeError("No product found")
    return files[0].as_posix()

  def _register_function(self, code: str, module_name: str) -> str:
    def get_all_function_names(code: str) -> list[str]:
      # detect all top-level function definitions, ignoring nested functions and methods
      pattern = r"^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(.*?\):"
      return re.findall(pattern, code, re.MULTILINE)

    def ensure_calling_main(code: str) -> bool:
      # check if there is a call to main() in the code
      from ast import parse, NodeVisitor, Call, Name

      @final
      class MainCallVisitor(NodeVisitor):
        def __init__(self):
          self.found = False

        @override
        def visit_Call(self, node: Call):
          if isinstance(node.func, Name) and node.func.id == "main":
            self.found = True
          self.generic_visit(node)

      tree = parse(code)
      visitor = MainCallVisitor()
      visitor.visit(tree)
      return visitor.found

    try:
      last_parser = self.product
    except RuntimeError:
      last_parser = None
    if last_parser is not None:
      with open(last_parser, "r") as f:
        last_parser_code = f.read()
      last_parser_functions = get_all_function_names(last_parser_code)
    else:
      last_parser_functions = []

    try:
      module_name = module_name.upper()
      base_directory = Path("data/python_parser")
      base_directory.mkdir(parents=True, exist_ok=True)
      dir_path = base_directory / f"{module_name}_{uuid.uuid4().hex[:6]}"
      dir_path.mkdir(parents=True, exist_ok=True)
      filename = f"{module_name}.py"
      filepath = (dir_path / filename).absolute()
      with open(filepath, "w") as f:
        f.write(code)  # pyright: ignore[reportUnusedCallResult]
        print(f"Finish writing Python code under {filepath}")
      # Check syntax by attempting to compile the code
      _ = compile(code, "<string>", "exec")

      this_functiosns = get_all_function_names(code)
      missing_functions: list[str] = []
      if last_parser is not None:
        missing_functions = [
          func for func in last_parser_functions if func not in this_functiosns
        ]
      if missing_functions:
        shutil.rmtree(dir_path)
        return f"Error: Missing required functions: {', '.join(missing_functions)}"
      if not ensure_calling_main(code):
        shutil.rmtree(dir_path)
        return "Error: The code must include a call to main() to execute the parser. Insert 'main()' or an if __name__ == '__main__': main() block at the end of the code."
      return "Syntax Correct"
    except SyntaxError as e:
      shutil.rmtree(dir_path)  # pyright: ignore[reportPossiblyUnboundVariable]
      return f"Syntax Error: {e.msg} at line {e.lineno}, offset {e.offset}"

  @staticmethod
  def get_task_prompt(format1: str, format2: str) -> str:
    from src.tool import task_prompt_merge_py

    return task_prompt_merge_py(format1, format2)

  @staticmethod
  def get_developer_prompt(manual: str, example: str) -> str:
    from src.tool import developer_prompt_merge_py

    return developer_prompt_merge_py(manual, example)

  def __init__(
    self,
    manual: str,
    example: str,
    format1: str,
    format2: str,
    chat_result_directory: str,
    max_turns: int = 15,
    config_list: list[ConfigList] = config_list,
  ):
    def make_register_function(code: str, module_name: str) -> str:
      return self._register_function(code, module_name)

    super().__init__(
      task_prompt=self.get_task_prompt(format1, format2),
      system_prompt=self.get_developer_prompt(manual, example),
      executor_system_message="Executor. Execute the Python code written by the Developer using the custom function. You can only execute code using the provided function!! Please ***donot infer and execute the Python code directly***!",
      is_termination_msg=MergePythonAgent._is_termination_msg,
      register_function=make_register_function,
      function_description="A function that takes Python code as input, and returns 'Syntax Correct' if the code is syntactically correct, otherwise returns the error message.",
      max_turns=max_turns,
      config_list=config_list,
      chat_result_directory=chat_result_directory,
      logger_step_name="MergePythonAgent",
    )


class Refine3DAgent(PairLoopAgent):
  @staticmethod
  def _is_termination_msg(msg: dict[str, Any]) -> bool:  # pyright: ignore[reportExplicitAny]
    from src.tool import termination_for_3d

    return termination_for_3d(msg)

  @staticmethod
  def _register_function(code: str, module_name: str) -> tuple[str, str]:
    from src.tool import simple_parse

    return simple_parse(code, module_name)

  @staticmethod
  def get_task_prompt(buggy_code: str, instruction: str) -> str:
    from src.tool import task_prompt_refine_3d

    return task_prompt_refine_3d(buggy_code, instruction)

  @staticmethod
  def get_developer_prompt(manual: str, example: str) -> str:
    from src.tool import developer_prompt_refine_3d

    return developer_prompt_refine_3d(manual, example)

  def __init__(
    self,
    manual: str,
    example: str,
    buggy_code: str,
    instruction: str,
    chat_result_directory: str,
    max_turns: int = 15,
    config_list: list[ConfigList] = config_list,
  ):
    super().__init__(
      task_prompt=self.get_task_prompt(buggy_code, instruction),
      system_prompt=self.get_developer_prompt(manual, example),
      executor_system_message="Executor. Execute the 3d code written by the Developer using the custom function simple_parse. You can only execute code using the provided function!! Please ***donot infer and execute the 3D code directly***!",
      is_termination_msg=Refine3DAgent._is_termination_msg,
      register_function=Refine3DAgent._register_function,
      function_description="A function that takes 3D code as input, and returns 'EverParse succeeded!' if the code is syntactically correct, otherwise returns the error message.",
      max_turns=max_turns,
      config_list=config_list,
      chat_result_directory=chat_result_directory,
      logger_step_name="Refine3DAgent",
    )

  @property
  def product(self) -> str:
    # find the latest created directory in data/3d_syntaxs
    dir_path = Path("data/3d_syntaxs")
    if not dir_path.exists():
      raise RuntimeError("No product found")
    dirs = [d for d in dir_path.iterdir() if d.is_dir()]
    if not dirs:
      raise RuntimeError("No product found")
    latest_dir = max(dirs, key=lambda d: d.stat().st_ctime)
    # find the .3d file in the directory
    files = list(latest_dir.glob("*.3d"))
    if not files:
      raise RuntimeError("No product found")
    return files[0].as_posix()


class RefinePyAgent(PairLoopAgent):
  @staticmethod
  def _is_termination_msg(msg: dict[str, Any]) -> bool:  # pyright: ignore[reportExplicitAny]
    from src.tool import termination_for_py

    return termination_for_py(msg)

  @property
  def product(self) -> str:
    # find the latest created directory in data/python_parser
    dir_path = Path("data/python_parser")
    if not dir_path.exists():
      raise RuntimeError("No product found")
    dirs = [d for d in dir_path.iterdir() if d.is_dir()]
    if not dirs:
      raise RuntimeError("No product found")
    latest_dir = max(dirs, key=lambda d: d.stat().st_ctime)
    # find the .py file in the directory
    files = list(latest_dir.glob("*.py"))
    if not files:
      raise RuntimeError("No product found")
    return files[0].as_posix()

  def _register_function(self, code: str, module_name: str) -> str:
    def get_all_function_names(code: str) -> list[str]:
      # detect all top-level function definitions, ignoring nested functions and methods
      pattern = r"^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(.*?\):"
      return re.findall(pattern, code, re.MULTILINE)

    def ensure_calling_main(code: str) -> bool:
      # check if there is a call to main() in the code
      from ast import parse, NodeVisitor, Call, Name

      @final
      class MainCallVisitor(NodeVisitor):
        def __init__(self):
          self.found = False

        @override
        def visit_Call(self, node: Call):
          if isinstance(node.func, Name) and node.func.id == "main":
            self.found = True
          self.generic_visit(node)

      tree = parse(code)
      visitor = MainCallVisitor()
      visitor.visit(tree)
      return visitor.found

    last_parser_code = self.last_parser
    last_parser_functions = get_all_function_names(last_parser_code)
    try:
      module_name = module_name.upper()
      base_directory = Path("data/python_parser")
      base_directory.mkdir(parents=True, exist_ok=True)
      dir_path = base_directory / f"{module_name}_{uuid.uuid4().hex[:6]}"
      dir_path.mkdir(parents=True, exist_ok=True)
      filename = f"{module_name}.py"
      filepath = (dir_path / filename).absolute()
      with open(filepath, "w") as f:
        f.write(code)  # pyright: ignore[reportUnusedCallResult]
        print(f"Finish writing Python code under {filepath}")
      # Check syntax by attempting to compile the code
      _ = compile(code, "<string>", "exec")

      this_functiosns = get_all_function_names(code)
      missing_functions: list[str] = []
      missing_functions = [
        func for func in last_parser_functions if func not in this_functiosns
      ]
      if missing_functions:
        shutil.rmtree(dir_path)
        return f"Error: Missing required functions: {', '.join(missing_functions)}. Remember to keep all the functions in the original code!!!!."
      if not ensure_calling_main(code):
        shutil.rmtree(dir_path)
        return "Error: The code must include a call to main() to execute the parser. Insert 'main()' or an if __name__ == '__main__': main() block at the end of the code."
      return "Syntax Correct"
    except SyntaxError as e:
      shutil.rmtree(dir_path)  # pyright: ignore[reportPossiblyUnboundVariable]
      return f"Syntax Error: {e.msg} at line {e.lineno}, offset {e.offset}"

  @staticmethod
  def get_task_prompt(buggy_code: str, instruction: str) -> str:
    from src.tool import task_prompt_refine_py

    return task_prompt_refine_py(buggy_code, instruction)

  @staticmethod
  def get_developer_prompt(manual: str, example: str) -> str:
    from src.tool import developer_prompt_refine_py

    return developer_prompt_refine_py(manual, example)

  def __init__(
    self,
    manual: str,
    example: str,
    buggy_code: str,
    instruction: str,
    chat_result_directory: str,
    max_turns: int = 15,
    config_list: list[ConfigList] = config_list,
  ):
    def make_register_function(code: str, module_name: str) -> str:
      return self._register_function(code, module_name)

    super().__init__(
      task_prompt=self.get_task_prompt(buggy_code, instruction),
      system_prompt=self.get_developer_prompt(manual, example),
      executor_system_message="Executor. Execute the Python code written by the Developer using the custom function. You can only execute code using the provided function!! Please ***donot infer and execute the Python code directly***!",
      is_termination_msg=RefinePyAgent._is_termination_msg,
      register_function=make_register_function,
      function_description="A function that takes Python code as input, and returns 'Syntax Correct' if the code is syntactically correct, otherwise returns the error message.",
      max_turns=max_turns,
      config_list=config_list,
      chat_result_directory=chat_result_directory,
      logger_step_name="RefinePyAgent",
    )

    self.last_parser: str = buggy_code
