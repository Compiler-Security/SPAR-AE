from pathlib import Path
import re
import shutil
import time
from typing import Any, final, override
import uuid
from src.log import StepLogger
from src.agent import PairLoopAgent
from src.secret import config_list
from tap import tapify


class Generate3DAgentWORFC(PairLoopAgent):
  @staticmethod
  def _is_termination_msg(msg: dict[str, Any]) -> bool:  # pyright: ignore[reportExplicitAny]
    from src.tool import termination_for_3d

    return termination_for_3d(msg)

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

  @staticmethod
  def get_task_prompt(protocol_name: str) -> str:
    from src.tool.prompts import task_prompt_generate_3d_wo_rfc

    return task_prompt_generate_3d_wo_rfc(protocol_name)

  @staticmethod
  def get_developer_prompt(manual_3d: str) -> str:
    from src.tool.prompts import developer_prompt_generate_3d_wo_rfc

    return developer_prompt_generate_3d_wo_rfc(manual_3d)

  @staticmethod
  def _register_function(code: str, module_name: str) -> tuple[str, str]:
    from src.tool import simple_parse

    return simple_parse(code, module_name)

  def __init__(
    self,
    protocol_name: str,
    manual: str,
    chat_result_directory: str,
    max_turns: int = 10,
  ):
    super().__init__(
      system_prompt=self.get_developer_prompt(manual),
      task_prompt=self.get_task_prompt(protocol_name),
      executor_system_message="Executor. Execute the 3d code written by the Developer using the custom function simple_parse. You can only execute code using the provided function!! Please ***donot infer and execute the 3D code directly***!",
      is_termination_msg=self._is_termination_msg,
      register_function=self._register_function,
      function_description="A function that takes 3D code as input, and returns 'EverParse succeeded!' if the code is syntactically correct, otherwise returns the error message.",
      max_turns=max_turns,
      chat_result_directory=chat_result_directory,
      config_list=config_list,
      logger_step_name="Generate3DAgentWORFC",
    )


class GeneratePyAgentWORFC(PairLoopAgent):
  @staticmethod
  def _is_termination_msg(msg: dict[str, Any]) -> bool:  # pyright: ignore[reportExplicitAny]
    from src.tool import termination_for_py

    return termination_for_py(msg)

  @staticmethod
  def get_task_prompt(protocol_name: str) -> str:
    from src.tool.prompts import task_prompt_generate_py_wo_rfc

    return task_prompt_generate_py_wo_rfc(protocol_name)

  @staticmethod
  def get_developer_prompt(manual_py: str) -> str:
    from src.tool.prompts import developer_prompt_generate_py_wo_rfc

    return developer_prompt_generate_py_wo_rfc(manual_py)

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

  def _register_function(self, code: str, module_name: str, **kwargs: Any) -> str:
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
    protocol_name: str,
    manual: str,
    chat_result_directory: str,
    max_turns: int = 10,
  ):
    def make_register_function(code: str, module_name: str) -> str:
      return self._register_function(code, module_name)

    super().__init__(
      system_prompt=self.get_developer_prompt(manual),
      task_prompt=self.get_task_prompt(protocol_name),
      executor_system_message="Executor. Execute the Python code written by the Developer using the custom function _register_function. You can only execute code using the provided function!! Please ***donot infer and execute the Python code directly***!",
      is_termination_msg=self._is_termination_msg,
      register_function=make_register_function,
      function_description="A function that takes Python code as input, and returns 'Syntax Correct' if the code is syntactically correct, otherwise returns the error message.",
      max_turns=max_turns,
      chat_result_directory=chat_result_directory,
      config_list=config_list,
      logger_step_name="GeneratePyAgentWORFC",
    )


