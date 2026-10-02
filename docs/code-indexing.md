# Code indexing

Raggie parses your project with tree-sitter and stores the result in a SQLite database at `.raggie/.code_index.raggie`. The index is what lets the agent ask "what calls this?" instead of grepping and guessing.

It holds:

- **Symbols**: functions, methods, classes, structs, interfaces, enums, variables, type aliases, with their locations
- **Imports** per file
- **Dependencies**: which function calls or references which symbol, resolved across files, in both directions (dependencies and dependents)
- **Complexity data**: branch counts used by [code health](code-health.md)

The tools built on it are `GetFileCodeSemantics`, `GetSymbolSourceCode`, `WalkCallTree` and `EditSymbol`. See [Tools](tools.md).

## When indexing runs

| Moment | What runs |
|---|---|
| Chat start | Incremental index |
| Before each message | Incremental index |
| After a file-modifying tool or a shell command | Incremental index |
| `/reindex` | Incremental index on demand |
| `/reindex --force` | Full rebuild |

Incremental means only new files, changed files, and the files that depend on a changed file are parsed again, so on an unchanged project it costs almost nothing. Changes are detected by modification time first, then confirmed with a content hash. Pressing Ctrl+C during indexing keeps the existing index and continues.

## Supported languages

| Language | Extensions | What gets indexed |
|---|---|---|
| **Python** | `.py` | Functions, classes, methods, imports, variables, type aliases, docstrings |
| **Go** | `.go` | Functions, methods with receivers, structs, interfaces, type aliases, imports |
| **C#** | `.cs` | Methods, constructors, classes, records, interfaces, structs, enums, namespaces, properties, using directives |
| **JavaScript** | `.js`, `.jsx` | Functions, generators, classes, methods, imports, variables |
| **TypeScript** | `.ts` | Functions, classes, interfaces, type aliases, enums, public fields, imports |
| **TSX** | `.tsx` | Same as TypeScript, with JSX |
| **Rust** | `.rs` | Functions, structs, enums, traits, impl blocks, constants, statics, type aliases, `use` declarations, `macro_rules!` |
| **Zig** | `.zig` | Functions, `const` / `var` declarations, `@import` |
| **Elixir** | `.ex`, `.exs` | `def` / `defp` / `defmacro`, modules, aliases, assignments |
| **C** | `.c`, `.h` | Functions, structs, enums, typedefs, `#include`, macros |
| **C++** | `.cpp`, `.cc`, `.cxx`, `.hpp`, `.h`, `.hxx` | Functions, classes, structs, enums, type aliases, `#include`, macros |
| **PHP** | `.php` | Functions, methods, classes, interfaces, `use` / `include` / `require` |
| **Dart** | `.dart` | Functions, getters and setters, constructors, classes, mixins, extensions, imports |
| **Java** | `.java` | Methods, constructors, classes, records, annotation types, interfaces, enums, imports |
| **Kotlin** | `.kt`, `.kts` | Functions, classes, objects, interfaces, enums, type aliases, imports |

A language is skipped if its tree-sitter grammar is not installed.

### Frontend files

Markup and styles are indexed too, so the agent can connect components, selectors and the elements they apply to:

| Kind | Extensions |
|---|---|
| HTML | `.html`, `.htm` |
| CSS | `.css` |
| Vue single-file components | `.vue` |
| Svelte components | `.svelte` |
| JSX / TSX components | `.jsx`, `.tsx` |

Defaults can be overridden in `.raggie/frontend_config.json`:

```json
{
  "enabled_languages": ["html", "css", "javascript", "tsx", "vue", "svelte"],
  "generated_dir_exclusions": ["dist", "build", "node_modules", ".next", ".nuxt", "out"],
  "parse_inline_scripts": true,
  "parse_inline_styles": true,
  "include_text_nodes": false,
  "css_module_resolution": true,
  "generated_css_threshold": 100000,
  "max_frontend_file_size": 500000
}
```

## What is skipped

- Files matched by `.aiignore`, or `.gitignore` when there is no `.aiignore`. See [Configuration](configuration.md#gitignore-and-aiignore).
- Generated directories: `dist`, `build`, `node_modules`, `.next`, `.nuxt`, `out` (the `generated_dir_exclusions` list above).
- Directories named `test` or `tests`. Test code is left out of the index and the call graph. The agent can still read and edit those files with the file tools.

## Project detection

Before the terminal agent starts, Raggie checks for a `.raggie/` folder in the working directory.

| Situation | Result |
|---|---|
| `.raggie/` exists | Starts normally |
| No `.raggie/`, and the directory has no subdirectories | Starts normally. A flat directory is cheap to scan |
| No `.raggie/`, and the directory has subdirectories | Warns that this does not look like a Raggie project and asks whether to create one here. Declining exits with a hint to `cd` into your project |

This prevents scanning something huge by accident, for example when you run `raggie code .` in your home directory.

## Performance

Parsing runs in parallel worker processes with a sliding-window scheduler, and a dedicated writer thread does batched inserts. Dependencies are resolved in a pass after parsing.

**Benchmark: Linux kernel 7.1.1** (27,844,648 lines across 62,875 files)

| Phase | Time |
|---|---|
| File collection | ~4s |
| Changed-file detection | ~1.5s |
| Parse and insert (parallel) | ~521s |
| Dependency resolution | ~66s |
| **Total** | **~10m37s** |

Symbols indexed: 750K functions, 5.9M macros, 367K classes, 909K structs, 84K enums, 266K variables.

A typical project of a few hundred files indexes in seconds, and re-indexing after an edit only touches the changed files.

## Going deeper

[Indexer internals](indexer.md) documents the indexer modules, database schema, extraction pipeline and per-language handling.
