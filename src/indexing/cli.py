"""
CLI argument parsing for the code indexer.
"""

import argparse
from indexing.language_config import LANGUAGE_CONFIG, is_language_available


FRONTEND_LANGUAGES = ["html", "css", "tsx", "javascript"]


def create_argument_parser():
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="Code Indexer - Index source code files using tree-sitter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported languages:
  python, go, csharp, javascript, typescript, rust, zig, elixir, cpp
  Frontend: html, css, tsx (jsx via javascript)

Examples:
  python code_indexer.py .                          # Index all supported languages
  python code_indexer.py . -l python,go             # Index only Python and Go files
  python code_indexer.py . -o my_index.json        # Save to custom output file
  python code_indexer.py . --frontend               # Enable frontend indexing
  python code_indexer.py . --no-frontend            # Disable frontend indexing
  python code_indexer.py --list-frontend-languages   # List frontend languages
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
        "--list-frontend-languages",
        action="store_true",
        help="List supported frontend languages and exit"
    )
    
    frontend_group = parser.add_mutually_exclusive_group()
    frontend_group.add_argument(
        "--frontend",
        action="store_true",
        default=True,
        help="Enable frontend indexing (HTML, CSS, JSX/TSX) (default: enabled)"
    )
    frontend_group.add_argument(
        "--no-frontend",
        action="store_false",
        dest="frontend",
        help="Disable frontend indexing"
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
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed timing and progress information"
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


def list_frontend_languages():
    """Print supported frontend languages and their status."""
    print("Supported frontend languages:")
    for lang in FRONTEND_LANGUAGES:
        if lang in LANGUAGE_CONFIG:
            config = LANGUAGE_CONFIG[lang]
            status = "ok" if is_language_available(lang) else "disabled (not installed)"
            print(f"  {lang:12} {status}")
            print(f"    Extensions: {', '.join(config['extensions'])}")
        else:
            print(f"  {lang:12} not configured")