class DriverWORFC(StepLogger):
  def __init__(
    self,
    protocol_name: str,
    data_dir: str,
  ):
    super().__init__(name="DriverWORFC")
    self.protocol_name: str = protocol_name
    self.data_dir: str = data_dir
    self.manual_3d_path: Path = Path(data_dir) / "DSL" / "3d_syntax_check.txt"
    self.manual_py_path: Path = Path(data_dir) / "DSL" / "python_coding_style.txt"
    with open(self.manual_3d_path, "r") as f:
      self.manual_3d: str = f.read()
    with open(self.manual_py_path, "r") as f:
      self.manual_py: str = f.read()
    self.format_path: str = ""
    self.parser_path: str = ""
    self.format_code: str = ""
    self.parser_code: str = ""
    self.result_dir: Path = Path(self.data_dir) / "ablation" / "without_rfc"
    self.protocol_dir: Path = self.result_dir / (
      self.protocol_name + f"_{uuid.uuid4().hex[:6]}"
    )
    self.result_dir.mkdir(parents=True, exist_ok=True)
    self.protocol_dir.mkdir(parents=True, exist_ok=True)

  @property
  def prompt_generate_3d_system(self) -> str:
    from src.tool.prompts import task_prompt_generate_3d_wo_rfc

    return task_prompt_generate_3d_wo_rfc(self.manual_3d)

  @property
  def prompt_generate_py_system(self) -> str:
    from src.tool.prompts import task_prompt_generate_py_wo_rfc

    return task_prompt_generate_py_wo_rfc(self.manual_py)

  @property
  def prompt_generate_3d_developer(self) -> str:
    from src.tool.prompts import developer_prompt_generate_3d_wo_rfc

    return developer_prompt_generate_3d_wo_rfc(self.protocol_name)

  @property
  def prompt_generate_py_developer(self) -> str:
    from src.tool.prompts import developer_prompt_generate_py_wo_rfc

    return developer_prompt_generate_py_wo_rfc(self.protocol_name)

  @override
  def run(self):
    self.log("Starting Driver without RFC text...")
    # Step 1: Generate 3D code
    gen3d = Generate3DAgentWORFC(
      protocol_name=self.protocol_name,
      manual=self.manual_3d,
      chat_result_directory=self.data_dir,
    )
    request_success = False
    retry_cnt = 5
    while not request_success and retry_cnt > 0:
      retry_cnt -= 1
      try:
        gen3d.start()
        request_success = gen3d.is_successful()
      except Exception as e:
        self.log_error(f"Error: {e}")
        import inspect

        self.log_info(f"Traceback: {inspect.trace()}")
        self.log_info("Retrying.....")
        time.sleep(5)
        continue
    self.format_path = gen3d.product
    with open(self.format_path, "r") as f:
      self.format_code = f.read()
    self.log("3D code generation completed.")

    # Step 2: Generate Python parser code
    genpy = GeneratePyAgentWORFC(
      protocol_name=self.protocol_name,
      manual=self.manual_py,
      chat_result_directory=self.data_dir,
    )
    request_success = False
    while not request_success:
      try:
        genpy.start()
        request_success = genpy.is_successful()
      except Exception as e:
        self.log_error(f"Error: {e}")
        import inspect

        self.log_info(f"Traceback: {inspect.trace()}")
        self.log_info("Retrying.....")
        time.sleep(5)
        continue
      self.parser_path = genpy.product
      with open(self.parser_path, "r") as f:
        self.parser_code = f.read()
    self.log("Python parser code generation completed.")
    self.log("Driver without RFC text completed.")

    self.save_results()

  def save_results(self):
    format_path = self.protocol_dir / Path(self.format_path).name
    parser_path = self.protocol_dir / Path(self.parser_path).name
    _ = shutil.copy(self.format_path, format_path)
    _ = shutil.copy(self.parser_path, parser_path)
    self.log(f"Saved 3D code to {format_path}")
    self.log(f"Saved Python parser code to {parser_path}")


def main():
  tapify(DriverWORFC).run()


if __name__ == "__main__":
  main()
