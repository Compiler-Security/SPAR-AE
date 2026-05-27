import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, NoReturn


class _TodoPlaceholder:
  """Lazy placeholder that defers NotImplementedError until the value is actually used.

  Assignment (e.g. ``x = todo("Fill in credentials")``) is fine.  The error only
  fires when code tries to iterate, index, truth-test, or otherwise *use* the value.
  """

  def __init__(self, what: str = "") -> None:
    self._what = what

  def _raise(self) -> NoReturn:
    raise NotImplementedError(
      f"TODO: {'Implementation needed' if not self._what else self._what}"
    )

  def __bool__(self) -> bool:
    self._raise()

  def __iter__(self):
    self._raise()

  def __getitem__(self, _):
    self._raise()

  def __len__(self):
    self._raise()


def todo(what: str = "") -> _TodoPlaceholder:
  """
  A placeholder for code that needs to be implemented.
  Returns a lazy sentinel that raises NotImplementedError only when the value is
  accessed (iterated, indexed, truth-tested, etc.), not at assignment time.
  Can be inserted anywhere in the code where functionality is yet to be implemented,
  without basedpyright screaming warnings.
  """
  return _TodoPlaceholder(what)


def termination_for_3d(msg: dict[str, Any]) -> bool:  # pyright: ignore[reportExplicitAny]
  return (
    msg.get("content", "") and "EverParse succeeded!" in msg.get("content", "").rstrip()  # pyright: ignore[reportAny]
  )


def termination_for_py(msg: dict[str, Any]) -> bool:  # pyright: ignore[reportExplicitAny]
  return (
    msg.get("content", "") and "Syntax Correct" in msg.get("content", "").rstrip()  # pyright: ignore[reportAny]
  )


