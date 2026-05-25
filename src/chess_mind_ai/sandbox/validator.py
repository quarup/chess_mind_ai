"""Static AST validator for LLM-generated scorer code.

This validator is an **allowlist**: only an explicitly-enumerated set of AST
node types is permitted, and anything else fails closed. That is a deliberate
change from the original denylist (which could only reject constructs we
thought to name, and therefore failed *open* on novel tricks). See
`docs/scorer-sandbox-design.md` for the full rationale.

Crucially, this in-process layer is **not** the real security boundary. Any
live Python object handed to generated code — including `SafeChessContext` —
is a gateway to the interpreter via the object graph (``x.__class__`` →
``__subclasses__`` → ``__globals__``), so the only thing standing between
generated code and an escape is whether the *syntax* needed to walk that graph
is expressible. A denylist over a Turing-complete language inevitably leaks
(e.g. the classic ``"{0.__class__...}".format(obj)`` trick smuggles dunders
inside a string literal where there is no ``ast.Attribute`` node to catch).
The allowlist plus the string-dunder guard below closes the holes we know of,
but the actual wall is the OS-level sandbox (separate process + resource
limits + dropped FS/network) that runs the scorer — see milestone M4.
"""
from __future__ import annotations

import ast

REQUIRED_FUNCTION_NAMES: frozenset[str] = frozenset({
    "action_score",
    "state_score",
    "trajectory_score",
})

# Only these AST node types may appear anywhere in generated scorer code.
# Anything else (Import, ClassDef, Lambda, With, Try, Raise, Global, Nonlocal,
# Delete, Yield, Await, async defs, walrus, f-strings, etc.) fails closed.
_ALLOWED_NODES: frozenset[type[ast.AST]] = frozenset({
    # module + function structure
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.keyword,
    # statements
    ast.Return,
    ast.Pass,
    ast.Assign,
    ast.AugAssign,
    ast.AnnAssign,
    ast.If,
    ast.For,
    ast.While,
    ast.Break,
    ast.Continue,
    ast.Expr,
    # expressions
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.Attribute,
    ast.Subscript,
    ast.Slice,
    ast.Name,
    ast.Constant,
    ast.Tuple,
    ast.List,
    ast.Dict,
    ast.Set,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.comprehension,
    # expression contexts
    ast.Load,
    ast.Store,
    # boolean / binary / unary / comparison operators
    ast.And,
    ast.Or,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Is,
    ast.IsNot,
    ast.In,
    ast.NotIn,
})

# Defence-in-depth on top of the node allowlist. These names are syntactically
# reachable (Name / Call / Attribute are allowed nodes) so we still reject them
# explicitly even though the runtime builtins are also restricted.
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
    "type",
    "super",
})

_BANNED_ATTRIBUTE_NAMES: frozenset[str] = frozenset({
    # str-formatting methods are the remaining attribute-based escape route
    # (a runtime-assembled format string can carry dunders past the
    # string-literal guard); no legitimate scorer needs them.
    "format",
    "format_map",
})


class ScorerValidationError(ValueError):
    """Raised when generated code violates the scorer safety rules."""


class _SafetyValidator(ast.NodeVisitor):
    def visit(self, node: ast.AST) -> None:
        if type(node) not in _ALLOWED_NODES:
            raise ScorerValidationError(
                f"Disallowed syntax: {type(node).__name__}"
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

    def visit_Name(self, node: ast.Name) -> None:
        # Block bare-name uses too — `f = open; f("...")` would otherwise slip
        # past visit_Call.
        if node.id in _BANNED_CALL_NAMES:
            raise ScorerValidationError(f"Banned name reference: {node.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Reject every leading-underscore attribute, not just dunders. This
        # blocks the object-graph escape (`x.__class__`) *and* access to a
        # facade's private state (`board._board.push(...)`); scorers only ever
        # touch the public read-only API.
        if node.attr in _BANNED_ATTRIBUTE_NAMES or node.attr.startswith("_"):
            raise ScorerValidationError(f"Banned attribute access: {node.attr}")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        # Closes the `"{0.__class__.__globals__...}".format(obj)` escape: the
        # dunders live inside a string literal (no ast.Attribute node to
        # catch), so we forbid any string constant containing a dunder marker.
        if isinstance(node.value, str) and "__" in node.value:
            raise ScorerValidationError(
                "String literals may not contain '__' (dunder-escape guard)"
            )
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
