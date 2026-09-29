"""Small helpers shared by routes and templates."""


def inr(value) -> str:
    """Format a number as Indian Rupees with Indian digit grouping, e.g. 1234567 -> ₹12,34,567."""
    try:
        n = int(round(float(value or 0)))
    except (TypeError, ValueError):
        n = 0
    sign = "-" if n < 0 else ""
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return f"{sign}₹{s}"


def safe_next(url: str | None, default: str = "/dashboard") -> str:
    """Only allow same-site relative redirects (prevents open-redirect abuse)."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return default
