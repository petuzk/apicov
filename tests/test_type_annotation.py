from typing import Any, Literal, Never, NoReturn, Optional, Tuple, Union  # noqa: UP035 (intentional usage of Tuple)

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
        (Union[int, Union[str, None]], None, "None"),  # noqa: UP007 (intentional usage of Union to test support)
        (type(None), None, "None"),
        (None, None, "None"),
        (None, 42, None),
        (Optional[int], None, "None"),  # noqa: UP045 (intentional usage of Optional to test support)
        (Optional[int], 42, "int"),  # noqa: UP045 (intentional usage of Optional to test support)
        (Any, 42, "Any"),
        (Never, 42, None),
        (NoReturn, 42, None),
        (Literal["foo", "bar"], "bar", "Literal['bar']"),
        (Literal[Literal[Literal[1, 2, 3], "foo"], 5, None], 2, "Literal[2]"),  # noqa: RUF041 (intentionally nested)
        (tuple[()], (), "tuple[()]"),
        (tuple[()], [], None),
        (tuple[int | str], (42,), "tuple[int]"),
        (tuple[int, str | None], (42,), None),
        (tuple[int, str | None], (42, "foo"), "tuple[int, str]"),
        (Tuple[int, str | None], (42, None), "tuple[int, None]"),  # noqa: UP006 (intentional usage of Tuple)
        (Tuple[int, str | None], (42, None, "foo"), None),  # noqa: UP006 (intentional usage of Tuple)
        (list[int], [], None),  # typing semantics exception
        (list[int], [1, 2, 3], "list[int]"),
        (list[int], (1, 2, 3), None),
        (list[int], ["foo"], None),
        (list[int | str], ["foo", 42], "list[int | str]"),
        (list[Literal["foo", "bar"]], ["foo", "bar"], "list[Literal['foo', 'bar']]"),
        (tuple[int, ...], (), None),  # typing semantics exception
        (tuple[int, ...], (42, 43, 44), "tuple[int, ...]"),
        (tuple[int | str, ...], (42, 43, 44), "tuple[int, ...]"),
        (Tuple[int | str, ...], ("foo", "bar"), "tuple[str, ...]"),  # noqa: UP006 (intentional usage of Tuple)
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
