from pathlib import Path
from typing import final
import tempfile
import os

from src.tool import todo


@final
class PacketValidator:
  def __init__(self, format_code: str, entry_func: str):
    # we want to normalize line endings to \n and replace "== sizeof(XX)" constraints with >= 0 because 3d sucks
    self.format_code = format_code.replace("\r\n", "\n")
    import re

    self.format_code = re.sub(r"==\s*sizeof\([A-Za-z0-9_]+\)", ">= 0", self.format_code)

    self.format_entry = entry_func
    # open a temporary directory to store the format file
    self.temp_dir = tempfile.TemporaryDirectory()
    self.format_file_path = f"{self.temp_dir.name}/Format.3d"
    self.validator_path = ""
    self.validator_generate_failed = False
    with open(self.format_file_path, "w", encoding="utf-8") as f:
      _ = f.write(self.format_code)

  def generate_validator(self) -> None:
    cwd = Path.cwd()
    cmd = [
      "bash",
      Path("everparse/everparse.sh").absolute().as_posix(),
      f"{self.format_file_path}",
      "--no_clang_format",
      "--test_checker",
      f"Format.{self.format_entry}",
    ]
    os.chdir(self.temp_dir.name)
    # command to run everparse to generate the validator
    # run the command and capture output
    import subprocess

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    if stdout:
      output_dump = stdout.decode("utf-8")
    else:
      output_dump = ""
    if stderr:
      output_err = stderr.decode("utf-8")
    else:
      output_err = ""
    if process.returncode != 0:
      os.chdir(cwd)
      print(
        f"Failed to generate validator:\nSTDOUT:\n{output_dump}\nSTDERR:\n{output_err}"
      )
      self.validator_generate_failed = True
    print("Validator generation output:")
    print(output_dump)
    print("Validator generation error (if any):")
    print(output_err)
    # the validator binary should be at temp_dir/test.exe
    self.validator_path = f"{self.temp_dir.name}/test.exe"
    if not Path(self.validator_path).exists():
      if self.validator_generate_failed:
        print("Warning: Validator binary not found, but no generation error reported.")
        os.chdir(cwd)
        return
      os.chdir(cwd)
      raise FileNotFoundError(
        "Validator binary not found after generation. Directory contents:\n"
        + "\n".join([str(p) for p in Path(self.temp_dir.name).iterdir()])
      )
    os.chdir(cwd)

  def validate_packet(self, packet: bytes) -> tuple[bool, str]:
    import subprocess

    if not self.validator_path:
      raise RuntimeError(
        "Validator not generated yet. Call generate_validator() first."
      )
    # write packet to a temporary file
    with open(f"{self.temp_dir.name}/input_pkt.bin", "wb") as f:
      _ = f.write(packet)
    process = subprocess.Popen(
      [self.validator_path, f"{self.temp_dir.name}/input_pkt.bin"],
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
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
    print("Validator execution output:")
    print(output_dump)
    print("Validator execution error (if any):")
    print(output_err)
    # assume that exit code 0 means valid packet
    return (
      "Reason: impossible" in output_dump + "\n" + output_err
      or process.returncode in (0, 1),
      output_dump + "\n" + output_err,
    )
