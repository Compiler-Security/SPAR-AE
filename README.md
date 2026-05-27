SPAR: Generating Precise Format Specification for Network Protocols Through Adversarial LLM Interactions
---

**SPAR** automatically generates verified protocol specifications from natural-language descriptions. It leverages Large Language Models (LLMs) and adversarial refinement to verify and produce precise specifications.

Built on [EverParse](https://github.com/project-everest/everparse) (verifier), [Z3](https://github.com/Z3Prover/z3) (SMT solver), and the [autogen](https://github.com/microsoft/autogen) framework (LLM orchestration).

**Paper**: Generating Precise Format Specification for Network Protocols Through Adversarial LLM Interactions. Submitted to USENIX Security 2026.

**Artifact Claim**: The tool can automatically produce a precise protocol format specification from an RFC. This artifact demonstrates the BFD protocol generation and verification. Evaluators can run `main.py` on BFD and then use `eval_3d.py` to check the structural match against the ground truth. Due to the inconsistencies introduced by LLM providers and LLM models themselves, the artifact focuses on demonstrating the end-to-end workflow and providing a framework for evaluation, rather than guaranteeing exact numeric reproduction of paper results.


Repository Structure
---
```text
SPAR-AE/
├── main.py                 # CLI entry point
├── eval_3d.py              # Metrics evaluator (generated vs. ground truth)
├── pyproject.toml          # Project metadata & dependencies (uv-managed)
├── README.md               # This file
├── LICENSE                 # MIT
├── everparse/              # EverParse library (see Setup §2)
├── scripts/
│   ├── setup_everparse.sh  # Automated EverParse download
│   └── run_eval.sh         # Offline evaluation of all protocols
├── data/
│   ├── RFC/                # Protocol RFC text files (BGPv4, NTP, IGMP, BFD, BABEL, SCTP, DNS, HTTP2)
│   ├── DSL/                # DSL references (3d_syntax_check.txt, python_coding_style.txt)
│   ├── example/            # Example format/parser files per protocol as 3D generation harness
│   ├── ground_truths/      # 15 ground truth .3d specification files, some unused in the evaluation
│   └── packaged_results/   # Pre-computed outputs for offline evaluation (8 protocols)
└── src/
    ├── secret/             # LLM credentials (see Configuration)
    ├── driver/             # Pipeline driver
    ├── doc_graph/          # Document graph construction
    ├── refine/             # Refinement loop (verifier, tester, auto_evaluator)
    ├── parse3d/            # 3D format parser and AST
    ├── encode/             # Test case generation
    ├── fsm/                # Finite state machine extraction
    ├── hybrid_fuzz/        # Concolic fuzzing engine including program slicing
    ├── agent/              # LLM agent wrappers
    ├── ablation/           # Ablation study 1. Others are controlled by flags in main.py
    ├── tool/               # Utility functions and prompts
    ├── log/                # Logging infrastructure
    └── parallel_work/      # Parallel processing support (Unused)
```

Setup & Prerequisites
---
### 1. Python & Dependency Management

This project uses [`uv`](https://docs.astral.sh/uv/) for deterministic dependency management.

**Install `uv` (Linux):**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Alternatively, `pip install uv` works on any platform. See the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/) for other options.

**Sync dependencies:**

```bash
uv sync
```

This creates a virtual environment and installs all required packages at pinned versions.

### 2. EverParse Verifier

SPAR uses **EverParse** to formally verify the syntax of generated protocol specifications.

**Automated setup (recommended):**

```bash
bash scripts/setup_everparse.sh
```

This downloads the `v2025.06.05` release for Linux and extracts it to `everparse/`.

**Manual setup:**

1. Download the `v2025.06.05` release of EverParse for your platform from [GitHub](https://github.com/project-everest/everparse/releases/tag/v2025.06.05).
2. Extract the archive into the project root.
3. Rename the extracted directory to `everparse`.

Make sure the internal structure looks like `everparse/bin/...`, **not** `everparse/everparse-v2025.06.05-linux-x86_64/bin/...`. If the archive extracts to a nested subdirectory, move the contents up so that the `bin/` directory is directly under `everparse/`.

After correct extraction, the directory layout is:

```text
SPAR-AE/
├── everparse/
│   └── bin/        <-- EverParse binaries here
├── src/
├── main.py
└── ...
```

**Verification:** Confirm EverParse is working by running `./everparse/everparse.sh --version`.

**Troubleshooting:** If the EverParse binary fails with a library error, ensure required system libraries are installed (`glibc` on Linux).

System Requirements
---
- **OS**: Linux x86_64 (tested on Ubuntu 22.04). This artifact only supports Linux.
- **Python**: 3.12
- **RAM**: ~4GB (varies by protocol complexity).
- **Storage**: ~500MB for dependencies and generated artifacts.
- **Network**: Required for LLM API calls and `uv sync`. If using pre-computed outputs, network access is not needed for LLM interactions.
- **API Access**: An API key for a supported LLM provider is required to run the full pipeline. See Configuration below.
- **Runtime**: BFD example takes 5~20 minutes depending on LLM response times and adversarial interaction rounds. Full ablation suite takes around 6~8 hours.

Configuration
---

API credentials are **not** included in this artifact. Edit [`src/secret/secret.py`](src/secret/secret.py) and populate `config_list` and `config_list_reasoner` with your own LLM provider credentials.

Usage
---
Once dependencies are installed and credentials configured, run:

```bash
uv run python main.py --help
```

for a complete list of arguments and flags.

### Basic Generation

To generate a verified specification for a protocol, provide the protocol name, its RFC document, and a data directory containing the DSL reference files and examples. For example:

```bash
uv run python main.py \
  --protocol-name BFD \
  --rfc-path data/RFC/BFD.txt \
  --data-directory data/
```

The pipeline builds a document graph from the RFC, generates an initial format and parser via the LLM, then enters a refinement loop: the verifier tests the parser against generated test cases, and counterexamples drive the LLM to fix discovered bugs until no failures remain. Generated artifacts (format, parser, cost/runtime summary) are written under `<data-directory>/packaged_results/`.

### Optimization Flags

Three optimizations are **enabled by default**. Each can be turned off individually:

| Flag | Effect |
|---|---|
| `--disable-opt-i` | Disable path-cover optimization (test all paths exhaustively) |
| `--disable-opt-ii` | Disable constraint-negation pruning (explore all constraint combinations) |
| `--disable-opt-iii` | Disable instrumentation-based slicing (fall back to FSM-diff based refinement) |

### Ablation Studies

| Flag | Ablation | Description |
|---|---|---|
| `--run-wo-rfc` | Ablation 1 | Generate format and parser **without** the RFC text, using only the protocol name and DSL syntax reference |
| `--disable-opt-i` | Ablation 2 | Run with Optimization I disabled (full path enumeration instead of path cover) |
| `--disable-opt-ii` | Ablation 3 | Run with Optimization II disabled (exhaustive constraint-negation exploration) |
| `--disable-opt-iii` | Ablation 4 | Run with Optimization III disabled (FSM-diff fallback instead of instrumentation-guided slicing) |

Ablation 1 is a standalone run (`--run-wo-rfc` skips the normal refinement pipeline entirely). Ablations 2–4 are the optimization flags above, reused as ablation conditions to measure each optimization's contribution.

### Evaluating Generated Specifications

`eval_3d.py` measures structural similarity and constraint equivalence between a generated specification and the ground truth:

```bash
uv run python eval_3d.py --ground-truth path/to/reference.3d --generated path/to/output.3d
```

It reports the overall match score, strict pass/fail, and a per-definition breakdown of type and constraint-level alignment for every field. The automated evaluator is conservative and may report false negatives for structurally different but semantically equivalent representations (e.g., inline structs vs. named struct references). Human auditing is recommended to verify the nature of reported mismatches.

### Quick-Start (No API Keys)

Evaluate pre-computed SPAR results for all 8 protocols against their ground truth specifications. No API keys or network access required. Ensure you have run `uv sync` (see Setup & Prerequisites) beforehand.

```bash
bash scripts/run_eval.sh
```

Each protocol prints detailed results. Per-protocol output looks like:

```
═══════════════════════════════════════
  BFD
  Ground truth: data/ground_truths/BFD.3d
  Generated:    data/packaged_results/BFD_3c74bfa1/BFD_CONTROL.3d
═══════════════════════════════════════
Ground truth:   BFDControlPacket
Generated:      BFDControl
Overall score:  0.849
Strict pass:    False
Definitions:    7 (5 full, 1 partial)
...
```

Scores being lower than expected and `strict: False` are primarily due to the evaluator's conservative comparison logic (see Evaluating Generated Specifications above). Generated specifications may still be semantically correct — review the per-definition breakdown for each protocol to confirm. Common false negatives include: inline struct definitions vs. named casetype references, and field decomposition into sub-structs vs. flat inlining.

### Full Generation (Requires API Keys)

To run the full pipeline from scratch (BFD example):

```bash
# 1. Edit src/secret/secret.py with your API credentials
# 2. Generate the specification and parser, then refine via adversarial testing:
uv run python main.py \
  --protocol-name BFD \
  --rfc-path data/RFC/BFD.txt \
  --data-directory data/

# 3. Evaluate the generated specification against ground truth:
GEN_DIR=$(ls -dt data/packaged_results/BFD_*/ | head -1)
GEN_FILE=$(find "$GEN_DIR" -maxdepth 1 -name "*.3d" ! -name "initial_*" | head -1)
uv run python eval_3d.py \
  --ground-truth data/ground_truths/BFD.3d \
  --generated "$GEN_FILE"
```

Ground truth specification files for all 15 protocols are located in `data/ground_truths/`. The 8 protocols with RFC files available under `data/RFC/` are: BFD, BGPv4, DNS, HTTP2, IGMP, NTP, SCTP, BABEL. To run a different protocol, substitute the protocol name and RFC path accordingly.

### Output Files

After a successful run, generated artifacts are written to `data/packaged_results/<protocol>_<uuid>/`:

| File | Description |
|---|---|
| `<name>.3d` | Final verified format specification (e.g., `BFD_CONTROL.3d`) |
| `<name>.py` | Final parser implementation (e.g., `MERGED_BFD_PARSER.py`) |
| `<name>.json` | Document graph (intermediate representation) |


License
---

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.