def simple_parse(code: str, module_name: str) -> tuple[str, str]:
  from uuid import uuid4

  print("Code: \n")
  # print with line numbers
  for i, line in enumerate(code.splitlines()):
    print(f"{i + 1:4}: {line}")
  print("\n")
  module_name = module_name.upper()
  dir_path = Path("data/3d_syntaxs")
  if not dir_path.exists():
    dir_path.mkdir(parents=True, exist_ok=True)
  dir_path = dir_path / f"{module_name}_{uuid4().hex[:6]}"
  dir_path.mkdir(parents=True, exist_ok=True)

  filename = f"{module_name}.3d"
  filepath = (dir_path / filename).absolute()
  with open(filepath, "w") as f:
    _ = f.write(code)
  where_everparse = Path("everparse/everparse.sh").absolute().as_posix()
  from tempfile import TemporaryDirectory

  cwd = Path.cwd()
  with TemporaryDirectory() as tempdir:
    os.chdir(tempdir)
    call = f"bash {where_everparse} --no_clang_format {filepath.as_posix()}"
    print("Calling everparse.....")
    print(call)
    process = subprocess.Popen(
      call, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = process.communicate()
    if stdout:
      output_dump = stdout.decode("utf-8")
    else:
      output_dump = ""
    if stderr:
      output_err = stderr.decode("utf-8")
    else:
      output_err = ""
    print("EverParse output:")
    print(output_dump)
    print("EverParse error:")
    print(output_err)
  os.chdir(cwd)

  if "EverParse succeeded" not in output_dump:
    print("Everparse unsuccess")
    if "Cannot verify u" in output_err and "subtraction" in output_err:
      output_dump = "\nThe old format has Uint substraction, e.g., use x-y without guarantee x>=y before use of x-y"
    elif "Cannot verify u" in output_err and "addition" in output_err:
      output_dump = "\nThe old format has Uint addition, e.g., use x + y wihout guarantee x + y < type bound, e.g., use x * 2 without guarantee x * 2 < type bound"
    elif "Cannot verify u" in output_err and "multiplication" in output_err:
      output_dump = "\nThe old format has Uint multiplication, e.g., use x * y without guarantee x * y < type bound"
    elif "unknown language unknown" in output_err:
      output_dump = "\nPlease regenerate and Execute code with the supplied function simple_parse only!"
    elif "Error 168" in output_dump:
      output_dump = "Syntax error, type is a reserved keyword"
    elif "Expected a byte array" in output_dump:
      pattern = r"Processing files: .*? :\((\d+),\d+\)"
      linenum = re.search(pattern, output_dump)
      if linenum:
        output_dump = f"Error: Expected a byte array at line {linenum.group(1)}"
    elif "Variable" in output_dump and "not found" in output_dump:
      pattern = r".*?\((\d+),\d+\): \(Error\) Variable (.*?) not found"
      match = re.search(pattern, output_dump)
      if match:
        line_num = match.group(1)
        variable_name = match.group(2)
      else:
        line_num = "unknown"
        variable_name = "unknown"
      if "UINT128" in variable_name:
        output_dump = f"Line {line_num}: Variable '{variable_name}' not found. EverParse does not support UINT128 type currently. Consider using multiple UINT64 fields instead."
      elif len(variable_name.split(".")) >= 2 and variable_name.split(".")[1] == "_":
        output_dump = "You should not use '_' in switch cases as it is not allowed in 3D syntax. 3D switch cases does not need default case, please remove the default case."
      else:
        output_dump = f"Line {line_num}: Variable '{variable_name}' not found. If you are adding or modifying constraints, you SHOULD add them to later lines, so that the variable is defined before use. You MUST NOT swap the order of definitions."
      # we want to add line numbers to the code and report back to LLM, so that it locates the error line easier

    # else:
    #     output_dump = "ERROR, try again and Execute code with the supplied function simple_parse only: " + output_dump
    # output_dump += "\nPlease regenerate!DO NOT use 'type' as an identifier! Do NOT use 'struct.field' , consider expand the struct fields with the current struct! casetype syntax should be as follows: casetype _NAME (Type variable_name) {{ switch(variable_name){{ ...}} }} NAME; Type variable_name should not be defined inside the casetype, e.g., {{..Type variable_name; _NAME(variable_name);...}}, Do not add default type in casetype!!"
    shutil.rmtree(dir_path)
  else:
    from src.fsm import FSMBuilder
    from src.parse3d import Parse3D

    try:
      parser = Parse3D(code)
      module = parser.parse()
      fsm_map = FSMBuilder().build(module, parser.context)
      if module.entrypoint is None or module.entrypoint not in fsm_map:
        output_dump = "\nError: No entrypoint found! Please ensure only one entrypoint! Entry point should be the main packet structure!"
        shutil.rmtree(dir_path)
        return output_err, output_dump
      entry_fsm = fsm_map.get(module.entrypoint)
      if entry_fsm is None:
        output_dump = "\nError: No entrypoint found! Please ensure only one entrypoint! Entry point should be the main packet structure!"
        shutil.rmtree(dir_path)
        return output_err, output_dump
      paths = entry_fsm.save_all_paths()
      for path in paths:
        # if the bit size is wrong, accessing bit_size_map will raise ValueError
        try:
          from src.encode import Encoder

          _ = Encoder(path, path_conditions={}, context=parser.context)  # pyright: ignore[reportArgumentType]
        except ValueError as e:
          if "bit size must be byte-aligned" in str(
            e
          ) or "Non-byte-aligned bit size expr" in str(e):
            name = str(e)["bit size must be byte-aligned: ".__len__() :]
            if not name:
              output_dump = "\nError: The format defined a packet with size not divisible by 8, please check that bitfields are divisible by 8!"
            else:
              output_dump = f"\nError: The field '{name}' is defined with bit size not divisible by 8, please check that bitfields are divisible by 8!"
          else:
            output_dump = f"\nError: {str(e)}"
          shutil.rmtree(dir_path)
          return output_err, output_dump
    except ValueError as e:
      output_dump = f"\nError: {str(e)}"
      shutil.rmtree(dir_path)
      return output_err, output_dump
    output_dump += "\nEverParse succeeded!\n"

  return output_err, output_dump
