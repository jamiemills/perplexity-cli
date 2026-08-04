"""Pure ``ast`` signal extraction for the PEP 20 adherence analyser.

This module turns one source file into the pre-computed ``ModuleSignals``
contract consumed by ``_pep20_detectors``.  It performs no aphorism judgment
itself; it only extracts metrics, classifications and line-indexed
occurrences.

Complexity is counted with the zen rule: one plus every ``if``, ``for``,
``while``, ``try``, ``with``, ``assert``, every ``except`` handler, every
boolean operator branch and every comprehension.  Because it includes the
``try:`` keyword, this number differs from radon's (the repository's
canonical ``make complexity`` gate) by the count of ``try`` blocks.

A file that fails to parse is not an error: the ``SyntaxError`` message is
captured in ``ModuleSignals.parse_error`` and the CLI reports it as a
finding.  Comment detection is line-text based and does not resolve whether a
``#`` sits inside a string literal, which is an accepted heuristic.
"""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts._pep20_types import (
    DuplicateBlock,
    ExceptMetrics,
    FunctionMetrics,
    ModuleSignals,
)

__all__ = [
    "collect_module_signals",
    "comment_signals",
    "except_metrics",
    "function_metrics",
    "normalised_body_hash",
]

_LONG_LINE_LIMIT = 100
_MAGIC_NUMBER_EXCLUSIONS = {0, 1, -1}
_LOGGER_ATTRS = {"debug", "info", "warning", "error", "exception", "critical"}
_LOGGER_NAMES = {"logger", "logging"}
_EVAL_EXEC_NAMES = {"eval", "exec"}
_DYNAMIC_ATTR_NAMES = {"getattr", "setattr"}
_BROAD_EXCEPT_NAMES = {"Exception", "BaseException"}
_CONTROL_NODES = (ast.If, ast.For, ast.While, ast.Try, ast.With)
_NESTED_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_DEFERRED_MARKERS = ("TODO", "FIXME", "HACK")
_DUPLICATE_FLOOR = 2
_MIN_GETATTR_ARGS = 2
_FALLBACK_CHAIN_MIN = 3
_COMPOUND_RE = re.compile(
    r"^\s*(if|elif|else|for|while|with|try|except|finally|def|class)\b.*:\s*\S"
)

_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
_DocstringNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.Module


def _get_docstring(node: _DocstringNode) -> ast.Constant | None:
    """Return the docstring constant of *node*, or None."""
    if not node.body or not isinstance(node.body[0], ast.Expr):
        return None
    value = node.body[0].value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value
    return None


def _is_magic_value(value: object) -> bool:
    """True for a numeric magic value that is not a boolean."""
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float)) and value not in _MAGIC_NUMBER_EXCLUSIONS


def _iter_body_nodes(body: list[ast.stmt]) -> Iterable[ast.AST]:
    """Yield every node (recursively) reachable from a statement list."""
    for statement in body:
        yield from ast.walk(statement)


def _body_without_docstring(node: _FunctionNode) -> list[ast.stmt]:
    """Return *node*'s body with the leading docstring statement removed."""
    if _get_docstring(node) is not None:
        return node.body[1:]
    return node.body


def _canonical_token(node: ast.AST) -> str:
    """Render one AST node as an identifier-normalised token."""
    if isinstance(node, ast.Name):
        return "N"
    if isinstance(node, ast.arg):
        return "A"
    if isinstance(node, ast.Attribute):
        return "M"
    if isinstance(node, ast.Constant):
        return "0"
    return type(node).__name__


def _append_canonical(node: ast.AST, parts: list[str]) -> None:
    """Append a node's canonical form, skipping nested function bodies."""
    if isinstance(node, _NESTED_FUNCS):
        return
    parts.append(_canonical_token(node))
    for child in ast.iter_child_nodes(node):
        _append_canonical(child, parts)


def _canonical_body(body: list[ast.stmt]) -> str:
    """Render a body as an identifier-normalised canonical string."""
    parts: list[str] = []
    for statement in body:
        _append_canonical(statement, parts)
    return "".join(parts)


def _complexity_increment(node: ast.AST) -> int:
    """Return the complexity contribution of one AST node."""
    if isinstance(node, (_CONTROL_NODES, _COMPREHENSIONS, ast.ExceptHandler)):
        return 1
    if isinstance(node, ast.BoolOp):
        return len(node.values) - 1
    return 0


def _cyclomatic_complexity(node: ast.AST) -> int:
    """Return the zen cyclomatic complexity of a function subtree."""
    complexity = 1
    for child in ast.walk(node):
        complexity += _complexity_increment(child)
    return complexity


