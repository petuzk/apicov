from collections.abc import Iterable
from functools import reduce
from itertools import groupby
from operator import add
from typing import Any

from jinja2 import Environment, PackageLoader

from apicov.func_tracer import FuncTracer, Overload, OverloadCoverage, UnmatchedException, UnmatchedValue
from apicov.type_annotation import (
    NoAnnotation,
    ParametrizedTypeAnnotation,
    ParametrizedTypeCoverage,
    TypeAnnotation,
    TypeCoverage,
    TypeMatch,
    UnionAnnotation,
    UnknownAnnotation,
)


def generate_html_report(tracers: Iterable[FuncTracer]) -> Iterable[str]:
    """Generate HTML report presenting the data captured by provided tracers."""
    env = Environment(loader=PackageLoader("apicov"), autoescape=True)
    template = env.get_template("coverage_report.html")

    render_data = get_render_data(tracers)

    # Render the template
    return template.generate(render_data)


def get_render_data(tracers: Iterable[FuncTracer]) -> dict[str, Any]:
    """Convert the data captured by provided tracers into a format expected by the report template."""
    # sort tracers by filename (for grouping) and line number (for correct ordering in report)
    sorted_tracers = sorted(tracers, key=lambda tr: (tr.filename, tr.lineno))
    # group tracers by filename and generate report for each file
    by_filename = groupby(sorted_tracers, key=lambda tr: tr.filename)
    files_data = ((filename, *generate_file_report(file_tracers)) for filename, file_tracers in by_filename)
    return {
        "files": [
            {
                "name": filename,
                "coverage": convert_coverage(file_coverage),
                "members": members,
            }
            for filename, file_coverage, members in files_data
        ],
    }


def generate_file_report(tracers: Iterable[FuncTracer]) -> tuple[TypeCoverage, list[dict[str, Any]]]:
    """Generate report data for a single source file, including coverage for the whole file and the member tree."""
    # use fictional root node to simplify processing
    classmap: dict[str | None, dict[str, Any]] = {None: {"members": []}}

    # iterate over tracers (sorted by line number) and build member tree based on their qualified name
    target: list[dict[str, Any]]
    for tr in tracers:
        for parent_class in (None, *tr.qualname.split(".")[:-1]):
            if parent_class not in classmap:
                new_node: dict[str, Any] = {"kind": "class", "name": parent_class, "members": []}
                # target is always defined because the first iteration does not satisfy the condition
                target.append(new_node)  # noqa: F821
                classmap[parent_class] = new_node
            target = classmap[parent_class]["members"]
        target.extend(process_tracer(tr))

    # calculate coverage for each node (including root) based on its members, and convert coverage objects into dicts
    # iterate in reverse order to ensure that child nodes are processed before their parents
    for node in reversed(classmap.values()):
        coverages = []
        for member in node.get("members", []):
            if (cov := member.get("coverage")) is not None:
                coverages.append(cov)
                member["coverage"] = convert_coverage(cov)
        node["coverage"] = reduce(add, coverages, TypeCoverage(0, 0))

    return classmap[None]["coverage"], classmap[None]["members"]


def process_tracer(tracer: FuncTracer) -> list[dict[str, Any]]:
    """Convert FuncTracer's overloads into a format suitable for rendering in the report."""
    func_name = tracer.qualname.rsplit(".", 1)[-1]
    converted = [
        {
            "kind": "function",
            "name": func_name,
            "lineno": overload.lineno,
            "signature": convert_signature(overload, ov_cov),
            "coverage": ov_cov.total(),  # add raw TypeCoverage, will be converted in generate_file_report
            "call_details": get_call_details(tracer.matched_calls[overload]),
        }
        for overload, ov_cov in tracer.analyze_coverage().items()
    ]

    unmatched_calls = [
        {"args": ", ".join(f"{name}: {arg}" for name, arg in unmatched_args)}
        | ({"return_type": str(result)} if isinstance(result, UnmatchedValue) else {"result": f"raised {result}"})
        for unmatched_args, result in tracer.unmatched_calls
    ]

    if unmatched_calls:
        # if there is only one overload, attach unmatched calls to it, otherwise create a separate entry
        if len(converted) == 1:
            converted[0]["call_details"]["unmatched_calls"] = unmatched_calls
        else:
            new_node = {
                "kind": "function",
                "name": func_name,
                "lineno": tracer.lineno,
                "signature": None,
                "coverage": None,
                "call_details": {"unmatched_calls": unmatched_calls},
            }
            converted.append(new_node)

    return converted


