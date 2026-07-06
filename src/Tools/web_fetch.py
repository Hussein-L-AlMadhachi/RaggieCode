import re
import gzip
import zlib
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .utils import BLUE, RED, RESET


DEFAULT_MAX_CHARS = 20000
DEFAULT_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; RaggieBot/1.0; +https://github.com/myuser/raggie)"

_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "main", "br",
    "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "ul", "ol", "table",
    "blockquote", "pre", "hr", "figure", "figcaption", "nav",
}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}


class _TextExtractor(HTMLParser):
    """Convert HTML into readable plain text using only the stdlib.

    Drops script/style/etc., inserts newlines around block-level elements,
    and collapses runs of whitespace.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def get_text(self):
        text = "".join(self._parts)
        # Collapse horizontal whitespace, then squeeze blank lines.
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _decode_body(raw, headers):
    """Decompress (if needed) and decode the response body to str."""
    encoding = (headers.get("Content-Encoding") or "").lower()
    if "gzip" in encoding:
        try:
            raw = gzip.decompress(raw)
        except OSError as e:
            print(f"{RED}Warning: Failed to decompress gzip response: {e}{RESET}")
    elif "deflate" in encoding:
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)

    charset = "utf-8"
    content_type = headers.get("Content-Type", "")
    match = re.search(r"charset=([\w\-]+)", content_type, re.IGNORECASE)
    if match:
        charset = match.group(1)
    try:
        return raw.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return raw.decode("utf-8", errors="replace")


def handle(arguments, toolcall_id):
    url = arguments.get("url")
    print(f"{BLUE}WebFetch {url}{RESET}")

    if not url:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: 'url' is required",
        }

    if not re.match(r"^https?://", url, re.IGNORECASE):
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": "Error: url must start with http:// or https://",
        }

    max_chars = arguments.get("max_chars", DEFAULT_MAX_CHARS)
    try:
        max_chars = int(max_chars)
    except (TypeError, ValueError):
        max_chars = DEFAULT_MAX_CHARS

    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
            "Accept-Encoding": "gzip, deflate",
        },
    )

    try:
        with urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            headers = resp.headers
            raw = resp.read()
            final_url = resp.geturl()
    except HTTPError as err:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error: HTTP {err.code} {err.reason} for {url}",
        }
    except URLError as err:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error: failed to fetch {url}: {err.reason}",
        }
    except Exception as err:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error fetching {url}: {err}",
        }

    content_type = (headers.get("Content-Type") or "").lower()

    if "html" in content_type:
        body = _decode_body(raw, headers)
        parser = _TextExtractor()
        try:
            parser.feed(body)
            text = parser.get_text()
        except Exception:
            text = body
    elif content_type.startswith("text/") or "json" in content_type or "xml" in content_type:
        text = _decode_body(raw, headers)
    else:
        return {
            "role": "tool",
            "tool_call_id": toolcall_id,
            "content": f"Error: unsupported content type '{content_type}' for {url} ({len(raw)} bytes). Only text/HTML/JSON/XML are supported.",
        }

    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True

    header = f"URL: {final_url}\nContent-Type: {content_type or 'unknown'}\n"
    if truncated:
        header += f"[truncated to {max_chars} chars]\n"
    header += "\n"

    return {
        "role": "tool",
        "tool_call_id": toolcall_id,
        "content": header + text,
    }
