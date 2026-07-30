#!/usr/bin/env python3
"""
Source location utilities for frontend extractors.
Converts tree-sitter byte offsets to 1-indexed line/column positions.
"""

from typing import Dict, Optional


class SourceLocation:
    """Represents a source range with 1-indexed line/column positions."""

    __slots__ = ("start_line", "start_column", "end_line", "end_column", "start_byte", "end_byte")

    def __init__(self, start_line, start_column, end_line, end_column, start_byte=None, end_byte=None):
        self.start_line = start_line
        self.start_column = start_column
        self.end_line = end_line
        self.end_column = end_column
        self.start_byte = start_byte
        self.end_byte = end_byte

    def to_dict(self) -> Dict:
        d = {
            "start_line": self.start_line,
            "start_column": self.start_column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }
        if self.start_byte is not None:
            d["start_byte"] = self.start_byte
        if self.end_byte is not None:
            d["end_byte"] = self.end_byte
        return d

    def __repr__(self):
        return f"SourceLocation({self.start_line}:{self.start_column}-{self.end_line}:{self.end_column})"


def node_to_location(node) -> SourceLocation:
    """Convert a tree-sitter node to a SourceLocation with 1-indexed lines."""
    start_line, start_col = node.start_point
    end_line, end_col = node.end_point
    return SourceLocation(
        start_line=start_line + 1,
        start_column=start_col,
        end_line=end_line + 1,
        end_column=end_col,
        start_byte=node.start_byte,
        end_byte=node.end_byte,
    )


def byte_to_line_col(byte_offset: int, source_bytes: bytes) -> tuple:
    """Convert a byte offset to (line, column) with 1-indexed line."""
    line = 1
    col = 0
    for i in range(min(byte_offset, len(source_bytes))):
        if source_bytes[i] == 0x0A:  # newline
            line += 1
            col = 0
        else:
            col += 1
    return (line, col)


def extract_range(source_bytes: bytes, start_byte: int, end_byte: int) -> str:
    """Extract exact source text from byte range, handling UTF-8."""
    return source_bytes[start_byte:end_byte].decode("utf-8", errors="replace")
