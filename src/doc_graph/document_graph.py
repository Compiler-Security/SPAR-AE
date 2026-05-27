from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
import datetime
from functools import reduce
from logging import warning
from pathlib import Path
from src.secret import config_list
from src.secret.secret import ConfigList
import time
import trace
from typing import (
  TYPE_CHECKING,
  Any,
  NamedTuple,
  TypeGuard,
  TypedDict,
  final,
  override,
)
from typing_extensions import deprecated
import json
from src.log import StepLogger
from src.tool import todo

if TYPE_CHECKING:
  ...

# ----------- Definition of Merger and its implementations ----------- #


class Merger(ABC):
  @abstractmethod
  def merge(self, a: SectionNode, b: SectionNode) -> SectionNode:
    raise NotImplementedError("Merger is an abstract class")


class ViewMerger(Merger, StepLogger):
  # a dummy merger that just keeps the first section. The DocumentGraph.bottom_up will do nothing in this case, if implemented correctly.

  def __init__(self) -> None:
    super().__init__("ViewMerger")

  @override
  def run(self) -> None:
    pass  # dummy implementation

  @override
  def merge(self, a: SectionNode, b: SectionNode) -> SectionNode:
    self.log_info(f"Merging section {a.number} with {b.number}")
    return a  # reduce is a -> b, by keeping a we keep the top section


class ContentMerger(Merger, StepLogger):
  def __init__(self) -> None:
    super().__init__("ContentMerger")

  @override
  def run(self) -> None:
    pass  # dummy implementation

  @override
  def merge(self, a: SectionNode, b: SectionNode) -> SectionNode:
    self.log_info(f"Merging section {a.number} with {b.number}")
    # merge content and summaries
    merged_content = (
      a.content + "\n" + b.content
      if a.content and b.content
      else a.content or b.content
    )
    merged_summary = (
      a.summary + " " + b.summary if a.summary and b.summary else a.summary or b.summary
    )
    self.log_info(f"Merged content:\n  {merged_content[:]}")
    self.log_info(f"Merged summary:\n  {merged_summary}")
    return SectionNode(
      number=a.number,
      title=a.title,
      content=merged_content,
      summary=merged_summary,
      format_path=a.format_path or b.format_path,
      parser_path=a.parser_path or b.parser_path,
    )


class FormatMerger(Merger, StepLogger):
  @override
  def run(self) -> None:
    pass  # dummy implementation

  @override
  def merge(self, a: SectionNode, b: SectionNode) -> SectionNode:
    from src.agent import MergeFormatAgent

    self.log_info(f"Merging section {a.number} with {b.number}")
    a_format = a.format_path
    b_format = b.format_path
    if not a_format or not b_format:
      raise ValueError("Both sections must have format_path to merge.")
    if a_format == "No format table in this section.":
      return SectionNode(
        a.number, a.title, a.content, a.summary, b.format_path, a.parser_path
      )
    if b_format == "No format table in this section.":
      return SectionNode(
        a.number, a.title, a.content, a.summary, a.format_path, a.parser_path
      )
    with open(a_format, "r", encoding="utf-8") as f:
      a_format_content = f.read()
    with open(b_format, "r", encoding="utf-8") as f:
      b_format_content = f.read()
    merge_agent = MergeFormatAgent(
      self.manual,
      self.example,
      a_format_content,
      b_format_content,
      a.summary or "",
      b.summary or "",
      self.data_directory,
      config_list=self.config_list,
    )

    success = False
    while not success:
      try:
        _ = merge_agent.start()
        success = merge_agent.is_successful()
      except Exception as e:
        self.log_error(f"Error during merging format: {e}")
        self.log_info("Retrying......")
        time.sleep(5)
        # merge_agent.reset_cost_and_time()
        continue
    merged_format = merge_agent.product

    self.llm_cost += merge_agent.cost
    self.llm_tool_time += merge_agent.time_calling_register_function
    self.llm_chat_time += merge_agent.time_chat
    merged_node = SectionNode(
      a.number, a.title, a.content, a.summary, merged_format, a.parser_path
    )
    self.log_info(f"Merged format saved to {merged_format}")

    return merged_node

  def __init__(
    self,
    manual_path: str,
    example_path: str,
    data_directory: str,
    _config_list: list[ConfigList],
  ) -> None:
    super().__init__("FormatMerger")
    self.data_directory: str = data_directory
    self.config_list: list[ConfigList] = _config_list
    with open(manual_path, "r", encoding="utf-8") as f:
      self.manual: str = f.read()
    with open(example_path, "r", encoding="utf-8") as f:
      self.example: str = f.read()
    self.llm_cost: float = 0.0
    self.llm_tool_time: float = 0.0
    self.llm_chat_time: float = 0.0


class ParserMerger(Merger, StepLogger):
  @override
  def run(self) -> None:
    pass  # dummy implementation

  @override
  def merge(self, a: SectionNode, b: SectionNode) -> SectionNode:
    from src.agent import MergePythonAgent

    self.log_info(f"Merging section {a.number} with {b.number}")
    a_parser = a.parser_path
    b_parser = b.parser_path
    if not a_parser or not b_parser:
      raise ValueError("Both sections must have parser_path to merge.")
    if a_parser == "No format table in this section.":
      return SectionNode(
        a.number, a.title, a.content, a.summary, a.format_path, b.parser_path
      )
    if b_parser == "No format table in this section.":
      return SectionNode(
        a.number, a.title, a.content, a.summary, a.format_path, a.parser_path
      )
    if not all(map(lambda x: Path(x).exists(), [a_parser, b_parser])):
      raise ValueError("Both parser_path must exist to merge.")
    with open(a_parser, "r", encoding="utf-8") as f:
      a_parser_content = f.read()
    with open(b_parser, "r", encoding="utf-8") as f:
      b_parser_content = f.read()

    merge_agent = MergePythonAgent(
      self.manual,
      self.example,
      a_parser_content,
      b_parser_content,
      self.data_directory,
      config_list=self.config_list,
    )

    success = False
    while not success:
      try:
        _ = merge_agent.start()
        success = merge_agent.is_successful()
      except Exception as e:
        self.log_error(f"Error during merging parser: {e}")
        self.log_info("Retrying......")
        time.sleep(5)
        # merge_agent.reset_cost_and_time()
        continue
    merged_parser = merge_agent.product
    self.llm_cost += merge_agent.cost
    self.llm_tool_time += merge_agent.time_calling_register_function
    self.llm_chat_time += merge_agent.time_chat
    merged_node = SectionNode(
      a.number, a.title, a.content, a.summary, a.format_path, merged_parser
    )
    return merged_node

  def __init__(
    self,
    manual_path: str,
    example_path: str,
    data_directory: str,
    _config_list: list[ConfigList],
  ) -> None:
    super().__init__("ParserMerger")
    with open(manual_path, "r", encoding="utf-8") as f:
      self.manual: str = f.read()
    with open(example_path, "r", encoding="utf-8") as f:
      self.example: str = f.read()
    self.data_directory: str = data_directory
    self.config_list: list[ConfigList] = _config_list
    self.llm_cost: float = 0.0
    self.llm_tool_time: float = 0.0
    self.llm_chat_time: float = 0.0


