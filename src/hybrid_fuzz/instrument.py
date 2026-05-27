import ast
from dataclasses import dataclass
import os
from types import ModuleType
from typing import IO, Any, Callable, TypedDict, final, override
import z3

from src.hybrid_fuzz.mock import MockDict, MockFile, MockInt, MockRange, MockSet, MockStruct, symbolic_join
from src.hybrid_fuzz.concolic import (
  ConcolicList,
  ExecutionContext,
  PathEvent,
  PathEventDict,
)
import contextlib
import io


class InstrumentationError(Exception):
  pass


class InstrumentationTimeoutError(InstrumentationError):
  pass


class InstrumentationResultDict(TypedDict):
  exit_code: int
  constraints: list[PathEventDict]
  input_data: bytes
  stdout: str
  stderr: str


class JoinRewriter(ast.NodeTransformer):
  """
  Automatically converts b'...'.join(x) into symbolic_join(b'...', x)
  before the code is compiled.
  """
  @override
  def visit_Call(self, node):
    # Check if the call is: <Bytes Literal>.join(...)
    if (
      isinstance(node.func, ast.Attribute)
      and isinstance(node.func.value, ast.Constant)
      and isinstance(node.func.value.value, bytes)
      and node.func.attr == "join"
    ):
      # Found it! Swap it with symbolic_join(...)
      new_node = ast.Call(
        func=ast.Name(id="symbolic_join", ctx=ast.Load()),
        args=[node.func.value, *node.args],
        keywords=node.keywords,
      )
      return ast.copy_location(new_node, node)

    return self.generic_visit(node)


@dataclass
class InstrumentationResult:
  exit_code: int
  constraints: list[PathEvent]
  input_data: ConcolicList
  stdout: str = ""
  stderr: str = ""

  def as_dict(self) -> InstrumentationResultDict:
    return {
      "exit_code": self.exit_code,
      "constraints": [c.as_dict() for c in self.constraints],
      "input_data": self.input_data.as_bytes(),
      "stdout": self.stdout,
      "stderr": self.stderr,
    }

  @classmethod
  def from_dict(cls, data: InstrumentationResultDict) -> "InstrumentationResult":
    return cls(
      exit_code=data["exit_code"],
      constraints=[PathEvent.from_dict(c) for c in data["constraints"]],
      input_data=ConcolicList.from_bytes(data["input_data"]),
      stdout=data["stdout"],
      stderr=data["stderr"],
    )

  def gen_new_input(self, event: PathEvent) -> bytes:
    """Generate a new input that flips the given path event's constraint."""
    solver = z3.Solver()
    for c in self.constraints:
      if c == event:
        # Negate the constraint to flip the path
        solver.add(z3.Not(c.constraint))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
      else:
        solver.add(c.constraint)  # pyright: ignore[reportUnknownMemberType]
    if solver.check() == z3.sat:  # pyright: ignore[reportAny, reportUnknownMemberType]
      model = solver.model()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
      # Reconstruct input bytes from the model
      input_bytes = bytearray()
      for i in range(len(self.input_data)):
        byte_var = z3.BitVec(f"byte_{i}", 8)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if model.eval(byte_var, model_completion=True) is not None:  # pyright: ignore[reportUnknownMemberType]
          input_bytes.append(model.eval(byte_var, model_completion=True).as_long())  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        else:
          input_bytes.append(0)  # Default to 0 if not in model
      return bytes(input_bytes)
    else:
      raise InstrumentationError("Could not solve for new input.")


