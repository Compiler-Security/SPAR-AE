def length_byte_size_array(array_name: str, array_size: str):
  return f"(length_byte_size_array({array_name}) == ({array_size}))"


def length_array(array_name: str, array_size: str):
  return f"(length_array({array_name}) == ({array_size}))"


def size_eq_zero(array_size: str):
  return f"(({array_size}) == 0)"


def size_mod_eq_zero(array_size: str, mod: int):
  return f"(({array_size}) % {mod} == 0)"


def a_and_b(a: str | None, b: str | None) -> str | None:
  if a is None or a == "True":
    return b
  if b is None or b == "True":
    return a
  return f"(({a}) and ({b}))"


def a_or_b(a: str | None, b: str | None) -> str | None:
  if a is None:
    return b
  if b is None:
    return a
  return f"(({a}) or ({b}))"


def bits_complete_for_type(type_name: str, bits: int) -> bool:
  if type_name not in ("UINT8BE", "UINT16BE", "UINT32BE", "UINT64BE"):
    raise ValueError(f"Unsupported type name {type_name} in bits_complete")
  return int(type_name[4:-2]) == bits  # UINT32BE -> 32 == 32


def add_line_numbers(text: str) -> str:
  # split the text into lines, keep empty lines
  lines = text.split("\n")

  # add "number:", with number starting from 1, first compute the max width, then pad with spaces
  max_width = len(str(len(lines)))
  numbered_lines = [
    f"{str(i + 1).rjust(max_width)}: {line}" for i, line in enumerate(lines)
  ]
  return "\n".join(numbered_lines)


def normalize_name(name: str) -> str:
  return (
    name.replace("@", "_at_")
    .replace("(", "_lp_")
    .replace(")", "_rp_")
    .replace("[", "_lb_")
    .replace("]", "_rb_")
    .replace(".", "_dot_")
    .replace("<", "_lt_")
    .replace(">", "_gt_")
    .replace("=", "_eq_")
    .replace(",", "_comma_")
    .replace("-", "_dash_")
    .replace(" ", "_space_")
  )