class ElementMapping(Merger, StepLogger):
  @override
  def run(self) -> None:
    pass  # dummy implementation

  def __init__(self, doc_graph: DocumentGraph) -> None:
    super().__init__("ElementMapping")
    self.supervised_doc_graph: DocumentGraph = doc_graph

  @staticmethod
  def collect_elemets_py(
    code: str,
  ) -> tuple[set[str], dict[int, set[str]], dict[str, tuple[int, int]]]:
    if code.strip() == "":
      return set(), {}, {}
    import ast

    # We want to collect all names/functions/classes defined in the code
    class CodeVisitor(ast.NodeVisitor):
      def __init__(self):
        self.elements: set[str] = set()
        self.line_to_element: dict[int, set[str]] = {}
        self.function_scope: dict[str, tuple[int, int]] = {}

      def add_element(self, name: str, lineno: int) -> None:
        self.elements.add(f"{name}:{lineno}")
        if lineno not in self.line_to_element:
          self.line_to_element[lineno] = set()
        self.line_to_element[lineno].add(name)

      @override
      def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.end_lineno is not None:
          self.function_scope[node.name] = (node.lineno, node.end_lineno)
        else:
          self.function_scope[node.name] = (node.lineno, node.lineno)
        self.add_element(node.name, node.lineno)
        for arg in node.args.args:
          self.add_element(arg.arg, node.lineno)
        self.generic_visit(node)

      @override
      def visit_ClassDef(self, node: ast.ClassDef) -> None:
        raise ValueError("Class definitions are not expected in parser code.")

      @override
      def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
          if isinstance(target, ast.Name):
            self.add_element(target.id, node.lineno)
        self.generic_visit(node)

      @override
      def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
          self.add_element(node.target.id, node.lineno)
        self.generic_visit(node)

    visitor = CodeVisitor()
    tree = ast.parse(code)
    visitor.visit(tree)
    return visitor.elements, visitor.line_to_element, visitor.function_scope

  @override
  def merge(self, a: SectionNode, b: SectionNode) -> SectionNode:
    from src.parse3d import CollectElements3D

    self.log_info(
      f"Merging section {a.number} with {b.number} to collect element mapping"
    )
    a_format = a.format_path
    a_parser = a.parser_path
    b_format = b.format_path
    b_parser = b.parser_path
    if (
      not a_format or not a_parser or not b_format or not b_parser
    ):  # should have used all() but basedpyright is not happy
      raise ValueError("All sections must have format_path and parser_path to merge.")
    if not Path(b_format).exists() or not Path(b_parser).exists():
      return a  # we cannot collect anything from b
    if a.format_path == "No format table in this section.":
      a_format_content = ""
    else:
      with open(a_format, "r", encoding="utf-8") as f:
        a_format_content = f.read()
    if a.parser_path == "No format table in this section.":
      a_parser_content = ""
    else:
      with open(a_parser, "r", encoding="utf-8") as f:
        a_parser_content = f.read()
    with open(b_format, "r", encoding="utf-8") as f:
      b_format_content = f.read()
    with open(b_parser, "r", encoding="utf-8") as f:
      b_parser_content = f.read()

    collector = CollectElements3D()
    a_elements_3d = collector.get_elements_3d(a_format_content)
    b_elements_3d = collector.get_elements_3d(b_format_content)

    a_elements_py, a_line_to_element, a_function_scope = self.collect_elemets_py(
      a_parser_content
    )
    b_elements_py, b_line_to_element, b_function_scope = self.collect_elemets_py(
      b_parser_content
    )

    # Process child (b) BEFORE parent (a) so finer-granularity section
    # mappings win.  Bottom-up traversal visits leaves first, so b is
    # always the deeper / more specific section.
    for element in b_elements_3d:
      if element not in self.supervised_doc_graph.name_to_section_3d:
        self.supervised_doc_graph.name_to_section_3d.setdefault(element, {}).setdefault(
          b.number, []
        ).extend(
          b_elements_3d[element],
        )
    for element in a_elements_3d:
      if element not in self.supervised_doc_graph.name_to_section_3d:
        self.supervised_doc_graph.name_to_section_3d.setdefault(element, {}).setdefault(
          a.number, []
        ).extend(
          a_elements_3d[element],
        )

    for element in b_elements_py:
      self.supervised_doc_graph.name_to_section_py[element] = (
        self.supervised_doc_graph.name_to_section_py.get(element, b.number)
      )
    for element in a_elements_py:
      self.supervised_doc_graph.name_to_section_py[element] = (
        self.supervised_doc_graph.name_to_section_py.get(element, a.number)
      )

    def level_in_hierarchy(
      section_number: str,
      level: int = 0,
      current: SectionNode = self.supervised_doc_graph.root,
    ) -> int:
      if current.number == section_number:
        return level
      children = self.supervised_doc_graph.children_of.get(current.number, [])
      for child_number in children:
        child_node = self.supervised_doc_graph.sections.get(child_number)
        if child_node:
          child_level = level_in_hierarchy(section_number, level + 1, child_node)
          if child_level != -1:
            return child_level
      return -1

    # Because we only want the root information is correct, we can safely overwrite the line_to_element and function_scope, because root information will be the union of all sections anyways.
    # self.supervised_doc_graph.line_to_element_py[a.number] = a_line_to_element
    for line in b_line_to_element:
      # we want to inherit the child section number from existing mapping if possible
      existing_mapping = self.supervised_doc_graph.line_to_element_py.get(
        str(line), (b.number, set())
      )[0]
      level_existing = level_in_hierarchy(existing_mapping)
      level_b = level_in_hierarchy(b.number)
      if level_existing != -1 and level_existing > level_b:
        inherited_section = existing_mapping
      else:
        inherited_section = b.number
      self.supervised_doc_graph.line_to_element_py[str(line)] = (
        inherited_section,
        b_line_to_element[line],
      )

    for func in b_function_scope:
      # inherit section number from existing mapping if possible
      existing_mapping = self.supervised_doc_graph.py_function_scope.get(
        func, (b.number,)
      )[0]
      level_existing = level_in_hierarchy(existing_mapping)
      level_b = level_in_hierarchy(b.number)
      if level_existing != -1 and level_existing > level_b:
        inherited_section = existing_mapping
      else:
        inherited_section = b.number
      self.supervised_doc_graph.py_function_scope[func] = (
        inherited_section,
        b_function_scope[func],
      )
    for line in a_line_to_element:
      existing_mapping = self.supervised_doc_graph.line_to_element_py.get(
        str(line), (a.number, set())
      )[0]
      level_existing = level_in_hierarchy(existing_mapping)
      levbel_a = level_in_hierarchy(a.number)
      if level_existing != -1 and level_existing > levbel_a:
        inherited_section = existing_mapping
      else:
        inherited_section = a.number
      self.supervised_doc_graph.line_to_element_py[str(line)] = (
        inherited_section,
        a_line_to_element[line],
      )

    # self.supervised_doc_graph.py_function_scope[a.number] = a_function_scope
    for func in a_function_scope:
      existing_mapping = self.supervised_doc_graph.py_function_scope.get(
        func, (a.number,)
      )[0]
      level_existing = level_in_hierarchy(existing_mapping)
      level_a = level_in_hierarchy(a.number)
      if level_existing != -1 and level_existing > level_a:
        inherited_section = existing_mapping
      else:
        inherited_section = a.number
      self.supervised_doc_graph.py_function_scope[func] = (
        inherited_section,
        a_function_scope[func],
      )

    # self.supervised_doc_graph.line_to_element_py[b.number] = b_line_to_element
    # self.supervised_doc_graph.py_function_scope[b.number] = b_function_scope

    self.log_info(
      f"Collected {len(a_elements_3d)} 3D elements and {len(a_elements_py)} Python elements from section {a.number}"
    )
    self.log_info(
      f"Collected {len(b_elements_3d)} 3D elements and {len(b_elements_py)} Python elements from section {b.number}"
    )
    self.log_info(
      f"Total 3D elements mapped: {len(self.supervised_doc_graph.name_to_section_3d)}"
    )
    self.log_info(
      f"Total Python elements mapped: {len(self.supervised_doc_graph.name_to_section_py)}"
    )

    # We want to modify the information stored in DocumentGraph, which is not related to SectionNode, so we just return a unchanged SectionNode here.
    return a


