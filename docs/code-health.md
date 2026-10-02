# Code health

Raggie measures complexity from the tree-sitter AST while indexing. After every response by the main agent it shows a short summary of the worst offenders, and `/health` writes a full report. The feature is marked beta.

## The summary

```
health stats: (beta)
  top bloated functions:
    1. parse_document()  src/parser/core.py:298  VERY HIGH
    2. handle_request()  src/api/router.py:112  HIGH
    3. sync_orders()  src/jobs/sync.py:40  BLOATED
  top bloated objects:
    1. OrderService  src/services/orders.py:25  BLOATED  (score 2.41, methods 24, attributes 18, lines 1240)

  use /health to generate the full report
```

- Up to 3 functions and up to 3 classes are listed.
- If nothing crosses the thresholds, it prints "the codebase is healthy".
- Subagents do not print it.
- In the web UI it never mixes into the chat text. It goes to a health panel instead.

## Function complexity

```
score = round(branch_count / 30, 2) + line_count / 100
```

- **`branch_count`**: weighted count of branching constructs in the function. Nested branches weigh more (see below).
- **`line_count`**: `end_line - start_line + 1`.

| Score | Label | Color |
|---|---|---|
| 1.5 or less | not listed | |
| above 1.5 | BLOATED | yellow |
| above 3.5 | HIGH | red |
| above 5.5 | VERY HIGH | red |

### What counts as a branch

- **Conditionals**: `if`, `match` / `switch`, `try` / `catch`
- **Loops**: `for`, `while`, `do-while`, `foreach`, `loop` (Rust), range-based `for` (C++)
- **Elixir**: calls to `if`, `case`, `cond`, `try`, `receive`, `for`, `with`, `unless`

Not counted: `goto`, `break`, `continue`, `return`, labeled jumps.

### Nesting weight

Each branch contributes a weight based on how deeply it is nested inside other branches. The mode is set by `NESTING_WEIGHT_MODE` in `src/indexing/node_utils.py`:

| Mode | Weight at depth 1 / 2 / 3 / 4 / 5 | Description |
|---|---|---|
| `"sqrt"` | 1.0, 1.4, 1.7, 2.0, 2.2 | **Default.** Mild nesting penalty |
| `"linear"` | 1, 2, 3, 4, 5 | Each level adds 1 |
| `"flat"` | 1, 1, 1, 1, 1 | Plain branch count |
| `"quadratic"` | 1, 4, 9, 16, 25 | Harsh nesting penalty |

```python
NESTING_WEIGHT_MODE = "sqrt"  # "linear", "flat", or "quadratic"
```

Branch counts are stored at index time, so run `/reindex --force` after changing the mode.

### Macros

C and C++ preprocessor macros and Rust `macro_rules!` entries are indexed as function-like symbols of type `macro`. Each gets its own branch count and appears in the report.

## Class bloat

Top-level classes with at least one method are scored on size and coupling:

```
score = method_count / 30
      + avg_method_loc / 30
      + attribute_count / 15
      + fan_out / 10
      + 0.5 if fan_in > 5
```

| Term | Meaning |
|---|---|
| `method_count` | Number of methods |
| `avg_method_loc` | Average method length in lines |
| `attribute_count` | Number of attributes |
| `fan_out` | Distinct classes and modules the class's methods depend on |
| `fan_in` | Distinct outside functions that call into the class. More than 5 adds a flat penalty, because a widely used class is riskier to split |

| Score | Severity |
|---|---|
| below 1.0 | OK |
| 1.0 or more | LARGE |
| 2.0 or more | BLOATED |
| 3.0 or more | VERY BLOATED |

The summary lists classes scoring 1.5 or more.

## `/health`

Writes `complexity_report_<YYYYMMDD_HHMMSS>.txt` to the project directory.

Contents:

- Timestamp and the number of functions that have branches
- Every such function, sorted by score: name, file and line, complexity score, raw branch count, line count, and the owning type for methods
- A **Class Bloat Report**: up to 25 classes with score and severity, method, attribute and line counts, and fan-in (callers and caller files) and fan-out

In the web UI the health panel can show the same data without writing a file.

## Under the hood

Two index queries feed everything: `get_top_complex_functions(limit)` returns functions with `branch_count > 0` ordered by the complexity formula, and `get_top_bloated_classes(limit, min_score)` returns scored classes. Both live in `src/indexing/queries.py`.