def _max_nesting(node: ast.AST, depth: int) -> int:
    """Return the deepest control nesting, resetting at nested functions.

    The initial call passes the function being measured with depth zero;
    control nodes deepen by one, while a nested function or lambda restarts
    from zero because its own nesting is measured separately.
    """
    best = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _NESTED_FUNCS):
            child_depth = _max_nesting(child, 0)
        elif isinstance(child, _CONTROL_NODES):
            child_depth = _max_nesting(child, depth + 1)
        else:
            child_depth = _max_nesting(child, depth)
        best = max(best, child_depth)
    return best


def _argument_count(node: _FunctionNode) -> int:
    """Return the number of positional and keyword-only arguments."""
    args = node.args
    return len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)


def _count_nodes(node: ast.AST, node_type: type[ast.AST]) -> int:
    """Count descendants of a given AST node type in a subtree."""
    return sum(1 for child in ast.walk(node) if isinstance(child, node_type))


def _statement_count(node: ast.AST) -> int:
    """Count every statement node in a function subtree."""
    return sum(1 for child in ast.walk(node) if isinstance(child, ast.stmt))


def function_metrics(node: _FunctionNode) -> FunctionMetrics:
    """Compute complexity, nesting, signature and documentation metrics.

    Args:
        node: A FunctionDef or AsyncFunctionDef node.

    Returns:
        A FunctionMetrics record for the function.
    """
    return FunctionMetrics(
        cc=_cyclomatic_complexity(node),
        nesting_depth=_max_nesting(node, 0),
        arg_count=_argument_count(node),
        return_count=_count_nodes(node, ast.Return),
        statement_count=_statement_count(node),
        has_docstring=_get_docstring(node) is not None,
        start_line=node.lineno,
        end_line=_end_line(node),
    )


def _end_line(node: _FunctionNode) -> int:
    """Return a function's end line, falling back to its start line."""
    if node.end_lineno is not None:
        return node.end_lineno
    return node.lineno


def _is_broad_exception(exception: ast.AST | None) -> bool:
    """True when an except clause names Exception or BaseException."""
    if not isinstance(exception, ast.Name):
        return False
    return exception.id in _BROAD_EXCEPT_NAMES


def _is_logger_call(node: ast.AST) -> bool:
    """True when a call targets a logger method or the logging module."""
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute):
        return node.func.attr in _LOGGER_ATTRS
    if isinstance(node.func, ast.Name):
        return node.func.id in _LOGGER_NAMES
    return False


def _has_logger_call(body: list[ast.stmt]) -> bool:
    """True when a body calls a logger method or the logging module."""
    return any(_is_logger_call(node) for node in _iter_body_nodes(body))


def _has_raise_from(body: list[ast.stmt]) -> bool:
    """True when a body raises an exception with a ``from`` clause."""
    for node in _iter_body_nodes(body):
        if isinstance(node, ast.Raise) and node.cause is not None:
            return True
    return False


def _has_raise(body: list[ast.stmt]) -> bool:
    """True when a body raises an exception."""
    return any(isinstance(node, ast.Raise) for node in _iter_body_nodes(body))


def _has_return(body: list[ast.stmt]) -> bool:
    """True when a body returns a value."""
    return any(isinstance(node, ast.Return) for node in _iter_body_nodes(body))


def _has_comment(handler: ast.ExceptHandler, source: str) -> bool:
    """True when the handler's source segment contains a comment."""
    segment = ast.get_source_segment(source, handler)
    return "#" in segment if segment else False


def _body_is_pass(body: list[ast.stmt]) -> bool:
    """True when a body is empty or consists solely of a pass statement."""
    return len(body) == 0 or (len(body) == 1 and isinstance(body[0], ast.Pass))


def _first_kind(checks: tuple[tuple[str, bool], ...], default: str) -> str:
    """Return the first kind whose predicate matched, else the default."""
    for kind, matched in checks:
        if matched:
            return kind
    return default


def _classify_body(body: list[ast.stmt], handler: ast.ExceptHandler, source: str) -> str:
    """Classify a non-bare handler body into its kind."""
    return _first_kind(
        (
            ("logged", _has_logger_call(body)),
            ("raise_from", _has_raise_from(body)),
            ("raise", _has_raise(body)),
            ("return", _has_return(body)),
            ("commented", _has_comment(handler, source)),
            ("pass", _body_is_pass(body)),
        ),
        default="silent",
    )


