def process(value: str, *, strict: bool = False) -> str:
    result = value.strip()
    if strict and not result:
        raise ValueError("empty value is not allowed")
    return result