@final
class Instrumentator:
  def __init__(self, source_code: str, filename: str = "<parser>"):
    self.source_code = source_code
    self.filename = filename
    # Preprocess source code to rewrite .join calls
    parsed_ast = ast.parse(source_code, filename=filename)
    rewriter = JoinRewriter()
    rewritten_ast = rewriter.visit(parsed_ast)  # pyright: ignore[reportAny]
    ast.fix_missing_locations(rewritten_ast)  # pyright: ignore[reportAny]
    self.source_code = ast.unparse(rewritten_ast)  # pyright: ignore[reportAny]

  def run(self, input_data: bytes) -> InstrumentationResult:
    concolic_input = ConcolicList.from_bytes(input_data)
    input_file_path_name = "fuzz_input_pkt.bin"
    compiled_object = compile(self.source_code, self.filename, "exec")

    def mock_open(
      file,
      mode="rb",
      buffering=-1,
      encoding=None,
      errors=None,
      newline=None,
      closefd=True,
      opener=None,
    ):
      # Only intercept the specific input file in binary mode
      if file == input_file_path_name and "b" in mode:
        return MockFile(concolic_input)
      # Pass everything else to real open
      return open(file, mode, buffering, encoding, errors, newline, closefd, opener)

# --- NEW: Define the os.path mocks ---
        # We need to capture the REAL functions first so we can use them as fallback
    real_exists = os.path.exists
    real_isfile = os.path.isfile

    def mock_exists(path):
        # If the parser asks about our fake file, say "YES, it exists!"
        if path == input_file_path_name:
            return True
        # For libraries checking imports/configs, tell the truth
        return real_exists(path)

    def mock_isfile(path):
        if path == input_file_path_name:
            return True
        return real_isfile(path)

    # Patch os.path functions in the symbolic environment
    

    # A. Setup the Symbolic Environment
    symbolic_env: dict[
      str,
      type[ConcolicList]
      | type[ExecutionContext]
      | ModuleType
      | type[MockInt]
      | Callable[..., MockFile | IO[Any]]  # pyright: ignore[reportExplicitAny]
      | Any  # pyright: ignore[reportExplicitAny]
      | str,
    ] = {
      "int": MockInt,  # Override int with MockInt
      "dict": MockDict,  # Override dict with MockDict
      "set": MockSet,  # Override set with MockSet
      "range": MockRange,  # Override range with MockRange
      "struct": MockStruct,  # Override struct with MockStruct
      "open": mock_open,  # Override open to return MockFile for our input
      "symbolic_join": symbolic_join,  # Our symbolic join function
      "__builtins__": __builtins__,  # Safety: give access to print, len, etc.
      "__name__": "__main__",  # So that if parser checks __name__, it works
    }

    # B. Monkey-patch sys.argv as parser uses command-line args
    import sys

    original_argv = sys.argv
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    try:
      sys.argv = [self.filename, input_file_path_name]
      os.path.exists = mock_exists
      os.path.isfile = mock_isfile
      # C. Execute the Parser Code
      # C.a Reset Execution Context
      ExecutionContext.reset()
      # C.b Execute
      # redirect stdout/stderr to capture parser output
      with (
        contextlib.redirect_stdout(stdout_buf),
        contextlib.redirect_stderr(stderr_buf),
      ):
        exec(compiled_object, symbolic_env)
    except SystemExit as sys_exit:
      # we identify the return code via SystemExit exception
      return InstrumentationResult(
        exit_code=sys_exit.code if isinstance(sys_exit.code, int) else -1,
        constraints=ExecutionContext.path_constraints[:],
        input_data=concolic_input,
        stdout=stdout_buf.getvalue(),
        stderr=stderr_buf.getvalue(),
      )
    except Exception as e:
      print(f"[!] Exception during parser execution: {e}")
      return InstrumentationResult(
        exit_code=-114514,
        constraints=ExecutionContext.path_constraints[:],
        input_data=concolic_input,
        stdout=stdout_buf.getvalue(),
        stderr=stderr_buf.getvalue(),
      )
    finally:
      sys.argv = original_argv
      os.path.exists = real_exists
      os.path.isfile = real_isfile
    # If parser finishes without SystemExit, we consider it a normal exit
    return InstrumentationResult(
      exit_code=0,
      constraints=ExecutionContext.path_constraints[:],
      input_data=concolic_input,
      stdout=stdout_buf.getvalue(),
      stderr=stderr_buf.getvalue(),
    )
