from typing import TypedDict
from src.tool import todo

class ConfigList(TypedDict):
  model: str
  base_url: str
  api_key: str
  api_type: str
  tags: list[str]
  temperature: float
  stream: bool


config_list: list[ConfigList] = todo("Fill in your LLM provider credentials here.")

config_list_reasoner: list[ConfigList] = todo("Fill in your LLM provider credentials for the reasoning agent here.")
