from __future__ import annotations
from collections.abc import Generator
import time
from typing import TYPE_CHECKING, final, override
from src.encode import EncoderError
from src.encode.path_mutate import PathMutator
from src.log import StepLogger
from src.tool.tool import todo

if TYPE_CHECKING:
  from src.parse3d.ast import Module
  from src.parse3d.ctx import ParserContext
  from src.parse3d.collect_path_condition import PathCondition
  from src.fsm import Path


@final
class PathTestcaseGenerator(StepLogger):
  def __init__(
    self,
    path: "Path",
    module: "Module",
    ctx: "ParserContext",
    path_condition: "dict[str, dict[str, PathCondition]]",
    correct_case_count: int = 1,
    mute: bool = False,
    disable_opt_ii: bool = False,
  ) -> None:
    super().__init__("Testcase Generator", mute)
    self.mute = mute
    self.path = path
    self.module = module
    self.ctx = ctx
    self.path_condition = path_condition
    self.corect_case_count = correct_case_count
    self.incorrect_case_count = correct_case_count
    self.disable_opt_ii = disable_opt_ii
    # make cache for correct case and incorrect cases
    self._correct_cases: list[bytes] | None = None
    self._correct_case_table: list[dict[str, int]] | None = None
    self._incorrect_cases: dict[Path, dict[PathCondition, list[bytes]]] | None = None
    self._incorrect_case_table: dict[PathCondition, list[dict[str, int]]] | None = None
    self._original_path_condition: dict[PathCondition, PathCondition] | None = None
    self.mutated_paths: dict[PathCondition, list[Path]] | None = None
    self.smt_time_cost: float = 0.0

  @override
  def run(self):
    pass  # dummy implementation

  @property
  def original_path_condition(self) -> dict[PathCondition, PathCondition]:
    if self._original_path_condition is not None:
      return self._original_path_condition
    raise ValueError("original_path_condition is not generated yet")

  @property
  def correct_cases(self) -> Generator[bytes, None, None]:
    if self._correct_cases is not None:
      yield from self._correct_cases
    else:
      yield from self.get_correct_cases()

  @property
  def correct_case_table(self) -> list[dict[str, int]]:
    if self._correct_case_table is not None:
      return self._correct_case_table
    else:
      for case in self.get_correct_cases():
        pass  # to trigger correct case generation
      if self._correct_case_table is not None:
        return self._correct_case_table
      else:
        raise ValueError("correct_case_table is not generated yet")

  @property
  def incorrect_cases(self) -> dict[Path, dict[PathCondition, list[bytes]]]:
    if self._incorrect_cases is None:
      self._incorrect_cases = self.get_all_incorrect_cases()
    return self._incorrect_cases

  @correct_cases.setter
  def correct_cases(self, _value: list[bytes]) -> None:  # pyright: ignore[reportPropertyTypeMismatch]
    raise AttributeError("correct_case is read-only")

  @incorrect_cases.setter
  def incorrect_cases(
    self, _value: dict[Path, dict[PathCondition, list[bytes]]]
  ) -> None:
    raise AttributeError("incorrect_cases is read-only")

  def get_correct_cases(self) -> Generator[bytes, None, None]:
    with self.step("Correct Case Generation"):
      self.log_info(f"Generating {self.corect_case_count} correct cases...")
      if self._correct_cases is not None:
        yield from self._correct_cases
        return
      self._correct_cases = []
      from src.encode import Encoder

      encoder = Encoder(
        self.path,
        self.path_condition,
        self.ctx,
        count=self.corect_case_count,
        mute=self.mute,
      )
      # want to update self._correct_cases as well
      time_start = time.time()
      cases_generator = encoder.encode()
      while True:
        try:
          case = next(cases_generator)
          yield case
          self._correct_cases.append(case)
        except StopIteration:
          break
        except EncoderError as e:
          self.log_error(f"EncoderError during correct case generation: {e}")
          break
      self._correct_case_table = encoder.get_case_table()
      time_end = time.time()
      self.smt_time_cost += time_end - time_start
      if len(self._correct_cases) != len(self._correct_case_table):
        raise ValueError(
          f"Generated correct cases does not match with correct case table, encoded: {len(self._correct_cases)}, unique: {len(self._correct_case_table)}"
        )
      # encoded = encoder.encode()
      # self._correct_cases = encoded
      # self._correct_case_table = encoder.get_case_table()
      # if len(encoded) != len(self._correct_case_table):
      #   raise ValueError(
      #     f"Generated correct cases does not match with correct case table, encoded: {len(encoded)}, unique: {len(self._correct_case_table)}"
      #   )
      # return encoded

  @property
  def incorrect_case_table(self) -> dict[PathCondition, list[dict[str, int]]]:
    if self._incorrect_case_table is not None:
      return self._incorrect_case_table
    else:
      raise ValueError("incorrect_case_table is not generated yet")

  def get_mutated_paths(
    self,
  ) -> Generator[tuple[PathCondition, list[Path]], None, None]:
    if self.mutated_paths is not None:
      for pc, paths in self.mutated_paths.items():
        yield pc, paths
      return

    mutated_paths = PathMutator(
      self.path, self.module, self.ctx, self.path_condition, exhaustive=self.disable_opt_ii
    ).mutate()
    self.mutated_paths = {}
    for pc, paths in mutated_paths:
      self.mutated_paths.setdefault(pc, []).extend(paths)
      yield pc, paths

  def all_mutated_paths_and_condition(
    self,
  ) -> Generator[tuple[Path, list[PathCondition]], None, None]:
    if self.mutated_paths is not None:
      paths_and_conditions: dict[Path, list[PathCondition]] = {}
      for pc, paths in self.mutated_paths.items():
        for path in paths:
          paths_and_conditions.setdefault(path, []).append(pc)
      for path, pcs in paths_and_conditions.items():
        yield path, pcs
      return
    else:
      mutated_paths = self.get_mutated_paths()
      paths_and_conditions = {}
      for pc, paths in mutated_paths:
        for path in paths:
          paths_and_conditions.setdefault(path, []).append(pc)
      for path, pcs in paths_and_conditions.items():
        yield path, pcs

  def cases_for_incorrect_path_and_condition(
    self, path: Path, condition: PathCondition
  ) -> Generator[bytes, None, None]:
    if (
      self._incorrect_cases is None
      or path not in self._incorrect_cases
      or condition not in self._incorrect_cases[path]
    ):
      self._incorrect_cases = {}
      self._incorrect_cases[path] = {}
      self._incorrect_cases[path][condition] = []
      from src.encode import Encoder

      encoder = Encoder(
        path,
        self.path_condition,
        self.ctx,
        count=self.incorrect_case_count,
        target_mutate_var=condition.variable.name,
        mute=self.mute,
      )
      for case in encoder.encode():
        self._incorrect_cases[path][condition].append(case)
        if self._incorrect_case_table is None:
          self._incorrect_case_table = {}
        if condition not in self._incorrect_case_table:
          self._incorrect_case_table[condition] = []
        self._incorrect_case_table[condition].append(encoder.get_case_table()[-1])
        yield case
      self.smt_time_cost += encoder.smt_time_cost
    elif condition not in self._incorrect_cases[path]:
      self._incorrect_cases[path][condition] = []
      from src.encode import Encoder

      encoder = Encoder(
        path,
        self.path_condition,
        self.ctx,
        count=self.incorrect_case_count,
        target_mutate_var=condition.variable.name,
      )
      for case in encoder.encode():
        self._incorrect_cases[path][condition].append(case)
        # update self._incorrect_case_table as well
        if self._incorrect_case_table is None:
          self._incorrect_case_table = {}
        if condition not in self._incorrect_case_table:
          self._incorrect_case_table[condition] = []
        self._incorrect_case_table[condition].append(encoder.get_case_table()[-1])
        yield case
      self.smt_time_cost += encoder.smt_time_cost
    else:
      for case in self._incorrect_cases[path][condition]:
        yield case

  def get_all_incorrect_cases(
    self,
  ) -> dict[Path, dict[PathCondition, list[bytes]]]:
    if self._incorrect_cases is not None:
      return self._incorrect_cases
    from src.encode.path_mutate import PathMutator

    mutated_paths = PathMutator(
      self.path, self.module, self.ctx, self.path_condition, mute=self.mute, exhaustive=self.disable_opt_ii
    ).mutate()
    from src.encode import Encoder, EncoderError

    incorrect_cases: dict[Path, dict[PathCondition, list[bytes]]] = {}
    self._incorrect_case_table = {}
    for path_condition, mutated_path_list in mutated_paths:
      # incorrect_cases[path_condition] = {}
      # self.log_info(
      #   f"Generating incorrect case for mutated path condition: {path_condition}"
      # )
      for mutated_path in mutated_path_list:
        incorrect_cases[mutated_path] = {}
        try:
          encoder = Encoder(
            mutated_path,
            self.path_condition,
            self.ctx,
            count=self.incorrect_case_count,
            target_mutate_var=path_condition.variable.name,
            mute=self.mute,
          )
          incorrect_cases[mutated_path][path_condition] = []
          for case in encoder.encode():
            incorrect_cases[mutated_path][path_condition].append(case)
          self.smt_time_cost += encoder.smt_time_cost
          self._incorrect_case_table[path_condition] = encoder.get_case_table()
        except EncoderError:
          continue
    self._incorrect_cases = incorrect_cases
    return self._incorrect_cases
