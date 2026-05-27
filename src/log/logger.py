from __future__ import annotations
from abc import ABC, abstractmethod
import logging
from contextlib import contextmanager
import contextvars
from typing import override
from rich.logging import RichHandler
from rich.text import Text
from rich.console import Console
import inspect

# --- Setup global logger ---
console = Console()
logging.basicConfig(
  level=logging.INFO,
  format="%(message)s",
  datefmt="[%X]",
  handlers=[RichHandler(console=console, show_time=True, show_path=True)],
)
logger = logging.getLogger("rLLoger")

# --- Global context for nesting ---
_current_path = contextvars.ContextVar("current_path", default=[])


class NoMarkupFormatter(logging.Formatter):
  """Formatter that removes Rich/ANSI markup tags for plain file logs."""

  @override
  def format(self, record: logging.LogRecord) -> str:
    import re

    # regex to strip Rich markup like [bold red]...[/bold red]
    RICH_TAG_RE = re.compile(r"\[/?[a-zA-Z0-9 #=_-]+\]")
    message = super().format(record)
    return RICH_TAG_RE.sub("", message)


def add_file_handler(log_file_path: str):
  """Adds a file handler to the global logger."""
  file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
  file_handler.setLevel(logging.INFO)
  formatter = NoMarkupFormatter(
    "[%(asctime)s] [%(levelname)s] %(filename)s:%(lineno)d in %(funcName)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
  )
  file_handler.setFormatter(formatter)
  logger.addHandler(file_handler)


def _infer_stacklevel(skip_modules=("logger",)):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
  """
  Automatically infer how far up the stack we should report the call from.
  Skips frames that belong to internal logging utilities.
  """
  frame = inspect.currentframe()
  level = 1  # logger.log itself = 1
  while frame:
    frame = frame.f_back
    if frame is None:
      break
    module_name = frame.f_globals.get("__name__", "")  # pyright: ignore[reportAny]
    if not any(module_name.endswith(m) for m in skip_modules):  # pyright: ignore[reportAny, reportUnknownVariableType]
      break
    level += 1
  return level


def step_log(
  message: str,
  level: int = logging.INFO,
  style: str = "bold cyan",
  added_stacklevel: int = 0,
):
  """Logs a message with the current path as prefix."""
  extra = {
    "markup": True,
    "style": style,
  }
  stacklevel = _infer_stacklevel()
  prefix = " [bold][yellow]>[/yellow][/bold] ".join(_current_path.get())
  logger.log(
    level,
    Text(f"[{prefix}] {message}"),
    extra=extra,
    stacklevel=stacklevel + added_stacklevel,
  )


# --- Setup context manager for logging paths ---
@contextmanager
def log_scope(name: str, style: str = "bold cyan"):
  """Logs hierarchical step begin/finish."""
  import time

  path = _current_path.get() + [name]
  _ = _current_path.set(path)
  start = time.time()
  step_log("started", style=style, added_stacklevel=3)
  try:
    yield
    duration = time.time() - start
    step_log(f"finished (took {duration:.2f}s)", style=style, added_stacklevel=3)
  except Exception:
    step_log("failed", style=style, level=logging.ERROR, added_stacklevel=3)
    raise
  finally:
    _ = _current_path.set(_current_path.get()[:-1])


# --- Base class for all components ---
class StepLogger(ABC):
  def __init__(self, name: str, mute: bool = False):
    self.name: str = name
    self.mute: bool = mute

  @contextmanager
  def step(self, name: str):
    """Logs hierarchical step begin/finish."""
    if self.mute:
      yield
      return
    with log_scope(f"{name}"):
      yield

  def log(self, message: str, level: int = logging.INFO):
    """Logs a message with the current path as prefix."""
    if not self.mute:
      step_log(f"{message}", level=level)

  def log_error(self, message: str):
    """Logs an error message."""
    self.log(message, level=logging.ERROR)

  def log_warning(self, message: str):
    """Logs a warning message."""
    self.log(message, level=logging.WARNING)

  def log_info(self, message: str):
    """Logs an info message."""
    self.log(message, level=logging.INFO)

  def log_debug(self, message: str):
    """Logs a debug message."""
    self.log(message, level=logging.DEBUG)

  @property
  def current_path(self) -> list[str]:
    return _current_path.get()

  @abstractmethod
  def run(self) -> None:
    raise NotImplementedError("Subclasses must implement the run method.")
