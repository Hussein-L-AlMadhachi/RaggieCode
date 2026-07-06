"""
CLI argument parsing for the code indexer.
"""

import argparse
from indexing.language_config import LANGUAGE_CONFIG, is_language_available


def create_argument_parser():
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="Code Indexer - Index source code files using tree-sitter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported languages:
  python, go, csharp, javascript, typescript, rust, zig, elixir, cpp

Examples:
  python code_indexer.py .                          # Index all supported languages
  python code_indexer.py . -l python,go             # Index only Python and Go files
  python code_indexer.py . -o my_index.json        # Save to custom output file
        """
    )
    
    parser.add_argument(
        "directory",
        nargs='?',
        help="Directory to index (required for indexing mode)"
    )
    
    parser.add_argument(
        "-l", "--languages",
        help="Languages to index (comma-separated, default: all supported languages)"
    )
    
    parser.add_argument(
        "-o", "--output",
        default="code_index.db",
        help="Output SQLite database file (default: code_index.db)"
    )
    
    parser.add_argument(
        "--list-languages",
        action="store_true",
        help="List all supported languages and exit"
    )
    
    parser.add_argument(
        "--export-json",
        metavar="JSON_FILE",
        help="Export SQLite database to JSON file"
    )
    
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reindexing of all files, ignoring hash checks"
    )
    
    parser.add_argument(
        "--graph",
        metavar="FILE_PATH",
        help="View dependency graph for a specific file (relative path)"
    )
    
    return parser


def parse_arguments(args=None):
    """Parse command line arguments."""
    parser = create_argument_parser()
    return parser.parse_args(args)


def list_supported_languages():
    """Print all supported languages and their status."""
    print("Supported languages:")
    for lang in LANGUAGE_CONFIG.keys():
        config = LANGUAGE_CONFIG[lang]
        status = "ok" if is_language_available(lang) else "disabled (not installed)"
        print(f"  {lang:12} {status}")
        print(f"    Extensions: {', '.join(config['extensions'])}")