# ----------- Definition of SectionNode and DocumentGraph ----------- #


class SectionNodeEncoder(json.JSONEncoder):
  def __init__(self, *args: Any, **kwargs: Any) -> None:  # pyright: ignore[reportExplicitAny, reportAny]
    super().__init__(*args, **kwargs)

  @override
  def default(self, o: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny]
    if isinstance(o, SectionNode):
      return {
        "number": o.number,
        "title": o.title,
        "content": o.content,
        "summary": o.summary,
        "format_path": o.format_path,
        "parser_path": o.parser_path,
      }
    return super().default(o)  # pyright: ignore[reportAny]


class SectionNodeDict(TypedDict):
  number: str
  title: str
  content: str
  summary: str | None
  format_path: str | None
  parser_path: str | None


class SectionNodeDecoder(json.JSONDecoder):
  @staticmethod
  def is_section_node_dict(o: object) -> TypeGuard[SectionNodeDict]:
    if not isinstance(o, dict):
      return False
    required = frozenset(
      {
        "number",
        "title",
        "content",
        "summary",
        "format_path",
        "parser_path",
      }
    )
    if not required.issubset(o.keys()):  # pyright: ignore[reportUnknownArgumentType]
      return False
    return all(
      isinstance(o[key], str)
      or (key in {"summary", "format_path", "parser_path"} and o[key] is None)
      for key in required
    )

  @staticmethod
  def _object_hook(o: object) -> "SectionNode":
    if SectionNodeDecoder.is_section_node_dict(o):
      return SectionNode(
        number=o["number"],
        title=o["title"],
        content=o["content"],
        summary=o["summary"],
        format_path=o["format_path"],
        parser_path=o["parser_path"],
      )
    raise TypeError(f"Invalid SectionNodeDict: {o}")

  def __init__(self, *args: Any, **kwargs: Any) -> None:  # pyright: ignore[reportExplicitAny, reportAny]
    super().__init__(object_hook=self._object_hook, *args, **kwargs)


@final
@dataclass
class SectionNode:
  number: str
  title: str
  content: str
  summary: str | None
  format_path: str | None
  parser_path: str | None

  def __init__(
    self,
    number: str,
    title: str,
    content: str = "",
    summary: str | None = None,
    format_path: str | None = None,
    parser_path: str | None = None,
  ) -> None:
    self.number = number
    self.title = title
    self.content = content
    self.summary = summary
    self.format_path = format_path
    self.parser_path = parser_path
    self.encoder = SectionNodeEncoder()
    self.decoder = SectionNodeDecoder()

  def encode(self) -> str:
    return self.encoder.encode(self)

  @staticmethod
  def decode(s: str) -> "SectionNode":
    return SectionNodeDecoder().decode(s)  # pyright: ignore[reportAny]

  def update_content(self, content: str) -> None:
    self.content = content

  def update_summary(self, summary: str) -> None:
    self.summary = summary

  def update_format_path(self, format_path: str) -> None:
    self.format_path = format_path

  def update_parser_path(self, parser_path: str) -> None:
    self.parser_path = parser_path


