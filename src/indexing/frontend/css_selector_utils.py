#!/usr/bin/env python3
"""
Lightweight CSS selector matching for runtime element resolution.

This is NOT a full CSS engine. It handles the common selector types that
appear in real-world stylesheets:

- Type selectors: ``div``, ``button``, ``span``
- Class selectors: ``.btn``, ``.container.primary``
- ID selectors: ``#submit-btn``
- Compound selectors: ``div.btn``, ``button#save.active``
- Descendant combinators: ``.parent .child``
- Child combinators: ``.parent > .child``

Pseudo-classes, pseudo-elements, attribute selectors, and sibling
combinators are not supported and will cause the matcher to return
``False`` (safe fallback — the caller simply gets no match from this
strategy).
"""

import re
from typing import List, Optional, Tuple


def _parse_compound_selector(sel: str) -> Optional[dict]:
    """Parse a single compound selector (no combinators).

    Returns a dict with keys: ``tag`` (str|None), ``id`` (str|None),
    ``classes`` (list[str]), or ``None`` if the selector is unsupported.
    """
    sel = sel.strip()
    if not sel:
        return None

    tag = None
    elem_id = None
    classes: List[str] = []

    # Tokenize: tag at start, then .class / #id
    pos = 0

    # Optional tag at the beginning
    m = re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*', sel)
    if m:
        tag = m.group(0).lower()
        pos = m.end()

    # Parse .class and #id tokens
    while pos < len(sel):
        if sel[pos] == '.':
            m = re.match(r'\.([a-zA-Z_][a-zA-Z0-9_-]*)', sel[pos:])
            if not m:
                return None  # malformed
            classes.append(m.group(1))
            pos += m.end()
        elif sel[pos] == '#':
            m = re.match(r'#([a-zA-Z_][a-zA-Z0-9_-]*)', sel[pos:])
            if not m:
                return None
            elem_id = m.group(1)
            pos += m.end()
        elif sel[pos] == '*':
            # Universal selector — matches any tag
            tag = '*'
            pos += 1
        else:
            # Unsupported syntax (pseudo, attribute, etc.)
            return None

    return {"tag": tag, "id": elem_id, "classes": classes}


def _split_by_combinator(selector: str) -> Optional[List[Tuple[str, str]]]:
    """Split a selector into compound parts with combinators.

    Returns a list of (combinator, compound) pairs. The first element
    has combinator ``""`` (empty string). Returns ``None`` if the
    selector contains unsupported combinators.
    """
    # Normalize whitespace
    selector = selector.strip()
    if not selector:
        return None

    # Split on > or whitespace, keeping the combinator
    # We tokenize: compound, then optional combinator (> or space), then compound, ...
    parts: List[Tuple[str, str]] = []
    current = ""
    i = 0
    while i < len(selector):
        ch = selector[i]
        if ch == '>':
            if current.strip():
                parts.append(("", current.strip()))
                current = ""
            parts.append((">", ""))
            i += 1
        elif ch == '~' or ch == '+':
            # Sibling combinators — unsupported
            return None
        elif ch.isspace():
            if current.strip():
                parts.append(("", current.strip()))
                current = ""
            # Skip whitespace, but mark a descendant combinator unless
            # the next non-space char is '>'
            j = i
            while j < len(selector) and selector[j].isspace():
                j += 1
            if j < len(selector) and selector[j] == '>':
                # The > will be handled in the next iteration
                i = j
            else:
                # Descendant combinator (whitespace)
                if parts and parts[-1][0] != ">":
                    parts.append((" ", ""))
                i = j
        else:
            current += ch
            i += 1

    if current.strip():
        parts.append(("", current.strip()))

    # Rebuild into (combinator, compound) pairs
    result: List[Tuple[str, str]] = []
    pending_combinator = ""
    for comb, compound in parts:
        if comb == ">" or comb == " ":
            pending_combinator = comb
        elif compound:
            result.append((pending_combinator, compound))
            pending_combinator = ""

    if not result:
        return None

    # First entry should have empty combinator
    result[0] = ("", result[0][1])
    return result


def _compound_matches(compound: dict, tag: str, classes: List[str],
                      elem_id: Optional[str]) -> bool:
    """Check if a parsed compound selector matches an element."""
    # Tag check
    if compound["tag"] is not None and compound["tag"] != "*":
        if tag.lower() != compound["tag"]:
            return False

    # ID check
    if compound["id"] is not None:
        if elem_id != compound["id"]:
            return False

    # Class check — all classes in the selector must be present on the element
    if compound["classes"]:
        elem_class_set = set(classes)
        for c in compound["classes"]:
            if c not in elem_class_set:
                return False

    return True


def selector_matches_element(selector: str, tag: str, classes: List[str],
                             elem_id: Optional[str] = None,
                             attributes: Optional[dict] = None) -> bool:
    """Check if a CSS selector matches an element.

    Args:
        selector: CSS selector text (e.g. ``.btn``, ``div#main``, ``.parent > .child``).
        tag: Element tag name.
        classes: List of class names on the element.
        elem_id: Element's id attribute value, if any.
        attributes: Element's attributes dict (unused currently, reserved for future).

    Returns:
        True if the selector matches the element, False otherwise.
        Unsupported selector syntax always returns False.
    """
    parts = _split_by_combinator(selector)
    if parts is None:
        return False

    # Parse all compound selectors
    parsed = []
    for comb, compound_text in parts:
        p = _parse_compound_selector(compound_text)
        if p is None:
            return False
        parsed.append((comb, p))

    if not parsed:
        return False

    # Single compound selector — direct match
    if len(parsed) == 1:
        return _compound_matches(parsed[0][1], tag, classes, elem_id)

    # Multi-part selector with combinators — we only check the final compound
    # against the element (we don't have the full DOM tree here).
    # For descendant/child combinators, we check if the last compound matches.
    # Full ancestry matching is done at the caller level where DOM ancestry is available.
    last_compound = parsed[-1][1]
    return _compound_matches(last_compound, tag, classes, elem_id)


def selectors_matching_element(selectors: List[str], tag: str,
                               classes: List[str],
                               elem_id: Optional[str] = None) -> List[str]:
    """Return only the selectors that match the given element.

    Args:
        selectors: List of CSS selector strings.
        tag: Element tag name.
        classes: List of class names on the element.
        elem_id: Element's id attribute value, if any.

    Returns:
        List of matching selector strings (subset of input).
    """
    return [
        s for s in selectors
        if selector_matches_element(s, tag, classes, elem_id)
    ]
