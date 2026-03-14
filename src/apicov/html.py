from collections.abc import Iterable
from functools import reduce
from itertools import groupby
from operator import add
from typing import Any

from jinja2 import Environment, PackageLoader

from apicov.func_tracer import FuncTracer, Overload, OverloadCoverage
from apicov.type_annotation import NoAnnotation, TypeAnnotation, TypeCoverage, TypeMatch, UnionAnnotation


def generate_html_report(tracers: Iterable[FuncTracer]) -> Iterable[str]:
    """Generate HTML report presenting the data captured by provided tracers."""
    env = Environment(loader=PackageLoader("apicov"))
    template = env.get_template("coverage_report.html")

    render_data = get_render_data(tracers)

    # Render the template
    return template.generate(render_data)


def get_render_data(tracers: Iterable[FuncTracer]) -> dict[str, Any]:
    """Convert the data captured by provided tracers into a format expected by the report template."""
    # sort tracers by filename (for grouping) and line number (for correct ordering in report)
    sorted_tracers = sorted(
        tracers, key=lambda tr: (tr.original_func.__code__.co_filename, tr.original_func.__code__.co_firstlineno)
    )
    # group tracers by filename and generate report for each file
    by_filename = groupby(sorted_tracers, key=lambda tr: tr.original_func.__code__.co_filename)
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
        for parent_class in (None, *tr.original_func.__qualname__.split(".")[:-1]):
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
    func_name = tracer.original_func.__qualname__.rsplit(".", 1)[-1]
    converted = [
        {
            "kind": "function",
            "name": func_name,
            "lineno": overload.original_func.__code__.co_firstlineno,
            "signature": convert_signature(overload, ov_cov),
            "coverage": ov_cov.total(),  # add raw TypeCoverage, will be converted in generate_file_report
            "call_details": get_call_details(tracer.matched_calls[overload]),
        }
        for overload, ov_cov in tracer.analyze_coverage().items()
    ]

    unmatched_calls = [
        {"args": arg_repr, "result": f"{result_type}: {result_repr}"}
        for arg_repr, result_type, result_repr in tracer.unmatched_calls
    ]

    if unmatched_calls:
        # if there is only one overload, attach unmatched calls to it, otherwise create a separate entry
        if len(converted) == 1:
            converted[0]["call_details"]["unmatched_calls"] = unmatched_calls
        else:
            new_node = {
                "kind": "function",
                "name": func_name,
                "lineno": tracer.original_func.__code__.co_firstlineno,
                "signature": None,
                "coverage": None,
                "call_details": {"unmatched_calls": unmatched_calls},
            }
            converted.append(new_node)

    return converted


def get_call_details(calls: Iterable[tuple[tuple[TypeMatch, ...], TypeMatch | None, str | None]]) -> dict[str, Any]:
    """Convert signature's call details (parameters, return value, exception) into a format expected by template."""
    matched = []
    unmatched_ret = []
    exceptions = []
    for params, retval, exception in calls:
        converted_params = {"parameters": [str(p) for p in params]}
        if retval is not None:
            matched.append(converted_params | {"return_type": str(retval)})
        elif exception is not None:
            exceptions.append(converted_params | {"result": exception})
        else:
            # return value didn't match return annotation
            # TODO: show type and value repr
            unmatched_ret.append(converted_params | {"return_type": "?"})
    result = {"matched": matched, "unmatched_ret": unmatched_ret, "exceptions": exceptions}
    return {k: v for k, v in result.items() if v}


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


def convert_type_annotation(anno: TypeAnnotation, coverage: TypeCoverage) -> list[dict[str, Any]] | None:
    """Convert a type annotation (which may be a union, or NoAnnotation) into a format expected by template.

    Each type is represented as a list of union options, with coverage info for each option.
    If the annotation is not a union, the list will have only one element.
    If there is no annotation, None is returned.
    """
    if isinstance(anno, NoAnnotation):
        return None
    if isinstance(anno, UnionAnnotation):
        return [convert_single_type_annotation(opt, opt in coverage.covered_annotations) for opt in anno.options]
    return [convert_single_type_annotation(anno, coverage.hits == coverage.total)]


def convert_single_type_annotation(anno: TypeAnnotation, covered: bool) -> dict[str, Any]:
    """Convert a single (non-union) type annotation into a format expected by template."""
    return {
        "name": str(anno),
        "covered": covered,
        "args": None,  # TODO: generics are not supported in backend yet
    }


def convert_coverage(coverage: TypeCoverage) -> dict[str, Any]:
    """Convert coverage data into a format expected by template."""
    return {
        "hits": coverage.hits,
        "total": coverage.total,
        "ratio": coverage.ratio,
    }
