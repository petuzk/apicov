import pytest

from apicov.classify import classify


@pytest.mark.parametrize(
    "value, annotation",
    [
        (42, "int"),
        ("hello", "str"),
        (None, "None"),
    ],
)
def test_type_annotation_match(value, annotation):
    assert classify(value) == annotation
