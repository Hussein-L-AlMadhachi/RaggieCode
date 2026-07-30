#!/usr/bin/env python3
"""
CSS semantic extractor.
Extracts selectors, custom properties, keyframes, imports, and var() usages from parsed CSS.
"""

import re
from typing import Dict, List, Optional, Tuple

from indexing.frontend.css_parser import (
    CSSDocument, ParsedRuleSet, ParsedSelector, ParsedDeclaration,
    ParsedKeyframes, parse_css,
)
from indexing.frontend.source_location import SourceLocation


# Pattern for var(--name) with optional fallback
VAR_PATTERN = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)")


def extract_css_semantics(source_bytes: bytes, config=None, file_path: str = "") -> dict:
    """Extract all semantic entities from a CSS file.

    Args:
        source_bytes: Raw CSS file content as bytes.
        config: Optional FrontendConfig instance for extraction limits.
        file_path: Optional file path for CSS module detection (.module.css).

    Returns:
        dict with keys:
            - style_selectors: list of selector dicts
            - style_custom_properties: list of custom property definition dicts
            - style_custom_property_usages: list of var() usage dicts
            - style_keyframes: list of keyframes dicts
            - style_imports: list of @import dicts
            - frontend_diagnostics: list of diagnostic dicts
            - media_queries: list of media query dicts with nested selector info
    """
    # Detect generated/minified CSS by size threshold — check BEFORE parsing
    # to avoid the expensive tree-sitter parse for files that will be skipped.
    threshold = config.generated_css_threshold if config else 100_000
    file_size = len(source_bytes)

    result = {
        "style_selectors": [],
        "style_custom_properties": [],
        "style_custom_property_usages": [],
        "style_keyframes": [],
        "style_imports": [],
        "frontend_diagnostics": [],
        "media_queries": [],
    }

    if file_size > threshold:
        result["frontend_diagnostics"].append({
            "diagnostic_type": "generated_file_skipped",
            "severity": "unsupported",
            "message": f"CSS file is {file_size} bytes (threshold: {threshold}), skipping full extraction as generated",
        })
        return result

    doc = parse_css(source_bytes)

    is_css_module = file_path.endswith(".module.css") if file_path else False

    # Detect minified CSS by high selector-to-line ratio
    line_count = source_bytes.count(b"\n") + 1
    all_rules = list(doc.rule_sets) + list(doc.media_rules)
    total_selectors = sum(len(r.selectors) for r in all_rules)
    if line_count > 0 and total_selectors > 0 and total_selectors / line_count > 10:
        result["frontend_diagnostics"].append({
            "diagnostic_type": "generated_file_skipped",
            "severity": "unsupported",
            "message": f"CSS appears minified ({total_selectors} selectors in {line_count} lines), skipping full extraction as generated",
        })
        return result

    for rule in all_rules:
        media_query = rule.media_query

        for sel in rule.selectors:
            sel_dict = {
                "selector_text": sel.text,
                "normalized_selector": _normalize_selector(sel.text),
                "selector_type": sel.selector_type,
                "source_range": sel.location.to_dict() if sel.location else None,
                "is_scoped": is_css_module or _is_scoped_selector(sel.text),
                "media_query": media_query,
            }
            result["style_selectors"].append(sel_dict)

        # Extract custom properties and var() usages from declarations
        for decl in rule.declarations:
            if decl.is_custom_property:
                scope = rule.selectors[0].text if rule.selectors else None
                result["style_custom_properties"].append({
                    "name": decl.property_name,
                    "value": decl.value,
                    "scope_selector": scope,
                    "source_range": decl.location.to_dict(),
                })

            # Extract var() usages from declaration values
            usages = _extract_var_usages(decl.value, decl.location)
            for u in usages:
                u["selector_text"] = rule.selectors[0].text if rule.selectors else None
                result["style_custom_property_usages"].append(u)

        # Record media query info
        if media_query:
            result["media_queries"].append({
                "query": media_query,
                "selector_count": len(rule.selectors),
                "source_range": rule.location.to_dict() if rule.location else None,
            })

    # Process keyframes
    for kf in doc.keyframes:
        kf_dict = {
            "name": kf.name,
            "source_range": kf.location.to_dict() if kf.location else None,
            "stops": [],
        }
        for stop in kf.keyframes:
            kf_dict["stops"].append({
                "stop": stop.stop,
                "declaration_count": len(stop.declarations),
            })
        result["style_keyframes"].append(kf_dict)

    # Process imports
    for imp in doc.imports:
        result["style_imports"].append({
            "import_path": imp.import_path,
            "is_external": imp.import_path.startswith(("http://", "https://", "//")),
            "is_url": imp.is_url,
            "source_range": imp.location.to_dict(),
        })

    # Diagnostics for parse errors
    for err in doc.errors:
        result["frontend_diagnostics"].append({
            "diagnostic_type": "malformed_css",
            "severity": "recoverable",
            "message": f"Parse error near: {err.get('text', '')[:50]}",
            "source_range": err.get("location"),
        })

    # Parser recovery: errors occurred but selectors were still extracted
    if doc.errors and len(result["style_selectors"]) > 0:
        result["frontend_diagnostics"].append({
            "diagnostic_type": "parser_recovery",
            "severity": "recoverable",
            "message": f"CSS parser recovered from {len(doc.errors)} error(s), extracted {len(result['style_selectors'])} selector(s)",
        })

    # Unresolved imports: @import with empty or missing path
    for imp in result["style_imports"]:
        if not imp["import_path"] and not imp["is_external"]:
            result["frontend_diagnostics"].append({
                "diagnostic_type": "unresolved_import",
                "severity": "unresolved",
                "message": "CSS @import has empty path",
                "source_range": imp.get("source_range"),
            })

    return result


def _normalize_selector(selector: str) -> str:
    """Normalize a CSS selector for comparison."""
    # Remove extra whitespace
    normalized = re.sub(r"\s+", " ", selector.strip())
    # Remove spaces around combinators
    normalized = re.sub(r"\s*([>+~])\s*", r"\1", normalized)
    return normalized


def _is_scoped_selector(selector: str) -> bool:
    """Check if a selector is scoped (e.g., CSS modules :global or :local)."""
    return ":global(" in selector or ":local(" in selector or selector.startswith(":local")


def _extract_var_usages(value: str, location: SourceLocation) -> list:
    """Extract var(--name) usages from a CSS value string."""
    usages = []
    for match in VAR_PATTERN.finditer(value):
        usage = {
            "property_name": match.group(1),
            "source_range": location.to_dict() if location else None,
        }
        if match.group(2):
            usage["fallback_value"] = match.group(2).strip()
        usages.append(usage)
    return usages
