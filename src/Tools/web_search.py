from .utils import BLUE, RESET


DEFAULT_MAX_RESULTS = 5
MAX_RESULTS_CAP = 20


def handle(arguments, toolcall_id):
    query = arguments.get("query")
    print(f"{BLUE}WebSearch {query}{RESET}")

    if not query or not str(query).strip():
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'query' is required",
        }

    max_results = arguments.get("max_results", DEFAULT_MAX_RESULTS)
    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = DEFAULT_MAX_RESULTS
    max_results = max(1, min(max_results, MAX_RESULTS_CAP))

    region = arguments.get("region") or "wt-wt"

    try:
        from ddgs import DDGS
    except ImportError:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: the 'ddgs' package is not installed. Run: pip install ddgs",
        }

    try:
        results = DDGS().text(query, region=region, max_results=max_results)
    except Exception as err:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error performing web search: {err}",
        }

    if not results:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"No results found for '{query}'.",
        }

    lines = [f"Search results for '{query}':", ""]
    for i, item in enumerate(results, start=1):
        title = (item.get("title") or "").strip()
        href = (item.get("href") or "").strip()
        body = (item.get("body") or "").strip()
        lines.append(f"{i}. {title}")
        if href:
            lines.append(f"   URL: {href}")
        if body:
            lines.append(f"   {body}")
        lines.append("")

    return {
        "role": "tool",
        "tool_call_id": toolcall_id,
        "content": "\n".join(lines).strip(),
    }
