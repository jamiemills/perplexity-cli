"""Pure completeness checks for Mutmut 3.5 generated source and results."""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import io
import tokenize
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal, TypeGuard

type ScopeKind = Literal["full", "selected"]
type DeclarationKind = Literal["abstract-method", "protocol-method"]

_CLASS_SEPARATOR = "ǁ"
_MUTANT_MARKER = "__mutmut_"
_MUTANT_DICTIONARY_SUFFIX = "__mutmut_mutants"
_PROTOCOL_BASES = frozenset({"typing.Protocol", "typing_extensions.Protocol"})
_ABSTRACT_DECORATORS = frozenset({"abc.abstractmethod"})


class GeneratedSourceError(ValueError):
    """Raised when generated Python cannot be parsed or identified."""


@dataclass(frozen=True, slots=True)
class MutationSelection:
    """Declared mutation scope and repeated Mutmut-compatible patterns."""

    scope: ScopeKind
    patterns: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate scope and pattern invariants."""
        _validate_selection(self.scope, self.patterns)


@dataclass(frozen=True, slots=True)
class GeneratedMutants:
    """Mutant definitions and dictionary mappings found in generated Python."""

    keys: tuple[str, ...]
    dictionary_keys: tuple[str, ...]
    dictionary_disagreements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceSummary:
    """Independent generated/result multiset comparison for one scope."""

    generated_count: int
    selected_count: int
    result_count: int
    missing_results: tuple[str, ...]
    extra_results: tuple[str, ...]
    duplicate_generated: tuple[str, ...]
    duplicate_results: tuple[str, ...]
    dictionary_disagreements: tuple[str, ...]
    structural_exclusion_disagreements: tuple[str, ...]
    complete: bool
    generated_digest: str
    result_digest: str


@dataclass(frozen=True, slots=True)
class EvidenceDisagreements:
    """Independent generated-dictionary and structural exclusion failures."""

    dictionary: tuple[str, ...] = ()
    structural_exclusions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """One source path and its exact text for structural validation."""

    path: str
    source: str


@dataclass(frozen=True, slots=True)
class StructuralExclusion:
    """One reviewed declaration carrying an exact no-mutate pragma."""

    source_path: str
    line: int
    declaration: str
    declaration_kind: DeclarationKind
    owner: str
    reason: str
    reviewer: str


@dataclass(frozen=True, slots=True)
class _PragmaDeclaration:
    source_path: str
    line: int
    declaration: str
    declaration_kind: DeclarationKind


_NO_DISAGREEMENTS = EvidenceDisagreements()


def normalise_generated_module(path: str | PurePath, source_root: str | PurePath = "src") -> str:
    """Convert a generated Python path to its importable module name.

    Args:
        path: Generated path relative to the mutation workspace, or absolute.
        source_root: Configured source root below ``mutants/``.

    Returns:
        Dotted module name, with package ``__init__.py`` normalised to the
        package itself.

    Raises:
        GeneratedSourceError: If the path is not a package Python path.
    """
    parts = _relative_generated_parts(PurePath(path), PurePath(source_root))
    if not parts or PurePath(parts[-1]).suffix != ".py":
        msg = f"generated source path is not Python: {path}"
        raise GeneratedSourceError(msg)
    parts[-1] = PurePath(parts[-1]).stem
    if parts[-1] == "__init__":
        parts.pop()
    if not _is_module_parts(parts):
        msg = f"generated source path is not a package module: {path}"
        raise GeneratedSourceError(msg)
    return ".".join(parts)


def _validate_selection(scope: ScopeKind, patterns: tuple[str, ...]) -> None:
    if _patterns_forbidden(scope, patterns):
        msg = "full scope cannot declare selected patterns"
        raise ValueError(msg)
    if _patterns_required(scope, patterns):
        msg = "selected scope requires at least one pattern"
        raise ValueError(msg)
    if any(not pattern for pattern in patterns):
        msg = "mutation patterns cannot be empty"
        raise ValueError(msg)


def _patterns_forbidden(scope: ScopeKind, patterns: tuple[str, ...]) -> bool:
    return scope == "full" and bool(patterns)


def _patterns_required(scope: ScopeKind, patterns: tuple[str, ...]) -> bool:
    return scope == "selected" and not patterns


def _relative_generated_parts(path: PurePath, source_root: PurePath) -> list[str]:
    parts = list(path.parts)
    if "mutants" in parts:
        parts = parts[parts.index("mutants") + 1 :]
    root_parts = list(source_root.parts)
    if parts[: len(root_parts)] == root_parts:
        return parts[len(root_parts) :]
    return parts


def _is_module_parts(parts: list[str]) -> bool:
    return bool(parts) and all(part.isidentifier() for part in parts)


def enumerate_generated_mutants(source: str, path: str | PurePath) -> GeneratedMutants:
    """Enumerate strict numeric Mutmut 3.5 definitions from generated Python.

    The definition walk intentionally covers only module functions and direct
    methods of module classes, matching Mutmut 3.5's generation arrangement.
    Originals, trampoline wrappers, aliases and malformed suffixes are not
    definitions. Annotated mutant dictionaries are parsed independently and
    compared as multisets.

    Args:
        source: Generated Python source text.
        path: Generated source path used to derive the module prefix.

    Returns:
        Definitions, dictionary keys and any dictionary disagreement details.

    Raises:
        GeneratedSourceError: If the generated Python is invalid.
    """
    module_name = normalise_generated_module(path)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        msg = f"invalid generated Python for {path}: {exc.msg}"
        raise GeneratedSourceError(msg) from exc
    definitions = _definition_names(tree)
    dictionary_keys, mapping_issues = _dictionary_names(tree)
    qualified_definitions = _qualify(module_name, definitions)
    qualified_dictionary = _qualify(module_name, dictionary_keys)
    disagreements = _dictionary_disagreements(
        qualified_definitions,
        qualified_dictionary,
        tuple(f"{module_name}: {issue}" for issue in mapping_issues),
    )
    return GeneratedMutants(
        keys=qualified_definitions,
        dictionary_keys=qualified_dictionary,
        dictionary_disagreements=disagreements,
    )


def compare_evidence(
    generated_keys: Iterable[str],
    result_keys: Iterable[str],
    selection: MutationSelection,
    disagreements: EvidenceDisagreements = _NO_DISAGREEMENTS,
) -> EvidenceSummary:
    """Compare generated and result key multisets after independent selection.

    Args:
        generated_keys: Keys independently enumerated from generated Python.
        result_keys: Keys parsed from raw Mutmut results.
        selection: Declared full or selected scope.
        disagreements: Generated dictionary and exclusion cross-check failures.

    Returns:
        Counts, differences, duplicates, digests and completeness.
    """
    all_generated = tuple(generated_keys)
    selected_generated = _apply_selection(all_generated, selection)
    selected_results = _apply_selection(tuple(result_keys), selection)
    generated_counter = Counter(selected_generated)
    result_counter = Counter(selected_results)
    missing = _expanded_difference(generated_counter, result_counter)
    extra = _expanded_difference(result_counter, generated_counter)
    duplicate_generated = _duplicates(generated_counter)
    duplicate_results = _duplicates(result_counter)
    dictionary_disagreements = tuple(sorted(disagreements.dictionary))
    exclusion_disagreements = tuple(sorted(disagreements.structural_exclusions))
    complete = bool(selected_generated) and not any(
        (
            missing,
            extra,
            duplicate_generated,
            duplicate_results,
            dictionary_disagreements,
            exclusion_disagreements,
        )
    )
    return EvidenceSummary(
        generated_count=len(all_generated),
        selected_count=len(selected_generated),
        result_count=len(selected_results),
        missing_results=missing,
        extra_results=extra,
        duplicate_generated=duplicate_generated,
        duplicate_results=duplicate_results,
        dictionary_disagreements=dictionary_disagreements,
        structural_exclusion_disagreements=exclusion_disagreements,
        complete=complete,
        generated_digest=digest_records(selected_generated),
        result_digest=digest_records(selected_results),
    )


def digest_records(records: Iterable[str]) -> str:
    """Return a path-independent SHA-256 digest of a string multiset.

    Args:
        records: String records whose ordering is irrelevant.

    Returns:
        Lower-case SHA-256 digest.
    """
    payload = "".join(f"{record}\n" for record in sorted(records))
    return hashlib.sha256(payload.encode()).hexdigest()


def matches_selection(key: str, selection: MutationSelection) -> bool:
    """Return whether a mutant key belongs to the declared scope.

    Args:
        key: Fully qualified mutant key.
        selection: Full or pattern-selected scope.

    Returns:
        Whether the key is selected.
    """
    if selection.scope == "full":
        return True
    return any(fnmatch.fnmatchcase(key, pattern) for pattern in selection.patterns)


def validate_structural_exclusions(
    sources: Iterable[SourceDocument], declared: Iterable[StructuralExclusion]
) -> tuple[str, ...]:
    """Validate exact, reviewed no-mutate declarations without file access.

    Args:
        sources: Source documents whose pragmas are authoritative.
        declared: Manifest records expected to match those pragmas exactly.

    Returns:
        Sorted disagreements. An empty tuple is the only valid outcome.
    """
    source_items = tuple(sources)
    declared_items = tuple(declared)
    found, source_issues = _source_pragmas(source_items)
    issues = [*source_issues, *_manifest_metadata_issues(declared_items)]
    found_counter = Counter(found)
    declared_counter = Counter(_manifest_identity(item) for item in declared_items)
    issues.extend(
        f"undeclared pragma: {_format_identity(item)}"
        for item in (found_counter - declared_counter)
    )
    issues.extend(
        f"stale manifest entry: {_format_identity(item)}"
        for item in (declared_counter - found_counter)
    )
    issues.extend(_duplicate_identity_issues(declared_counter))
    return tuple(sorted(issues))


def _source_pragmas(
    sources: tuple[SourceDocument, ...],
) -> tuple[tuple[tuple[str, int, str, str], ...], tuple[str, ...]]:
    found: list[tuple[str, int, str, str]] = []
    issues: list[str] = []
    for document in sources:
        declarations, document_issues = _document_pragmas(document)
        found.extend(_pragma_identity(item) for item in declarations)
        issues.extend(document_issues)
    return tuple(found), tuple(issues)


def _document_pragmas(
    document: SourceDocument,
) -> tuple[tuple[_PragmaDeclaration, ...], tuple[str, ...]]:
    try:
        tree = ast.parse(document.source)
        lines, non_canonical = _pragma_lines(document.source)
    except (SyntaxError, tokenize.TokenError) as exc:
        return (), (f"unparseable exclusion source: {document.path}: {type(exc).__name__}",)
    declarations = _eligible_declarations(tree, document.path)
    found: list[_PragmaDeclaration] = []
    issues = [f"non-canonical pragma: {document.path}:{line}" for line in non_canonical]
    for line in lines:
        declaration = declarations.get(line)
        if declaration is None:
            issues.append(f"ineligible pragma: {document.path}:{line}")
        else:
            found.append(declaration)
    return tuple(found), tuple(issues)


def _pragma_lines(source: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    recognised = tuple(filter(_is_recognised_pragma, tokens))
    exact, non_canonical = _partition_pragmas(recognised)
    return exact, non_canonical


def _partition_pragmas(
    tokens: tuple[tokenize.TokenInfo, ...],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    exact: list[int] = []
    non_canonical: list[int] = []
    for token in tokens:
        target = exact if _is_exact_pragma(token) else non_canonical
        target.append(token.start[0])
    return tuple(exact), tuple(non_canonical)


def _is_recognised_pragma(token: tokenize.TokenInfo) -> bool:
    if token.type != tokenize.COMMENT or "# pragma:" not in token.string:
        return False
    return "no mutate" in token.string.partition("# pragma:")[-1]


def _is_exact_pragma(token: tokenize.TokenInfo) -> bool:
    return token.string.strip() == "# pragma: no mutate"


def _eligible_declarations(tree: ast.Module, path: str) -> dict[int, _PragmaDeclaration]:
    declarations: dict[int, _PragmaDeclaration] = {}
    aliases: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.ClassDef):
            declarations.update(_class_declarations(statement, path, aliases))
        _update_aliases(aliases, statement)
    return declarations


def _class_declarations(
    node: ast.ClassDef, path: str, aliases: dict[str, str]
) -> dict[int, _PragmaDeclaration]:
    fallback_kind: DeclarationKind | None = (
        "protocol-method" if _is_protocol(node, aliases) else None
    )
    class_aliases = aliases.copy()
    declarations: dict[int, _PragmaDeclaration] = {}
    for member in node.body:
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = _declaration_kind(member, fallback_kind, class_aliases)
            declaration = _eligible_method(member, node.name, path, kind)
            if declaration is not None:
                declarations[declaration.line] = declaration
        _update_aliases(class_aliases, member)
    return declarations


def _is_protocol(node: ast.ClassDef, aliases: dict[str, str]) -> bool:
    return any(_resolved_qualified_name(base, aliases) in _PROTOCOL_BASES for base in node.bases)


def _eligible_method(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    class_name: str,
    path: str,
    kind: DeclarationKind | None,
) -> _PragmaDeclaration | None:
    if kind is None:
        return None
    if not _has_non_executable_body(node):
        return None
    return _PragmaDeclaration(path, node.lineno, f"{class_name}.{node.name}", kind)


def _declaration_kind(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    fallback_kind: DeclarationKind | None,
    aliases: dict[str, str],
) -> DeclarationKind | None:
    if any(
        _resolved_qualified_name(item, aliases) in _ABSTRACT_DECORATORS
        for item in node.decorator_list
    ):
        return "abstract-method"
    return fallback_kind


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_qualified_name(node.value)}.{node.attr}"
    return ""


def _resolved_qualified_name(node: ast.expr, aliases: dict[str, str]) -> str:
    name = _qualified_name(node)
    root, separator, remainder = name.partition(".")
    resolved_root = aliases.get(root, root)
    return f"{resolved_root}{separator}{remainder}"


def _update_aliases(aliases: dict[str, str], statement: ast.stmt) -> None:
    imported = _statement_aliases(statement)
    for name in _bound_names(statement):
        aliases.pop(name, None)
    aliases.update(imported)


def _bound_names(statement: ast.stmt) -> tuple[str, ...]:
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return tuple(_statement_aliases(statement))
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (statement.name,)
    return _stored_names(statement)


def _stored_names(statement: ast.stmt) -> tuple[str, ...]:
    collector = _BindingCollector()
    collector.visit(statement)
    return tuple(sorted(collector.names))


class _BindingCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    def visit_ListComp(self, node: ast.ListComp) -> None:
        del node

    def visit_SetComp(self, node: ast.SetComp) -> None:
        del node

    def visit_DictComp(self, node: ast.DictComp) -> None:
        del node

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        del node

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self.names.add(node.rest)
        self.generic_visit(node)


def _statement_aliases(statement: ast.stmt) -> dict[str, str]:
    if isinstance(statement, ast.Import):
        return _direct_import_aliases(statement)
    if isinstance(statement, ast.ImportFrom) and statement.module and statement.level == 0:
        return _from_import_aliases(statement)
    return {}


def _direct_import_aliases(statement: ast.Import) -> dict[str, str]:
    return {alias.asname or alias.name.partition(".")[0]: alias.name for alias in statement.names}


def _from_import_aliases(statement: ast.ImportFrom) -> dict[str, str]:
    return {
        alias.asname or alias.name: f"{statement.module}.{alias.name}" for alias in statement.names
    }


def _has_non_executable_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = _without_docstring(node.body)
    return len(body) == 1 and _is_empty_statement(body[0])


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if body and _is_string_expression(body[0]):
        return body[1:]
    return body


def _is_string_expression(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_empty_statement(node: ast.stmt) -> bool:
    if isinstance(node, ast.Pass):
        return True
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    )


def _manifest_metadata_issues(entries: tuple[StructuralExclusion, ...]) -> tuple[str, ...]:
    issues: list[str] = []
    for entry in entries:
        identity = _format_identity(_manifest_identity(entry))
        for field in ("owner", "reason", "reviewer"):
            if _is_placeholder(getattr(entry, field)):
                issues.append(f"invalid {field}: {identity}")
        if entry.owner.strip() == entry.reviewer.strip():
            issues.append(f"owner must differ from reviewer: {identity}")
    return tuple(issues)


def _is_placeholder(value: str) -> bool:
    return not value.strip() or value.strip().lower() in {"unknown", "tbd", "none", "n/a"}


def _manifest_identity(entry: StructuralExclusion) -> tuple[str, int, str, str]:
    return (entry.source_path, entry.line, entry.declaration, entry.declaration_kind)


def _pragma_identity(entry: _PragmaDeclaration) -> tuple[str, int, str, str]:
    return (entry.source_path, entry.line, entry.declaration, entry.declaration_kind)


def _format_identity(identity: tuple[str, int, str, str]) -> str:
    path, line, declaration, kind = identity
    return f"{path}:{line}:{declaration}:{kind}"


def _duplicate_identity_issues(counter: Counter[tuple[str, int, str, str]]) -> tuple[str, ...]:
    return tuple(
        f"duplicate manifest entry: {_format_identity(identity)}"
        for identity, count in counter.items()
        if count > 1
    )


def _definition_names(tree: ast.Module) -> tuple[str, ...]:
    names: list[str] = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_mutant_name(statement.name, class_name=None):
                names.append(statement.name)
        elif isinstance(statement, ast.ClassDef):
            names.extend(_class_definition_names(statement))
    return tuple(names)


def _class_definition_names(class_node: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for statement in class_node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_mutant_name(
            statement.name, class_name=class_node.name
        ):
            names.append(statement.name)
    return names


def _is_mutant_name(name: str, class_name: str | None) -> bool:
    stem, marker, suffix = name.rpartition(_MUTANT_MARKER)
    if not marker or not _is_positive_integer(suffix):
        return False
    if class_name is None:
        return _has_identifier_suffix(stem, "x_")
    prefix = f"x{_CLASS_SEPARATOR}{class_name}{_CLASS_SEPARATOR}"
    return _has_identifier_suffix(stem, prefix)


def _has_identifier_suffix(value: str, prefix: str) -> bool:
    return value.startswith(prefix) and value[len(prefix) :].isidentifier()


def _is_positive_integer(value: str) -> bool:
    return value.isascii() and value.isdigit() and value[0] != "0"


def _dictionary_names(tree: ast.Module) -> tuple[tuple[str, ...], tuple[str, ...]]:
    keys: list[str] = []
    issues: list[str] = []
    for statement in _module_and_class_statements(tree):
        if not isinstance(statement, ast.AnnAssign):
            continue
        if not isinstance(statement.target, ast.Name):
            continue
        if not statement.target.id.endswith(_MUTANT_DICTIONARY_SUFFIX):
            continue
        parsed_keys, parsed_issues = _parse_dictionary(statement.target.id, statement.value)
        keys.extend(parsed_keys)
        issues.extend(parsed_issues)
    return tuple(keys), tuple(issues)


def _module_and_class_statements(tree: ast.Module) -> Iterable[ast.stmt]:
    for statement in tree.body:
        yield statement
        if isinstance(statement, ast.ClassDef):
            yield from statement.body


def _parse_dictionary(name: str, value_node: ast.expr | None) -> tuple[list[str], list[str]]:
    if not isinstance(value_node, ast.Dict):
        return [], [f"{name}: mapping is not a dictionary"]
    keys: list[str] = []
    issues: list[str] = []
    for key_node, mapped_node in zip(value_node.keys, value_node.values, strict=True):
        key, issue = _parse_dictionary_item(name, key_node, mapped_node)
        if key is not None:
            keys.append(key)
        if issue is not None:
            issues.append(issue)
    return keys, issues


def _parse_dictionary_item(
    dictionary_name: str,
    key_node: ast.expr | None,
    mapped_node: ast.expr,
) -> tuple[str | None, str | None]:
    key = _string_constant(key_node)
    if not _valid_dictionary_key(key):
        return None, f"{dictionary_name}: malformed dictionary key"
    expected_stem = dictionary_name.removesuffix(_MUTANT_DICTIONARY_SUFFIX)
    key_stem = key.rpartition(_MUTANT_MARKER)[0]
    if key_stem != expected_stem:
        return key, f"{dictionary_name}: {key!r} belongs to a different mutant dictionary"
    mapped_name = mapped_node.id if isinstance(mapped_node, ast.Name) else None
    if mapped_name != key:
        return key, f"{dictionary_name}: {key!r} does not map to itself"
    return key, None


def _valid_dictionary_key(key: str | None) -> TypeGuard[str]:
    return key is not None and _is_any_mutant_name(key)


def _string_constant(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_any_mutant_name(name: str) -> bool:
    stem, marker, suffix = name.rpartition(_MUTANT_MARKER)
    if not marker or not _is_positive_integer(suffix):
        return False
    if stem.startswith("x_"):
        return stem[2:].isidentifier()
    return _is_class_mutant_stem(stem)


def _is_class_mutant_stem(stem: str) -> bool:
    parts = stem.split(_CLASS_SEPARATOR)
    expected_parts = 3
    return (
        len(parts) == expected_parts
        and parts[0] == "x"
        and all(part.isidentifier() for part in parts[1:])
    )


def _qualify(module_name: str, names: Iterable[str]) -> tuple[str, ...]:
    return tuple(f"{module_name}.{name}" for name in names)


def _dictionary_disagreements(
    definitions: tuple[str, ...],
    dictionary_keys: tuple[str, ...],
    mapping_issues: tuple[str, ...],
) -> tuple[str, ...]:
    definition_counter = Counter(definitions)
    dictionary_counter = Counter(dictionary_keys)
    missing = _expanded_difference(definition_counter, dictionary_counter)
    extra = _expanded_difference(dictionary_counter, definition_counter)
    disagreements = [*(f"missing dictionary key: {key}" for key in missing)]
    disagreements.extend(f"extra dictionary key: {key}" for key in extra)
    disagreements.extend(mapping_issues)
    return tuple(sorted(disagreements))


def _apply_selection(keys: tuple[str, ...], selection: MutationSelection) -> tuple[str, ...]:
    return tuple(key for key in keys if matches_selection(key, selection))


def _expanded_difference(left: Counter[str], right: Counter[str]) -> tuple[str, ...]:
    return tuple(sorted((left - right).keys()))


def _duplicates(counter: Counter[str]) -> tuple[str, ...]:
    return tuple(key for key, count in sorted(counter.items()) if count > 1)
