from typing import Optional, Union

import pytest

from apicov.type_annotation import SelfAnnotation, get_annotation


@pytest.mark.parametrize(
    "annotation, value, match_str",
    [
        (int, 42, "int"),
        (int, "hello", None),
        (str, "hello", "str"),
        (int | str, 42, "int"),
        (int | str, "hello", "str"),
        (Union[int, str], 42, "int"),  # noqa: UP007 (intentional usage of Union to test support)
        (Union[int, str], 3.14, None),  # noqa: UP007 (intentional usage of Union to test support)
        (None, None, "None"),
        (None, 42, None),
        (Optional[int], None, "None"),  # noqa: UP045 (intentional usage of Optional to test support)
        (Optional[int], 42, "int"),  # noqa: UP045 (intentional usage of Optional to test support)
    ],
)
def test_type_annotation_match(annotation, value, match_str):
    annot = get_annotation(annotation)
    match = annot.match(value)
    if match_str is None:
        assert match is None
    else:
        assert match is not None
        assert str(match) == match_str


def test_self_annotation_match():
    class Foo: ...

    class Bar(Foo): ...

    foo_annot = SelfAnnotation(Foo)
    assert foo_annot.match(Foo())
    assert foo_annot.match(Bar())
    assert not foo_annot.match(42)

    bar_annot = SelfAnnotation(Bar)
    assert not bar_annot.match(Foo())
    assert bar_annot.match(Bar())
    assert not bar_annot.match(42)
