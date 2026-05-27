from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import override
from collections.abc import Iterator


class TestResultType(Enum):
  CORRECT_PASS_INCORRECT_FAIL = 1
  CORRECT_PASS_INCORRECT_PASS = 2
  CORRECT_FAIL = 3
  CORRECT_PASS = 4
  SKIP = 5
  CORRECT_ENCODE_FAIL = 6


@dataclass
class TestResultDetail:
  parser_output: str
  related_format: str
  related_parser: str
  related_section: str
  related_section_number: list[str]
  negated_path_conditions: tuple[str, ...] | None
  input_path: str

  def __iter__(self) -> Iterator[str | list[str] | tuple[str, ...] | None]:
    return iter(
      (
        self.parser_output,
        self.related_format,
        self.related_parser,
        self.related_section,
        self.related_section_number,
        self.negated_path_conditions,
        self.input_path,
      )
    )


dummy_detail = TestResultDetail("", "", "", "", [], (), "")


class TestResult:
  def __init__(self, result_type: TestResultType, details: TestResultDetail):
    self.result_type: TestResultType = result_type
    self.details: TestResultDetail = details

  def __iter__(self) -> Iterator[TestResultType | TestResultDetail]:
    return iter((self.result_type, self.details))

  @override
  def __str__(self):
    # do pretty print
    result = ""
    result += f"TestResultType: {self.result_type.name}\n"
    result += "Details:\n"
    for name, value in zip(TestResultDetail.__annotations__.keys(), self.details):  # pyright: ignore[reportAssignmentType]
      if name == "related_section":
        value: str = value.replace("\n", "\n        ")
      result += f"{name}: {value}\n"
    return result

  @override
  def __repr__(self):
    return self.__str__()

  @override
  def __hash__(self) -> int:
    return hash(self.details.negated_path_conditions)
