from collections.abc import Hashable, Iterable, Sequence


def transpose_into_sets[T: Hashable](rows: Iterable[Sequence[T]], n: int | None = None) -> list[set[T]]:
    """Transpose an iterable of sequences of the same length, grouping columns into sets."""
    transposed = list(map(set, zip(*rows)))
    if not transposed:
        return [set() for _ in range(n)] if n else []
    if n is not None and len(transposed) != n:
        raise ValueError(f"expected rows of length {n}, got {len(transposed)}")
    return transposed
