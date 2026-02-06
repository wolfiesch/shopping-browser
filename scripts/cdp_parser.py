"""
CDP Response Parser — Unified parser for nodriver's page.evaluate() responses.

nodriver returns CDP values as list-of-tuples: [(key, {type, value}), ...]
This module converts them to plain Python dicts/lists/scalars.
"""


def parse_cdp_response(data) -> dict:
    """Convert nodriver's evaluate() response to a plain Python dict.

    Handles both the tuple-list format (current nodriver) and plain dicts
    (future-proofing for when nodriver may change).
    """
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        return {"value": data}
    if not isinstance(data, (list, tuple)):
        return {"value": data}

    # Check if it's a list of tuples [(key, descriptor), ...]
    # vs a raw CDP array value
    result = {}
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            key, descriptor = item
            if isinstance(key, str) and isinstance(descriptor, dict):
                result[key] = _parse_value(descriptor)
            else:
                # Not a key-descriptor pair, treat as array
                return [_parse_value(i) if isinstance(i, dict) else i for i in data]
        else:
            # Not tuple pairs, treat as array
            return [_parse_value(i) if isinstance(i, dict) else i for i in data]
    return result


def _parse_value(raw):
    """Recursively parse a CDP value descriptor.

    CDP value descriptors have a 'type' field indicating the JS type:
      - null/undefined → None
      - boolean → True/False
      - number → int/float
      - string → str
      - array → list (recursive)
      - object → dict (recursive)
    """
    if not isinstance(raw, dict):
        return raw

    t = raw.get("type")

    if t in ("null", "undefined"):
        return None

    if t == "boolean":
        return raw.get("value", False)

    if t in ("number", "string"):
        return raw.get("value")

    if t == "array":
        items = raw.get("value", [])
        return [_parse_value(v) for v in items]

    if t == "object":
        props = raw.get("value", [])
        if isinstance(props, list):
            obj = {}
            for prop in props:
                if isinstance(prop, (list, tuple)) and len(prop) == 2:
                    obj[prop[0]] = _parse_value(prop[1])
            return obj
        return props

    # Fallback: return value directly if present, else the whole descriptor
    return raw.get("value", raw)