def get_call_details(
    calls: Iterable[tuple[tuple[TypeMatch, ...], TypeMatch | UnmatchedValue | UnmatchedException]],
) -> dict[str, Any]:
    """Convert signature's call details (parameters, return value, exception) into a format expected by template."""
    matched = []
    unmatched_ret = []
    exceptions = []
    for params, result in calls:
        converted_params = {"parameters": [str(p) for p in params]}
        if isinstance(result, TypeMatch):
            matched.append(converted_params | {"return_type": str(result)})
        elif isinstance(result, UnmatchedValue):
            unmatched_ret.append(converted_params | {"return_type": str(result)})
        elif isinstance(result, UnmatchedException):
            exceptions.append(converted_params | {"result": f"raised {result}"})
        else:
            raise TypeError(f"invalid result type: {type(result)}")
    result_dict = {"matched": matched, "unmatched_ret": unmatched_ret, "exceptions": exceptions}
    return {k: v for k, v in result_dict.items() if v}


def convert_signature(overload: Overload, coverage: OverloadCoverage) -> dict[str, Any]:
    """Convert an overload's signature and coverage data into a format expected by template."""
    return {
        "params": {
            param_name: convert_type_annotation(anno, cov)
            for param_name, anno, cov in zip(
                overload.signature.parameters, overload.param_annotations, coverage.param_coverages
            )
        },
        "ret": convert_type_annotation(overload.return_annotation, coverage.return_coverage),
    }


def convert_type_annotation(anno: TypeAnnotation | str, coverage: TypeCoverage | None) -> list[dict[str, Any]] | None:
    """Convert a type annotation into a format expected by template.

    Each type is represented as a list of union options, with coverage info for each option.
    If the annotation is not a union, the list will have only one element.
    If there is no annotation, None is returned.
    """
    if isinstance(anno, NoAnnotation):
        return None
    if isinstance(anno, UnionAnnotation):
        assert isinstance(coverage, ParametrizedTypeCoverage)
        return list(map(convert_single_type_annotation, anno.options, coverage.args_cov))
    if isinstance(anno, UnknownAnnotation):
        # display UnknownAnnotation as uncoverable
        coverage = None
    return [convert_single_type_annotation(anno, coverage)]


def convert_single_type_annotation(anno: TypeAnnotation | str, coverage: TypeCoverage | None) -> dict[str, Any]:
    """Convert a single (non-union) type annotation into a format expected by template."""
    cov_type = {"cov_type": get_cov_type(coverage)}
    match anno:
        case ParametrizedTypeAnnotation():
            return cov_type | {"name": anno.get_origin(), "args": get_type_args(anno, coverage)}
        case TypeAnnotation():
            return cov_type | {"name": anno.get_origin(), "args": None}
        case str(name):
            return cov_type | {"name": name, "args": None}
    raise TypeError(f"unexpected annotation: {anno!r}")


def get_cov_type(coverage: TypeCoverage | None) -> str:
    if coverage is None:
        return "uncoverable"
    if coverage.hits == coverage.total:
        return "cov-full"
    if not coverage.hits:
        return "cov-none"
    return "cov-partial"


def get_type_args(anno: ParametrizedTypeAnnotation, coverage: TypeCoverage | None) -> list[list[dict[str, Any]]]:
    # dealing with a parametrized type annotation, so expect parametrized coverage
    assert isinstance(coverage, ParametrizedTypeCoverage)
    return list(filter(None, map(convert_type_annotation, anno.get_args(), coverage.args_cov)))


def convert_coverage(coverage: TypeCoverage) -> dict[str, Any]:
    """Convert coverage data into a format expected by template."""
    return {
        "hits": coverage.hits,
        "total": coverage.total,
        "ratio": coverage.ratio,
    }
