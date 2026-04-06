from typing import overload

from apicov.type_annotation import TypeCoverage


def ov(a: int) -> str: ...


ov1 = ov
overload(ov)  # apply decorator


def ov(a: int, b: float) -> str: ...


ov2 = ov
overload(ov)


def ov(a, b=None):
    return "foo"


class TestOverloadMatching:
    def test_specific_overload_first(self, apicov):
        """Second overload must be selected whenever `b` is passed, even though `a` will match both."""

        with apicov:
            ov(1, 4.2)

        assert apicov.analyze(ov, ov1).total() == TypeCoverage(0, 1)
        assert apicov.analyze(ov, ov2).total() == TypeCoverage(1, 1)

    def test_no_overload_matches(self, apicov):
        with apicov:
            ov(None)

        assert apicov.analyze(ov, ov1).total() == TypeCoverage(0, 1)
        assert apicov.analyze(ov, ov2).total() == TypeCoverage(0, 1)
