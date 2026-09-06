"""Immutable attribute lookup boundary."""
MISSING = object()
def lookup_attribute(record, path):
    cur = record
    for key in path:
        if isinstance(cur, dict):
            if key not in cur: return MISSING
            cur = cur[key]
        else:
            if not hasattr(cur, key): return MISSING
            cur = getattr(cur, key)
    return cur
