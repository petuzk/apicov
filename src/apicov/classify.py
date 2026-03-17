from typing import Any


def classify(value: Any) -> str:
    """Classify a runtime value into a string representing its type.

    This is a best effort heuristic, which may not be accurate for all types of values.
    The primary use case is to provide a readable type annotation for arbitrary runtime values.
    """
    if value is None:
        return "None"
    return type(value).__qualname__