def _classify_kind(handler: ast.ExceptHandler, source: str) -> str:
    """Classify an except handler's type and body into a kind string."""
    if handler.type is None:
        return "bare"
    if _is_broad_exception(handler.type):
        return "broad"
    return _classify_body(handler.body, handler, source)


def except_metrics(handler: ast.ExceptHandler, source: str) -> ExceptMetrics:
    """Classify one except handler into a deterministic kind.

    Kinds are ``bare``, ``broad``, ``logged``, ``raise_from``, ``raise``,
    ``return``, ``commented``, ``pass`` and ``silent``.  A handler that merely
    carries a comment is ``commented`` (explicitly silenced) and takes
    priority over the ``pass`` or ``silent`` classifications.
    """
    return ExceptMetrics(kind=_classify_kind(handler, source), line=handler.lineno)


def normalised_body_hash(func: _FunctionNode) -> str | None:
    """Return an identifier-normalised hash of a function body, or None.

    Returns None for bodies with fewer than two statements so single-line
    helpers do not produce false duplicates.  Nested function bodies are
    excluded from the canonical form.
    """
    body = _body_without_docstring(func)
    if len(body) < _DUPLICATE_FLOOR:
        return None
    canonical = _canonical_body(body)
    return hashlib.md5(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


def _member_lines(members: list[_FunctionNode]) -> tuple[int, ...]:
    """Return the sorted starting lines of a duplicate-block's members."""
    return tuple(sorted(func.lineno for func in members))


def _duplicate_blocks(
    functions: list[_FunctionNode],
) -> tuple[DuplicateBlock, ...]:
    """Group functions by body hash and emit blocks shared by two or more."""
    by_hash: dict[str, list[_FunctionNode]] = {}
    for func in functions:
        body_hash = normalised_body_hash(func)
        if body_hash is not None:
            by_hash.setdefault(body_hash, []).append(func)
    blocks: list[DuplicateBlock] = []
    for body_hash, members in by_hash.items():
        if len(members) >= _DUPLICATE_FLOOR:
            blocks.append(DuplicateBlock(lines=_member_lines(members), body_hash=body_hash))
    return tuple(blocks)


def _is_stub_function(func: _FunctionNode) -> bool:
    """True when a function body is empty or consists solely of pass."""
    return _body_is_pass(func.body)


def _stub_function_lines(functions: list[_FunctionNode]) -> tuple[int, ...]:
    """Return the lines of functions whose body is only a pass statement."""
    return tuple(func.lineno for func in functions if _is_stub_function(func))


def _strip_comment(line: str) -> str:
    """Return *line* with any trailing comment removed (heuristic)."""
    index = line.find("#")
    return line[:index] if index != -1 else line


def _strip_indent(line: str) -> str:
    """Return *line*'s leading whitespace."""
    return line[: len(line) - len(line.lstrip())]


def _is_long_line(line: str) -> bool:
    """True when a line exceeds the limit and is not a URL-carrying line."""
    if "http://" in line or "https://" in line:
        return False
    return len(line) > _LONG_LINE_LIMIT


def _is_compound_line(line: str) -> bool:
    """True when a line holds two statements or a one-line suite."""
    code = _strip_comment(line).strip()
    if not code:
        return False
    if ";" in code:
        return True
    return bool(_COMPOUND_RE.match(code))


def _is_tab_mix(line: str) -> bool:
    """True when a line's indentation mixes tabs and spaces."""
    indent = _strip_indent(line)
    return "\t" in indent and " " in indent


def _count_comments(lines: list[str]) -> int:
    """Count comment-only lines."""
    return sum(1 for line in lines if line.strip().startswith("#"))


def _count_code(lines: list[str]) -> int:
    """Count non-blank lines that are not comments."""
    return sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))


def _find_long_lines(lines: list[str]) -> tuple[tuple[int, int], ...]:
    """Return (line, length) pairs for lines exceeding the length limit."""
    return tuple(
        (index, len(line)) for index, line in enumerate(lines, start=1) if _is_long_line(line)
    )


def _find_compound_lines(lines: list[str]) -> tuple[int, ...]:
    """Return the lines holding compound statements."""
    return tuple(index for index, line in enumerate(lines, start=1) if _is_compound_line(line))


def _find_tab_mix_lines(lines: list[str]) -> tuple[int, ...]:
    """Return the lines mixing tabs and spaces in their indentation."""
    return tuple(index for index, line in enumerate(lines, start=1) if _is_tab_mix(line))


@dataclass(frozen=True, slots=True)
class _TextSignals:
    """Line-level text metrics for one module."""

    comment_line_count: int
    code_line_count: int
    long_lines: tuple[tuple[int, int], ...]
    compound_statement_lines: tuple[int, ...]
    tab_mix_lines: tuple[int, ...]