@final
class DocumentGraph(StepLogger):
  @override
  def run(self) -> None:
    pass  # dummy implementation

  def __init__(self, protocol_name: str) -> None:
    super().__init__(f"DocumentGraph-{protocol_name}")
    self.root = SectionNode(
      "placeholder", f"Document Tree Root for {protocol_name}", "", None, None, None
    )
    self.protocol_name = protocol_name
    self.root_initialized = False
    self.sections: dict[str, SectionNode] = {}
    self.parent_of: dict[
      str, str
    ] = {}  # child number -> parent number to find parent in self.sections
    self.children_of: dict[
      str, list[str]
    ] = {}  # parent number -> list of child numbers to find children in self.sections

    # --- need to map section number to source elements such as struct name, field name, etc. Currently only do it to root ---
    self.name_to_section_3d: dict[
      str, dict[str, list[tuple[int, int]]]
    ] = {}  # 3d element -> (section number -> list of (line, col))
    self.name_to_section_py: dict[str, str] = {}  # python element -> section number
    self.line_to_element_py: dict[
      str, tuple[str, set[str]]
    ] = {}  # line_number -> tuple(section number, set of element names)
    self.py_function_scope: dict[
      str, tuple[str, tuple[int, int]]
    ] = {}  # function name -> (section number, (start line, end line))

  @override
  def __repr__(self) -> str:
    # do pretty print of the document graph
    result = ""
    for section in self.topological_sort_reversed():
      section_number = section.number
      parent = self.parent_of.get(section_number, "")
      children = self.children_of.get(section_number, [])
      result += (
        f"Section {section_number}: {section.title}\n"
        f"  Parent: {parent}\n"
        f"  Children: {children}\n"
        f"  Content: {section.content[:30]}...\n"
        f"  Summary: {section.summary}\n"
        f"  Format Path: {section.format_path}\n"
        f"  Parser Path: {section.parser_path}\n"
      )
    return result

  @override
  def __str__(self) -> str:
    return self.__repr__()

  @override
  def __eq__(self, other: object) -> bool:
    if not isinstance(other, DocumentGraph):
      return False
    return (
      self.protocol_name == other.protocol_name
      and self.sections == other.sections
      and self.parent_of == other.parent_of
      and self.children_of == other.children_of
    )

  def add_section(
    self,
    number: str,
    title: str,
    content: str = "",
    summary: str | None = None,
    format_path: str | None = None,
    parser_path: str | None = None,
    parent_number: str | None = None,
  ) -> SectionNode:
    if number in self.sections:
      raise ValueError(f"Section {number} already exists.")
    # if number ends with "." remove the last "."
    if number.endswith("."):
      number = number[:-1]
    new_section = SectionNode(number, title, content, summary, format_path, parser_path)
    self.sections[number] = new_section
    if parent_number:
      if parent_number not in self.sections:
        raise ValueError(f"Parent section {parent_number} does not exist.")
      self.parent_of[number] = parent_number
      self.children_of.setdefault(parent_number, []).append(number)
    else:
      if not self.root_initialized:
        self.root = new_section
        self.root_initialized = True
      else:
        # heuristic: if no parent is given, try to find a parent by section number
        parent_number = ".".join(number.split(".")[:-1])
        if parent_number in self.sections:
          self.parent_of[number] = parent_number
          self.children_of.setdefault(parent_number, []).append(number)
        else:
          ...
          # If no parent can be found, we leave it as a root-level section, to be handled later.
    return new_section

  def make_hierarchy(self, hierarchy: tuple[str, str]):
    parent, child = hierarchy
    if parent not in self.sections or child not in self.sections:
      raise ValueError(f"Parent {parent} or child {child} section does not exist.")
    previous_parent = self.parent_of.get(child)
    if parent not in self.parent_of.get(child, []):
      self.parent_of[child] = parent
    if child not in self.children_of.get(parent, []):
      self.children_of.setdefault(parent, []).append(child)
    # Note: this does not remove child from previous parent's children list, do it now

    if previous_parent and previous_parent != parent:
      if child in self.children_of.get(previous_parent, []):
        self.children_of[previous_parent].remove(child)

    # since we only record parent-child relationships, children's children shoule not be affected
    # if child has children, they remain unchanged, as they are still children of child

  def make_hierarchy_bulk(self, hierarchies: Sequence[tuple[str, str]]) -> None:
    for parent, child in hierarchies:
      self.make_hierarchy((parent, child))

  def get_section(self, number: str) -> SectionNode | None:
    return self.sections.get(number)

  def get_parent(self, number: str) -> Sequence[SectionNode] | None:
    parent_number = self.parent_of.get(number)
    if parent_number:
      return list(filter(None, map(lambda x: self.sections.get(x), parent_number)))
    return None

  def get_children(self, number: str) -> list[SectionNode]:
    child_numbers = self.children_of.get(number, [])
    return [
      self.sections[child_number]
      for child_number in child_numbers
      if child_number in self.sections
    ]

  def inline_content(self, child: str, parent: str) -> None:
    """Merge child section's content into parent section's content."""
    if child not in self.sections:
      raise ValueError(f"Child section {child} does not exist.")
    if parent not in self.sections:
      raise ValueError(f"Parent section {parent} does not exist.")
    child_section = self.sections[child]
    parent_section = self.sections[parent]
    parent_section.content = (
      parent_section.content + "\n" + child_section.content
      if parent_section.content
      else child_section.content
    )

  def remove_section(self, number: str) -> None:
    """Remove a section from the graph, cleaning up all references."""
    if number not in self.sections:
      return
    # Remove from parent_of and update parent's children list
    parent = self.parent_of.pop(number, None)
    if parent and number in self.children_of.get(parent, []):
      self.children_of[parent].remove(number)
    # Remove from children_of if this section was itself a parent
    self.children_of.pop(number, None)
    # Remove child references that pointed to this section
    for child_num, child_parent in list(self.parent_of.items()):
      if child_parent == number:
        del self.parent_of[child_num]
    # Remove from sections
    del self.sections[number]

  def encode(self) -> str:
    # Encode the entire document graph as a JSON string
    graph_dict = {
      "protocol_name": self.protocol_name,
      "root": self.root.number,
      "sections": {num: json.loads(sec.encode()) for num, sec in self.sections.items()},
      "parent_of": self.parent_of,
      "children_of": self.children_of,
      "name_to_section_3d": self.name_to_section_3d,
      "name_to_section_py": self.name_to_section_py,
      "line_to_element_py":  # convert the set in line_to_element_py to list for JSON serialization
      {
        line: (section_num, list(elements))
        for line, (section_num, elements) in self.line_to_element_py.items()
      },
      "py_function_scope": self.py_function_scope,
    }
    return json.dumps(graph_dict, indent=4)

  @staticmethod
  def decode(s: str) -> "DocumentGraph":
    graph_dict = json.loads(s)  # pyright: ignore[reportAny]
    protocol_name: str = graph_dict["protocol_name"]  # pyright: ignore[reportAny]
    doc_graph = DocumentGraph(protocol_name)
    doc_graph.sections = {
      num: SectionNode.decode(json.dumps(sec_json))
      for num, sec_json in graph_dict["sections"].items()  # pyright: ignore[reportAny]
    }
    doc_graph.root = doc_graph.sections[graph_dict["root"]]
    doc_graph.parent_of = graph_dict["parent_of"]
    doc_graph.children_of = graph_dict["children_of"]
    doc_graph.root_initialized = True
    doc_graph.name_to_section_3d = graph_dict.get("name_to_section_3d", {})  # pyright: ignore[reportAny]
    doc_graph.name_to_section_py = graph_dict.get("name_to_section_py", {})  # pyright: ignore[reportAny]
    doc_graph.line_to_element_py = {
      line: (section_num, set(elements))  # pyright: ignore[reportAny]
      for line, (section_num, elements) in graph_dict.get(  # pyright: ignore[reportAny]
        "line_to_element_py", {}
      ).items()
    }
    doc_graph.py_function_scope = graph_dict.get("py_function_scope", {})  # pyright: ignore[reportAny]
    return doc_graph

  def topological_sort(self) -> list[SectionNode]:
    visited: set[str] = set()
    result: list[SectionNode] = []

    def dfs(section_number: str) -> None:
      if section_number in visited:
        return
      visited.add(section_number)
      for child_number in self.children_of.get(section_number, []):
        dfs(child_number)
      if section_number in self.sections:
        result.append(self.sections[section_number])

    # Start DFS from root sections (those without parents)
    root_sections = [num for num in self.sections if num not in self.parent_of]
    for root in root_sections:
      dfs(root)
    return result

  def topological_sort_reversed(self) -> list[SectionNode]:
    sorted_sections = self.topological_sort()
    sorted_sections.reverse()
    return sorted_sections

  def bottom_up(self, visitor: "Merger") -> DocumentGraph:
    result_map: dict[str, SectionNode] = {}
    merged: set[str] = set()
    sorted_sections: list[SectionNode] = self.topological_sort()
    self.log_info(
      f"Bottom-up order: {' -> '.join([s.number for s in sorted_sections])}"
    )
    new_graph = DocumentGraph(self.protocol_name)

    for section in sorted_sections:
      children = self.get_children(section.number)
      merged_children = [
        result_map[c.number]
        for c in children
        if c.number in result_map and c.number not in merged
      ]
      result_map[section.number] = reduce(
        lambda a, b: visitor.merge(a, b),
        [section] + merged_children,
      )
      for c in merged_children:
        merged.add(c.number)

    # find roots (nodes without parents)
    roots = [n for n in sorted_sections if self.get_parent(n.number) is None]
    self.log_info(f"Root sections: {[r.number for r in roots]}")

    merged_roots = sorted([result_map[r.number] for r in roots], key=lambda x: x.number)
    merged_root: SectionNode = reduce(
      lambda a, b: visitor.merge(a, b),
      merged_roots,
    )
    # new_graph.root.number = merged_root.number
    # new_graph.root.format_path = merged_root.format_path
    # new_graph.root.parser_path = merged_root.parser_path
    new_graph.root = merged_root
    new_graph.root_initialized = True
    new_graph.sections = result_map
    # rebuild parent_of and children_of
    new_graph.parent_of = deepcopy(self.parent_of)
    new_graph.children_of = deepcopy(self.children_of)
    # pass other mappings
    new_graph.name_to_section_3d = deepcopy(self.name_to_section_3d)
    new_graph.name_to_section_py = deepcopy(self.name_to_section_py)
    new_graph.line_to_element_py = deepcopy(self.line_to_element_py)
    new_graph.py_function_scope = deepcopy(self.py_function_scope)
    return new_graph


