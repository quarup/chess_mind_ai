"""Static AST validator for LLM-generated scorer code.

See plan.md section 6.1 for the full rationale. This is a deny-list of
syntactic constructs and identifier references that are obvious escape
hatches; it is NOT a substitute for the runtime sandbox (M4). It catches
the most common ways an LLM would accidentally (or maliciously) reach
outside the SafeChessContext API.
"""
from __future__ import annotations

import ast

REQUIRED_FUNCTION_NAMES: frozenset[str] = frozenset({
    "action_score",
    "state_score",
    "trajectory_score",
})

_BANNED_NODES: tuple[type[ast.AST], ...] = (
    ast.Import,
    ast.ImportFrom,
    ast.With,
    ast.AsyncWith,
    ast.AsyncFor,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
    ast.Global,
    ast.Nonlocal,
    ast.Try,
    ast.Raise,
    ast.Delete,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
)

_BANNED_CALL_NAMES: frozenset[str] = frozenset({
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "input",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "hasattr",
    "memoryview",
    "breakpoint",
})

_BANNED_ATTRIBUTE_NAMES: frozenset[str] = frozenset({
    "__class__",
    "__bases__",
    "__subclasses__",
    "__globals__",
    "__code__",
    "__closure__",
    "__dict__",
    "__mro__",
    "__getattribute__",
    "__init_subclass__",
    "__builtins__",
})


class ScorerValidationError(ValueError):
    """Raised when generated code violates the scorer safety rules."""


class _SafetyValidator(ast.NodeVisitor):
    def visit(self, node: ast.AST) -> None:
        if isinstance(node, _BANNED_NODES):
            raise ScorerValidationError(
                f"Banned syntax: {type(node).__name__}"
            )
        super().visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.decorator_list:
            raise ScorerValidationError("Decorators are not allowed")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in _BANNED_CALL_NAMES:
            raise ScorerValidationError(f"Banned call: {node.func.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _BANNED_ATTRIBUTE_NAMES or node.attr.startswith("__"):
            raise ScorerValidationError(f"Banned attribute access: {node.attr}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # Block bare-name uses too — `f = open; f("...")` would otherwise slip
        # past visit_Call. Allow these names if the model never *calls* them
        # via attribute / call expressions; that's caught above.
        if node.id in _BANNED_CALL_NAMES:
            raise ScorerValidationError(f"Banned name reference: {node.id}")
        self.generic_visit(node)


def validate_generated_code(source: str) -> ast.Module:
    """Parse `source` and reject it if it violates the scorer safety rules.

    Returns the parsed AST on success so the caller can reuse it for compile().
    Raises `ScorerValidationError` on any violation.
    """
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as e:
        raise ScorerValidationError(f"Generated code is not valid Python: {e}") from e

    _SafetyValidator().visit(tree)

    top_level_defs = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    missing = REQUIRED_FUNCTION_NAMES - top_level_defs
    if missing:
        raise ScorerValidationError(
            f"Generated code is missing required function(s): {sorted(missing)}"
        )
    unexpected = top_level_defs - REQUIRED_FUNCTION_NAMES
    if unexpected:
        raise ScorerValidationError(
            f"Generated code defines unexpected top-level function(s): {sorted(unexpected)}"
        )

    return tree
