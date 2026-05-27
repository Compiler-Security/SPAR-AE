from typing import Any, Callable, TypeVar, NoReturn
import functools
import pdbp  # noqa: F401  # pyright: ignore[reportUnusedImport]
import pdb

F = TypeVar("F", bound=Callable[..., Any])  # pyright: ignore[reportExplicitAny]
NoReturnF = TypeVar("NoReturnF", bound=Callable[..., NoReturn])


def debug_decorator_factory(debug: bool) -> Callable[[F], F | NoReturnF]:
  """
  A factory function that returns a decorator based on the debug flag.
  If debug is True, it returns the debug_on_exception decorator.
  If debug is False, it returns the not_debug_on_exception decorator.
  """
  if debug:
    return debug_on_exception  # pyright: ignore[reportReturnType]
  else:
    return not_debug_on_exception


def not_debug_on_exception(func: F) -> F:
  def wrapper(*args, **kwargs) -> Any:  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType, reportAny, reportExplicitAny]
    return func(*args, **kwargs)  # pyright: ignore[reportAny]

  return wrapper  # pyright: ignore[reportReturnType, reportUnknownVariableType]


def debug_on_exception(func: F) -> F | NoReturnF:
  """
  A decorator that drops into pdb post-mortem if an exception occurs in the decorated function.
  """

  @functools.wraps(func)
  def wrapper(*args, **kwargs) -> Any:  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType, reportAny, reportExplicitAny]
    try:
      # Call the original function
      return func(*args, **kwargs)  # pyright: ignore[reportAny]
    except Exception as e:
      print(f"--- Exception in {func.__name__} ---")
      print(f"Exception Type: {type(e).__name__}")
      print(f"Exception Message: {e}")
      # Enter post-mortem debugging
      pdb.post_mortem()
      # exit after debugging
      raise e

  return wrapper  # pyright: ignore[reportReturnType, reportUnknownVariableType]
