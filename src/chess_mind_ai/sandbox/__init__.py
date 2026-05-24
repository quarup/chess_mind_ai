"""Validate + execute LLM-generated scorer code.

Implements layers 1-3 of plan.md section 6 (AST validation, restricted
builtins, in-process execution). Subprocess isolation, timeouts, and
container hardening are M4's job.
"""
