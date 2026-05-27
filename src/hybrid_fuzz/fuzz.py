from __future__ import annotations
from src.hybrid_fuzz.concolic import PathEvent
from src.hybrid_fuzz.instrument import (
  InstrumentationError,
  InstrumentationResult,
  Instrumentator,
)

import z3

from src.tool import todo
import time


class HybridFuzzer:
  def __init__(
    self,
    source_code: str,
    filename: str,
    seeds: set[bytes],
    timeout: float = 60.0,
    max_iterations: int = 100,
  ):
    self.source_code: str = source_code
    self.filename: str = filename
    self.seeds: set[bytes] = seeds
    self.input_queue: list[bytes] = list(seeds)
    self.used_inputs: set[bytes] = set()
    self.timeout: float = timeout
    self.max_iterations: int = max_iterations
    self.collected_testcases: dict[
      bytes, InstrumentationResult
    ] = {}  # Maps input bytes to their instrumentation results, including path constraints

  def reset(self):
    """Reset the fuzzer state"""
    self.input_queue = list(self.seeds)
    self.used_inputs = set()
    self.collected_testcases = {}

  def fuzz(self) -> dict[bytes, InstrumentationResult]:
    """Perform hybrid fuzzing according to timeout and max_iterations"""
    self.reset()
    current_time = time.time()
    iterations = 0
    instrumentator = Instrumentator(self.source_code, self.filename)
    while (
      time.time() - current_time
    ) < self.timeout and iterations < self.max_iterations:
      if not self.input_queue:
        break  # No more inputs to process
      input_pkt = self.input_queue.pop(0)
      if input_pkt in self.used_inputs:
        continue
      self.used_inputs.add(input_pkt)
      result = instrumentator.run(input_pkt)
      self.collected_testcases[input_pkt] = result
      # Analyze path constraints to generate new inputs
      for event in result.constraints:
        try:
          new_input = result.gen_new_input(event)
          if (
            new_input not in self.used_inputs
          ):  # do not check against input_queue, since it is slow to check list and duplicates will be ignored anyways
            self.input_queue.append(new_input)
        except InstrumentationError:
          # Could not generate new input for this constraint
          pass
        except Exception as e:
          raise e
      iterations += 1
    return self.collected_testcases