def text_signals(lines: list[str]) -> _TextSignals:
    """Extract line-length, compound-statement, tab-mix and comment metrics."""
    return _TextSignals(
        comment_line_count=_count_comments(lines),
        code_line_count=_count_code(lines),
        long_lines=_find_long_lines(lines),
        compound_statement_lines=_find_compound_lines(lines),
        tab_mix_lines=_find_tab_mix_lines(lines),
    )


def _has_noqa(line: str) -> int:
    """Return one when a line carries a noqa directive."""
    return 1 if "# noqa" in line else 0


def _has_type_ignore(line: str) -> int:
    """Return one when a line carries a type-ignore directive."""
    return 1 if "# type: ignore" in line or "# pyright: ignore" in line else 0


def _has_deferred_marker(line: str) -> bool:
    """True when a line carries a deferred-work marker."""
    return any(marker in line for marker in _DEFERRED_MARKERS)


def comment_signals(lines: list[str]) -> tuple[int, int, list[int]]:
    """Count suppression directives and collect deferred-work markers.

    Returns:
        A tuple of (noqa count, type-ignore count, deferred marker lines).
    """
    noqa_count = 0
    type_ignore_count = 0
    todo_lines: list[int] = []
    for index, line in enumerate(lines, start=1):
        noqa_count += _has_noqa(line)
        type_ignore_count += _has_type_ignore(line)
        if _has_deferred_marker(line):
            todo_lines.append(index)
    return noqa_count, type_ignore_count, todo_lines


def _magic_number_lines(node: ast.Compare) -> list[tuple[int, object]]:
    """Return (line, value) pairs for magic numbers used in a comparison."""
    found: list[tuple[int, object]] = []
    for operand in (node.left, *node.comparators):
        if isinstance(operand, ast.Constant) and _is_magic_value(operand.value):
            found.append((node.lineno, operand.value))
    return found


def _has_continue(body: list[ast.stmt]) -> bool:
    """True when a body contains a continue statement."""
    return any(isinstance(node, ast.Continue) for node in _iter_body_nodes(body))


def _has_string_arg(args: list[ast.expr]) -> bool:
    """True when a call's second argument is a string constant."""
    if len(args) < _MIN_GETATTR_ARGS:
        return False
    return isinstance(args[1], ast.Constant) and isinstance(args[1].value, str)


class _Collector(ast.NodeVisitor):
    """One-pass collector of every line-indexed signal from a module."""

    def __init__(self) -> None:
        """Initialise the collector with empty signal lists."""
        self.functions: list[_FunctionNode] = []
        self.excepts: list[ast.ExceptHandler] = []
        self.wildcard_import_lines: list[int] = []
        self.global_statement_lines: list[int] = []
        self.getattr_lines: list[int] = []
        self.eval_exec_lines: list[int] = []
        self.magic_numbers: list[tuple[int, object]] = []
        self.function_import_lines: list[int] = []
        self.guess_continue_lines: list[int] = []
        self.fallback_chain_lines: list[int] = []
        self._function_depth = 0
        self._loop_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Record a function definition and descend with depth incremented."""
        self.functions.append(node)
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Record an async function definition and descend with depth incremented."""
        self.functions.append(node)
        self._function_depth += 1
        self.generic_visit(node)
        self._function_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        """Track loop depth so except-guess detection knows it is in a loop."""
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        """Track loop depth so except-guess detection knows it is in a loop."""
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_Import(self, node: ast.Import) -> None:
        """Record an import inside a function and descend."""
        if self._function_depth > 0:
            self.function_import_lines.append(node.lineno)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Record function-level and wildcard imports."""
        if self._function_depth > 0:
            self.function_import_lines.append(node.lineno)
        if any(alias.name == "*" for alias in node.names):
            self.wildcard_import_lines.append(node.lineno)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        """Record a global statement line."""
        self.global_statement_lines.append(node.lineno)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        """Record an except handler and a loop-level guessing continue."""
        self.excepts.append(node)
        if self._loop_depth > 0 and _has_continue(node.body):
            self.guess_continue_lines.append(node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Record dynamic attribute dispatch and eval/exec calls."""
        if isinstance(node.func, ast.Name):
            if node.func.id in _DYNAMIC_ATTR_NAMES and _has_string_arg(node.args):
                self.getattr_lines.append(node.lineno)
            elif node.func.id in _EVAL_EXEC_NAMES:
                self.eval_exec_lines.append(node.lineno)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        """Record magic numbers used as comparison operands."""
        self.magic_numbers.extend(_magic_number_lines(node))
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        """Record guessing fallback chains of three or more alternatives."""
        if isinstance(node.op, ast.Or) and len(node.values) >= _FALLBACK_CHAIN_MIN:
            self.fallback_chain_lines.append(node.lineno)
        self.generic_visit(node)


