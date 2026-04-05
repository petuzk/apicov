import pytest

from apicov.util import transpose_into_sets


class TestTranspose:
    def test_basic(self):
        assert transpose_into_sets([[1, 2], [1, 3]]) == [{1}, {2, 3}]
        assert transpose_into_sets([[1, 2], [1, 3], [1, 4]], n=2) == [{1}, {2, 3, 4}]

    def test_empty(self):
        assert transpose_into_sets([]) == []
        assert transpose_into_sets([], n=2) == [set(), set()]

    def test_invalid_length(self):
        with pytest.raises(ValueError, match="expected rows of length 3, got 2"):
            transpose_into_sets([[1, 2], [1, 3]], n=3)
