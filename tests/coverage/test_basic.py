from typing import Never

import pytest

from apicov.type_annotation import TypeCoverage


def add(x: int, y: int) -> int:
    return int(x + y)  # explicit int for test_invalid_arg_type


class TestAdd:
    def test_add(self, apicov):
        with apicov:
            assert add(1, 2) == 3

        assert apicov.analyze(add).total() == TypeCoverage(1, 1)

    def test_invalid_arg_type(self, apicov):
        with apicov:
            assert add("2", "3") == 23

        # there was no call with (int, int), so expect zero coverage
        assert apicov.analyze(add).total() == TypeCoverage(0, 1)


def invalid_return_type(x: int) -> int:
    return str(x)


class TestInvalidReturnType:
    def test_invalid_return_type(self, apicov):
        with apicov:
            assert invalid_return_type(42) == "42"

        # return type was not covered, so expect zero coverage
        assert apicov.analyze(invalid_return_type).total() == TypeCoverage(0, 1)


def multireturn(x: int) -> int | str:
    return x if x else "zero"


class TestMultireturn:
    def test_multireturn_partial(self, apicov):
        with apicov:
            assert multireturn(42) == 42

        assert apicov.analyze(multireturn).total() == TypeCoverage(1, 2)

    def test_multireturn_full(self, apicov):
        with apicov:
            assert multireturn(42) == 42
            assert multireturn(0) == "zero"

        assert apicov.analyze(multireturn).total() == TypeCoverage(2, 2)


def raising(x: int) -> None:
    if x < 0:
        raise ValueError("x must be non-negative")


class TestRaising:
    def test_raises(self, apicov):
        with pytest.raises(ValueError), apicov:
            raising(-42)
            pytest.fail("raising() did not raise")

        # the function did not return, which means the return type was not covered
        assert apicov.analyze(raising).total() == TypeCoverage(0, 1)

    def test_returns(self, apicov):
        with pytest.raises(ValueError), apicov:
            raising(42)
            raising(-42)
            pytest.fail("raising() did not raise")

        # even though the second call raised an exception, the first call should give 100% coverage
        assert apicov.analyze(raising).total() == TypeCoverage(1, 1)


def never() -> Never:
    raise RuntimeError("this function never returns")


class TestNever:
    def test_never(self, apicov):
        with pytest.raises(RuntimeError), apicov:
            never()
            pytest.fail("never() did not raise")

        # the function did not return as indicated by the Never return type, so expect 100% coverage
        assert apicov.analyze(never).total() == TypeCoverage(1, 1)
