from typing import Literal

from apicov.type_annotation import TypeCoverage


def one_arg(x: Literal["foo", "bar"]) -> None:
    pass


class TestOneArg:
    def test_one_arg(self, apicov):
        with apicov:
            one_arg("foo")

        assert apicov.analyze(one_arg).total() == TypeCoverage(1, 2)


def two_args(x: Literal["foo", "bar"], y: Literal[1, 2, 3]) -> None:
    pass


class TestTwoArgs:
    def test_two_args_partial_cov(self, apicov):
        with apicov:
            two_args("foo", 1)
            two_args("foo", 2)

        assert apicov.analyze(two_args).total() == TypeCoverage(2, 6)

    def test_two_args_full_cov(self, apicov):
        with apicov:
            two_args("foo", 1)
            two_args("foo", 2)
            two_args("bar", 3)

        assert apicov.analyze(two_args).total() == TypeCoverage(6, 6)