def _is_all_target(target: ast.expr | ast.Name) -> bool:
    """True when a target is the ``__all__`` name."""
    return isinstance(target, ast.Name) and target.id == "__all__"


def _declares_all(statement: ast.stmt) -> bool:
    """True when a statement assigns the ``__all__`` name."""
    if isinstance(statement, ast.Assign):
        return any(_is_all_target(target) for target in statement.targets)
    if isinstance(statement, ast.AnnAssign):
        return _is_all_target(statement.target)
    return False


def _has_all_export(tree: ast.Module) -> bool:
    """True when a module declares an ``__all__`` name."""
    return any(_declares_all(statement) for statement in tree.body)


def _build_function_metrics(nodes: list[_FunctionNode]) -> tuple[FunctionMetrics, ...]:
    """Build the metrics tuple for every function in a module."""
    return tuple(function_metrics(func) for func in nodes)


def _build_except_metrics(
    handlers: list[ast.ExceptHandler], source: str
) -> tuple[ExceptMetrics, ...]:
    """Build the metrics tuple for every except handler in a module."""
    return tuple(except_metrics(handler, source) for handler in handlers)


def _count_kind(items: tuple[ExceptMetrics, ...], kind: str) -> int:
    """Count handlers classified with a single kind."""
    return sum(1 for item in items if item.kind == kind)


def _count_kinds(items: tuple[ExceptMetrics, ...], kinds: tuple[str, ...]) -> int:
    """Count handlers classified with any of the given kinds."""
    return sum(1 for item in items if item.kind in kinds)


def collect_module_signals(source: str, rel_path: str) -> ModuleSignals:
    """Extract every signal from one source file into a ModuleSignals record.

    A syntax error does not raise: the parse message is stored in
    ``ModuleSignals.parse_error`` and all other signals default to zero.

    Args:
        source: The full text of the Python module.
        rel_path: Repository-relative path used as the finding location.

    Returns:
        The populated ModuleSignals contract for the module.
    """
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as exc:
        return ModuleSignals(module_path=rel_path, parse_error=str(exc.msg))

    collector = _Collector()
    collector.visit(tree)
    text = text_signals(source.splitlines())
    noqa_count, type_ignore_count, todo_lines = comment_signals(source.splitlines())

    functions = _build_function_metrics(collector.functions)
    excepts = _build_except_metrics(collector.excepts, source)

    return ModuleSignals(
        module_path=rel_path,
        functions=functions,
        excepts=excepts,
        duplicate_blocks=_duplicate_blocks(collector.functions),
        module_has_docstring=_get_docstring(tree) is not None,
        comment_line_count=text.comment_line_count,
        code_line_count=text.code_line_count,
        long_line_count=len(text.long_lines),
        long_lines=text.long_lines,
        compound_line_count=len(text.compound_statement_lines),
        compound_statement_lines=text.compound_statement_lines,
        tab_mix_count=len(text.tab_mix_lines),
        tab_mix_lines=text.tab_mix_lines,
        noqa_count=noqa_count,
        type_ignore_count=type_ignore_count,
        todo_count=len(todo_lines),
        todo_lines=tuple(todo_lines),
        wildcard_import_count=len(collector.wildcard_import_lines),
        wildcard_import_lines=tuple(collector.wildcard_import_lines),
        global_statement_lines=tuple(collector.global_statement_lines),
        getattr_count=len(collector.getattr_lines),
        getattr_lines=tuple(collector.getattr_lines),
        eval_exec_count=len(collector.eval_exec_lines),
        eval_exec_lines=tuple(collector.eval_exec_lines),
        magic_number_count=len(collector.magic_numbers),
        magic_numbers=tuple(collector.magic_numbers),
        function_import_lines=tuple(collector.function_import_lines),
        stub_function_lines=_stub_function_lines(collector.functions),
        guess_continue_lines=tuple(collector.guess_continue_lines),
        fallback_chain_lines=tuple(collector.fallback_chain_lines),
        bare_except_count=_count_kind(excepts, "bare"),
        silent_swallow_count=_count_kinds(excepts, ("pass", "silent")),
        has_all_in_init=(_has_all_export(tree) if rel_path.endswith("__init__.py") else False),
    )
