def main():
  from src.driver import Driver
  from tap import tapify  # pyright: ignore[reportUnknownVariableType]

  tapify(
    Driver,
    underscores_to_dashes=True,
    description="SPAR, a protocol specification generator based on LLM and discrepancy-based refinement.",
  ).run()


if __name__ == "__main__":
  main()
