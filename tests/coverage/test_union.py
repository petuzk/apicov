from apicov.type_annotation import TypeCoverage


def one_arg(x: int | str) -> str:
    return str(x)


class TestOneArg:
    def test_one_arg(self, apicov):
        with apicov:
            one_arg(42)

        assert apicov.analyze(one_arg).total() == TypeCoverage(1, 2)


def two_args(x: int | str, y: float | None) -> str:
    return f"{x} {y}"


class TestTwoArgs:
    def test_two_args_partial_cov(self, apicov):
        with apicov:
            two_args(42, 3.14)

        assert apicov.analyze(two_args).total() == TypeCoverage(1, 4)

    def test_two_args_full_cov(self, apicov):
        with apicov:
            two_args(42, 3.14)
            two_args(42, None)
            two_args("42", None)

        # even though there was no call with (str, float), both str and float are covered by other calls
        assert apicov.analyze(two_args).total() == TypeCoverage(4, 4)