@final
class DocumentGraphBuilder(StepLogger):
  @override
  def run(self) -> None:
    pass  # dummy implementation

  @staticmethod
  def load_from_json(json_path: str) -> DocumentGraph:
    from pathlib import Path

    path = Path(json_path)
    if not path.exists():
      raise FileNotFoundError(f"Document graph JSON file {json_path} not found.")
    with open(path, "r", encoding="utf-8") as f:
      json_content = f.read()
    doc_graph = DocumentGraph.decode(json_content)
    return doc_graph

  def __init__(
    self,
    protocol_name: str,
    rfc_path: str,
    directory: str = "",
    use_existing: str = "",
  ) -> None:
    super().__init__("DocumentGraphBuilder")
    self.doc_graph = DocumentGraph(protocol_name)
    self.data_directory: str = directory
    self.doc_graph_directory: str = ""
    self.doc_graph_json_path: str = ""
    self.use_existing: str = use_existing
    self.llm_cost: float = 0.0
    self.time_spent_not_chatting: float = 0.0
    self.time_spent_chatting: float = 0.0
    from src.secret import config_list

    self.config_list: list[ConfigList] = config_list
    from pathlib import Path

    self.rfc_path = Path(rfc_path)
    with open(self.rfc_path, "r", encoding="utf-8") as file:
      self.file_content = file.read()
    self.cleaned_text = DocumentGraphBuilder.clean_text(self.file_content)
    from src.tool.prompts import (
      summary_system_prompt,
      hierarchy_system_prompt,
      summary_user_prompt,
      hierarchy_user_prompt,
    )

    self.summary_system_message = summary_system_prompt()

    self.hierarchy_system_message = hierarchy_system_prompt()
    self.build_time = datetime.datetime.now()

    self.get_summary_task_prompt = summary_user_prompt
    self.get_hierarchy_task_prompt = hierarchy_user_prompt

  @deprecated("Use build() method instead.")
  def build_dummy(self) -> DocumentGraph:
    # For demonstration, we add some dummy sections and hierarchies.
    _ = self.doc_graph.add_section("1", "Introduction", "This is the introduction.")
    _ = self.doc_graph.add_section("1.1", "Background", "This is the background.")
    _ = self.doc_graph.add_section("1.2", "Scope", "This is the scope.")
    _ = self.doc_graph.add_section("2", "Methodology", "This is the methodology.")
    _ = self.doc_graph.add_section("2.1", "Data Collection", "This is data collection.")
    _ = self.doc_graph.add_section("2.2", "Data Analysis", "This is data analysis.")
    _ = self.doc_graph.add_section("1.1.1", "History", "This is the history.")
    _ = self.doc_graph.add_section("1.1.2", "Related Work", "This is related work.")
    _ = self.doc_graph.add_section(
      "2.2.1", "Statistical Methods", "This is statistical methods."
    )
    _ = self.doc_graph.make_hierarchy_bulk(
      [
        ("1", "1.1"),
        ("1", "1.2"),
        ("2", "2.1"),
        ("2", "2.2"),
        ("1.1", "1.1.1"),
        ("1.1", "1.1.2"),
        ("2.2", "2.2.1"),
      ]
    )
    # todo("Implement a real parser to parse the document and build the graph.")
    return self.doc_graph

  @staticmethod
  def clean_text(file_content: str) -> str:
    import re

    header_pattern = re.compile(r"RFC (\d+)\s+(.*?)\s+([A-Za-z]+ \d{4})")
    footer_pattern = re.compile(r"^.*\s+\[Page \d+\]$", re.MULTILINE)

    text = header_pattern.sub("", file_content)
    text = footer_pattern.sub("", text)

    text = re.sub(r"\n\s*\n", "\n", text)
    return text.strip()

  @staticmethod
  def add_line_numbers(text: str) -> str:
    from src.tool import add_line_numbers

    return add_line_numbers(text)

  def build_by_llm(self, directory: str = "") -> DocumentGraph:
    from warnings import warn

    warn("build_by_llm is an experimental method, use at your own risk.", UserWarning)
    # Step 1: Clean the text
    doc_graph = self.clean_and_reuse_text(directory)
    if doc_graph is not None:
      return doc_graph

    # Step 2: Split the text roughly into sections using LLM
    from src.agent import SplitRoughAgent

    with self.step("Rough Splitting"):
      hierarchy_agent = SplitRoughAgent()
      numbered_text = DocumentGraphBuilder.add_line_numbers(self.cleaned_text)
      cleaned_lines = self.cleaned_text.split("\n")
      rough_hierarchy = hierarchy_agent.get_splits(numbered_text)
      self.log_info(f"Rough hierarchy obtained: {rough_hierarchy}")
      splits = rough_hierarchy["splits"]

      root_section_idx = rough_hierarchy["root_section"]
      sections: list[SectionSplit] = []
      for split in splits:
        section_name = split["section_name"]
        section_number = section_name.split(" ")[0]
        if section_number.endswith("."):
          section_number = section_number[:-1]
        start_line = split["start_line_number"]
        end_line = split["end_line_number"]
        section_content = cleaned_lines[start_line - 1 : end_line]
        self.log_info(f"Section content for {section_number} - {section_name}:\n")
        self.log_info("\n".join(section_content))
        sections.append(
          SectionSplit(section_number, section_name, "\n".join(section_content))
        )
      root_section = sections[root_section_idx]
      self.log_info(
        f"Root section identified: {root_section.number} - {root_section.title}"
      )
      self.log_info(
        f"Adding section number: {root_section.number}, title: {root_section.title}"
      )
      _ = self.doc_graph.add_section(
        root_section.number, root_section.title, root_section.content
      )
      if not splits[root_section_idx]["should_related_to_implementation"]:
        self.doc_graph.root.format_path = "No format table in this section."
        self.doc_graph.root.parser_path = "No format table in this section."
      for idx, section in enumerate(sections):
        if section.number != root_section.number:
          self.log_info(
            f"Adding section number: {section.number}, title: {section.title}"
          )
          _ = self.doc_graph.add_section(section.number, section.title, section.content)
          if not splits[idx]["should_related_to_implementation"]:
            self.doc_graph.sections[
              section.number
            ].format_path = "No format table in this section."
            self.doc_graph.sections[
              section.number
            ].parser_path = "No format table in this section."
      self.log_info(f"Total sections created: {len(self.doc_graph.sections)}")
    return self.doc_graph
    todo("the rest of the LLM-based building process.")

  def clean_and_reuse_text(self, directory: str = "") -> DocumentGraph | None:
    if directory == "":
      directory = self.data_directory or str(self.rfc_path.parent)
    else:
      self.data_directory = directory
    self.log_info(f"Building DocumentGraph for {self.rfc_path}......")
    from pathlib import Path

    cleaned_file = (
      Path(directory) / "RFC" / f"{self.rfc_path.stem}_cleaned{self.rfc_path.suffix}"
    )
    cleaned_file.parent.mkdir(parents=True, exist_ok=True)

    with open(cleaned_file, "w", encoding="utf-8") as file:
      _ = file.write(self.cleaned_text)
    self.log_info(f"Cleaned RFC saved to {cleaned_file}")
    if (
      self.use_existing
      and (cleaned_file.parent / f"{self.rfc_path.stem}.json").exists()
    ):
      with open(
        cleaned_file.parent / f"{self.rfc_path.stem}.json", "r", encoding="utf-8"
      ) as file:
        json_content = file.read()
      self.log_info(
        f"Existing DocumentGraph found at {cleaned_file.parent / f'{self.rfc_path.stem}.json'}, loading..."
      )
      self.doc_graph = DocumentGraph.decode(json_content)
      self.doc_graph_directory = cleaned_file.parent.absolute().as_posix()
      self.log_info("DocumentGraph loaded successfully.")
      return self.doc_graph
    return None

  def build(self, directory: str = "") -> DocumentGraph:
    with self.step("Building"):
      if directory == "":
        directory = self.data_directory or str(self.rfc_path.parent)
      else:
        self.data_directory = directory
      self.log_info(f"Building DocumentGraph for {self.rfc_path}......")
      from pathlib import Path

      cleaned_file = (
        Path(directory) / "RFC" / f"{self.rfc_path.stem}_cleaned{self.rfc_path.suffix}"
      )
      cleaned_file.parent.mkdir(parents=True, exist_ok=True)

      with open(cleaned_file, "w", encoding="utf-8") as file:
        _ = file.write(self.cleaned_text)
      self.log_info(f"Cleaned RFC saved to {cleaned_file}")
      if (
        self.use_existing != ""
        and (cleaned_file.parent / f"{self.rfc_path.stem}.json").exists()
      ):
        # we want to first verify the existing doc graph is valid
        if not Path(self.use_existing).exists():
          raise FileNotFoundError(
            f"Specified existing DocumentGraph JSON file {self.use_existing} not found."
          )

        # copy the specified existing file to the expected location cleaned_file.parent /"{self.rfc_path.stem}.json"
        from shutil import copyfile

        _ = copyfile(
          self.use_existing, cleaned_file.parent / f"{self.rfc_path.stem}.json"
        )

        with open(
          cleaned_file.parent / f"{self.rfc_path.stem}.json", "r", encoding="utf-8"
        ) as file:
          json_content = file.read()
        self.log_info(
          f"Existing DocumentGraph found at {cleaned_file.parent / f'{self.rfc_path.stem}.json'}, loading..."
        )
        self.doc_graph = DocumentGraph.decode(json_content)
        self.doc_graph_directory = cleaned_file.parent.absolute().as_posix()
        self.log_info("DocumentGraph loaded successfully.")
        return self.doc_graph

      import re

      def contains_table(section_content: str) -> bool:
        pattern = r"(?:\s*\+-+[\+-]*\n)+"  # Horizontal dividers (+---+)
        matches = re.findall(pattern, section_content)

        # no format table
        if len(matches) == 0:
          return False
        return True

      def split_sections(text: str) -> list[SectionSplit]:
        sections: list[SectionSplit] = []
        section_header_pattern = re.compile(
          r"^([\w\d]+(?:\.\d+)*)(\.?)\s+(.*)$", re.MULTILINE
        )  # matches section headers like "1. Introduction" or "2.1. Background" etc.
        for i, match in enumerate(section_header_pattern.finditer(text)):
          start = match.start()
          end = (
            section_header_pattern.finditer(text, start + 1).__next__().start()
            if i + 1 < len(list(section_header_pattern.finditer(text)))
            else len(text)
          )
          number = match.group(1)
          title = match.group(3).strip()
          content = text[start:end].strip()
          sections.append(SectionSplit(number, title, content))
        return sections

      with self.step("Splitting Sections"):
        sections = split_sections(self.cleaned_text)
        from src.agent import AskAgent

        self.log_info(f"Total sections found: {len(sections)}")
        self.log_info("Adding sections based on number heuristic......")
      with self.step("Summarizing"):
        for section in sections:
          self.log_info(f"Processing section {section.number}: {section.title}")
          self.log_info(f"Section content: \n{section.content}\n")
          number, title, content = section.number, section.title, section.content
          if content != "":
            # want to summary content
            self.log_info(f"Summarizing section {number}: {title}......")
            summary = ""
            summary_agent = AskAgent()
            while not summary:
              summary = summary_agent.ask(
                self.get_summary_task_prompt(number, title, content),
                self.summary_system_message,
              )
              self.log_info(f"Received summary: {summary}")
              import re

              if isinstance(summary, str):
                summary = re.sub(r"\n*TERMINATE\s*$", "", summary)
                # try to remove code fences if any
                if summary.startswith("```") and summary.endswith("```"):
                  summary = "\n".join(summary.split("\n")[1:-1])
                  self.log_info(f"Removed code fences, new summary: {summary}")
                try:
                  summary = json.loads(summary)  # pyright: ignore[reportAny]
                except json.JSONDecodeError:
                  try:
                    summary = eval(summary)  # pyright: ignore[reportAny]
                  except Exception as e:
                    summary = ""  # keep summary as empty to retry
                    summary_agent.reset_cost_and_time()  # reset cost and time for retry
                    continue  # keep summary as empty to retry

            summary_text = summary.get("summary", None)
            if not isinstance(summary_text, str) and summary_text is not None:
              raise ValueError(f"Summary text is not a string: {summary_text}")
            self.log_info(f"Summary for section {number}: {summary_text}")
            self.llm_cost += summary_agent.cost
            init_format = None
            init_parser = None
            if not contains_table(content) and "." not in number:
              init_format = "No format table in this section."
              init_parser = "No format table in this section."
            _ = self.doc_graph.add_section(
              number, title, content, summary_text, init_format, init_parser
            )
      # with self.step("Merging Content"):
      #   # before building hierarchy, we want to merge contents of sections
      #   self.doc_graph = self.doc_graph.bottom_up(ContentMerger())
      with self.step("Building Hierarchy"):
        hierarchy_agent = AskAgent()
        hierarchies = hierarchy_agent.ask(
          self.get_hierarchy_task_prompt(
            list(map(lambda x: x, list(self.doc_graph.sections.values())))
          ),
          self.hierarchy_system_message,
        )
        self.log_info(f"Received hierarchies: {hierarchies}")
        if isinstance(hierarchies, str):
          # try to remove the werid TERMINATE word at the end
          hierarchies = re.sub(r"\n*TERMINATE\s*$", "", hierarchies)
          # try to remove code fences if any
          if hierarchies.startswith("```") and hierarchies.endswith("```"):
            hierarchies = "\n".join(hierarchies.split("\n")[1:-1])
          # try to remove any surrounding text before and after JSON
          json_start = hierarchies.find("{")
          json_end = hierarchies.rfind("}")
          if json_start != -1 and json_end != -1:
            hierarchies = hierarchies[json_start : json_end + 1]
          try:
            hierarchies = json.loads(hierarchies)  # pyright: ignore[reportAny]
          except json.JSONDecodeError:
            try:
              hierarchies = eval(hierarchies)  # pyright: ignore[reportAny]
            except Exception as e:
              self.log_error(
                f"Failed to parse hierarchies JSON: {e}\nHierarchies: {hierarchies}"
              )
              hierarchy_agent.reset_cost_and_time()  # reset cost and time for retry
              raise e
        if not isinstance(hierarchies, dict) or "hierarchies" not in hierarchies:
          try:
            hierarchies = json.loads(hierarchies["content"])
          except Exception:
            raise ValueError(
              f"Hierarchies is not a dict or missing 'hierarchies': {hierarchies}"
            )
        if not isinstance(hierarchies["hierarchies"], list):
          raise ValueError(f"'hierarchies' is not a list: {hierarchies['hierarchies']}")
        self.llm_cost += hierarchy_agent.cost

        # Group hierarchy entries by child to detect multi-parent cases.
        # The data model only supports one parent per child, so sections
        # referenced by multiple parents are inlined into each parent
        # instead of becoming regular children.
        child_parents: dict[str, list[str]] = {}
        for parent, child in hierarchies["hierarchies"]:  # pyright: ignore[reportUnknownVariableType]
          if parent in self.doc_graph.sections and child in self.doc_graph.sections:
            child_parents.setdefault(child, []).append(parent)

        multi_parent_children = {
          child: parents
          for child, parents in child_parents.items()
          if len(parents) > 1
        }
        single_parent_pairs = [
          (parents[0], child)
          for child, parents in child_parents.items()
          if len(parents) == 1
        ]

        # Inline multi-parent sections into all their parents
        for child, parents in multi_parent_children.items():
          self.log_info(
            f"Inlining multi-parent section {child} into: {parents}"
          )
          for parent in parents:
            self.doc_graph.inline_content(child, parent)
          self.doc_graph.remove_section(child)

        self.doc_graph.make_hierarchy_bulk(single_parent_pairs)
        # write to file

      # for debug
      _ = self.doc_graph.bottom_up(ViewMerger())
      self.doc_graph = self.doc_graph.bottom_up(ContentMerger())

      self.write_back_to_file(cleaned_file.parent.absolute().as_posix())

      return self.doc_graph

  def get_graph(self) -> DocumentGraph:
    return self.doc_graph

  def get_protocol_name(self) -> str:
    return self.doc_graph.protocol_name

  def get_rfc_path(self) -> str:
    return str(self.rfc_path)

  def get_cleaned_text(self) -> str:
    return self.cleaned_text

  def get_sections(self) -> dict[str, SectionNode]:
    return self.doc_graph.sections

  def write_back_to_file(self, directory: str = "") -> None:
    with self.step("Writeback"):
      from pathlib import Path

      if self.doc_graph_json_path != "":
        unify_place = (
          Path(self.doc_graph_json_path).parent / f"{self.rfc_path.stem}.json"
        )
        place = self.doc_graph_json_path
      else:
        if directory == "":
          directory = self.doc_graph_directory or str(self.rfc_path.parent)
        else:
          self.doc_graph_directory = directory
        unify_place = Path(directory) / f"{self.rfc_path.stem}.json"
        place = str(Path(directory) / f"{self.rfc_path.stem}-{self.build_time}.json")
        self.doc_graph_json_path = place
      Path(place).parent.mkdir(parents=True, exist_ok=True)
      self.log_info(f"Writing DocumentGraph back to {place}......")
      with open(place, "w", encoding="utf-8") as file:
        _ = file.write(self.doc_graph.encode())
      self.log_info(f"Writing unified DocumentGraph back to {unify_place}......")
      with open(unify_place, "w", encoding="utf-8") as file:
        _ = file.write(self.doc_graph.encode())

  def gen_format(self, manual_path: str, example_path: str) -> None:
    with self.step("Format Generation"):
      with open(manual_path, "r", encoding="utf-8") as f:
        manual_text = f.read()
      with open(example_path, "r", encoding="utf-8") as f:
        example_text = f.read()
      from src.agent import Generate3DAgent

      for section in self.doc_graph.sections.values():
        self.log_info(f"Generating format for section {section.number}......")
        if section.format_path is None:
          gen3d = Generate3DAgent(
            manual_text,
            example_text,
            section.content,
            self.data_directory,
            config_list=self.config_list,
          )
          # generate format for this section
          request_success = False
          while not request_success:
            try:
              gen3d.start()
              request_success = gen3d.is_successful()
            except Exception as e:
              # raise e
              self.log_error(f"Error: {e}")
              import inspect

              self.log_info(f"Traceback: {inspect.trace()}")
              self.log_info(message="Retrying......")
              time.sleep(5)
              # gen3d.reset_cost_and_time()  # reset cost and time for retry
              continue
          format = gen3d.product
          section.update_format_path(format)
          self.llm_cost += gen3d.cost
          self.time_spent_not_chatting += gen3d.time_calling_register_function
          self.time_spent_chatting += gen3d.time_chat
          self.write_back_to_file()
      self.write_back_to_file()

  def gen_parser(self, manual_path: str, example_path: str) -> None:
    with self.step("Parser Generation"):
      with open(manual_path, "r", encoding="utf-8") as f:
        manual_text = f.read()
      with open(example_path, "r", encoding="utf-8") as f:
        example_text = f.read()
      from src.agent import GeneratePythonAgent

      for section in self.doc_graph.sections.values():
        self.log_info(f"Generating parser for section {section.number}......")
        if section.parser_path is None:
          genpy = GeneratePythonAgent(
            manual_text,
            example_text,
            section.content,
            self.data_directory,
            config_list=self.config_list,
          )
          # generate parser for this section
          request_success = False
          while not request_success:
            try:
              genpy.start()
              request_success = genpy.is_successful()
            except Exception as e:
              self.log_error(f"Error: {e}")
              self.log_info("Retrying......")
              time.sleep(5)
              # genpy.reset_cost_and_time()  # reset cost and time for retry
              continue
          parser = genpy.product
          section.update_parser_path(parser)
          self.llm_cost += genpy.cost
          self.time_spent_not_chatting += genpy.time_calling_register_function
          self.time_spent_chatting += genpy.time_chat
          self.write_back_to_file()
      self.write_back_to_file()

  def merge_format(self, manual_path: str, example_path: str) -> None:
    with self.step("Format Merging"):
      # if (
      #   self.doc_graph.root.format_path is not None
      #   and self.doc_graph.root.format_path != "No format table in this section."
      # ):
      #   return
      merge3d = FormatMerger(
        manual_path, example_path, self.data_directory, _config_list=self.config_list
      )
      self.doc_graph = self.doc_graph.bottom_up(merge3d)
      self.llm_cost += merge3d.llm_cost
      self.time_spent_not_chatting += merge3d.llm_tool_time
      self.time_spent_chatting += merge3d.llm_chat_time

      self.write_back_to_file()

  def merge_parser(self, manual_path: str, example_path: str) -> None:
    with self.step("Parser Merging"):
      # if (
      #   self.doc_graph.root.parser_path is not None
      #   and self.doc_graph.root.parser_path != "No format table in this section."
      # ):
      #   return
      mergepy = ParserMerger(
        manual_path, example_path, self.data_directory, _config_list=self.config_list
      )
      self.doc_graph = self.doc_graph.bottom_up(mergepy)
      self.llm_cost += mergepy.llm_cost
      self.time_spent_not_chatting += mergepy.llm_tool_time
      self.time_spent_chatting += mergepy.llm_chat_time
      self.write_back_to_file()

  def map_elements(self) -> None:
    with self.step("Element Mapping"):
      _ = self.doc_graph.bottom_up(ElementMapping(self.doc_graph))
      self.write_back_to_file()


# ----------- Definitions to make basedpyright happy ----------- #


class SectionSplit(NamedTuple):
  number: str
  title: str
  content: str
