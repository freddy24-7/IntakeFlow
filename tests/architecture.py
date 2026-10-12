"""Checks that read the source tree to enforce the architecture rules.

They take a root directory so the tests can also point them at a tree that is
built wrongly on purpose, and prove the check catches it.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

SOURCE_DIRS = ("app", "scripts")

# Rule 1: packages that hold a model, embedding or Document Intelligence client.
MODEL_CLIENT_PREFIXES = (
    "openai",
    "azure.ai",
    "azure.search",
    "langchain_openai",
    "langchain_community",
    "langchain.chat_models",
    "langchain.embeddings",
    "langchain_core.language_models",
    "langchain_core.embeddings",
)
MODEL_CLIENT_ALLOWED_DIRS = ("app/inference", "app/reading")

# Rule 4: the only files that may mention the ERP table or its model.
ERP_MODEL_NAME = "ErpEntry"
ERP_TABLE_NAME = "erp_entries"
ERP_MODEL_FILE = "app/db/models.py"
ERP_GATEWAY_FILE = "app/erp/gateway.py"


def _python_files(root: Path) -> Iterator[tuple[str, ast.Module]]:
    for source_dir in SOURCE_DIRS:
        for path in sorted((root / source_dir).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            yield relative, ast.parse(path.read_text(encoding="utf-8"), filename=relative)


def _imported_modules(tree: ast.Module) -> Iterator[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, node.lineno


def find_model_client_imports(root: Path) -> list[str]:
    """Imports of a model client outside the allowed packages, as 'file:line module'."""
    violations = []
    for relative, tree in _python_files(root):
        if relative.startswith(MODEL_CLIENT_ALLOWED_DIRS):
            continue
        for module, line in _imported_modules(tree):
            if any(module == p or module.startswith(p + ".") for p in MODEL_CLIENT_PREFIXES):
                violations.append(f"{relative}:{line} {module}")
    return violations


def find_erp_references_outside_gateway(root: Path) -> list[str]:
    """Any mention of the ERP model or table outside the model file and the gateway."""
    violations = []
    for relative, tree in _python_files(root):
        if relative in (ERP_MODEL_FILE, ERP_GATEWAY_FILE):
            continue
        for node in ast.walk(tree):
            if (
                (isinstance(node, ast.Name) and node.id == ERP_MODEL_NAME)
                or (isinstance(node, ast.Attribute) and node.attr == ERP_MODEL_NAME)
                or (isinstance(node, ast.alias) and node.name == ERP_MODEL_NAME)
            ):
                violations.append(f"{relative}:{node.lineno} {ERP_MODEL_NAME}")
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and ERP_TABLE_NAME in node.value
            ):
                violations.append(f"{relative}:{node.lineno} '{ERP_TABLE_NAME}'")
    return violations


def find_erp_write_sites(root: Path) -> list[str]:
    """Places in the gateway that create an ERP entry, as 'function:line'. Must be one."""
    gateway = root / ERP_GATEWAY_FILE
    tree = ast.parse(gateway.read_text(encoding="utf-8"), filename=ERP_GATEWAY_FILE)
    sites = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == ERP_MODEL_NAME
            ):
                sites.append(f"{function.name}:{node.lineno}")
    return sites


# Rule 3: the one place where a document may become auto-approved.
AUTO_APPROVED_NAME = "AUTO_APPROVED"
AUTO_APPROVED_VALUE = "auto_approved"
AUTO_APPROVE_FILE = "app/workflow/routing_steps.py"


def _mentions_auto_approved(node: ast.AST) -> bool:
    return any(
        (isinstance(child, ast.Attribute) and child.attr == AUTO_APPROVED_NAME)
        or (isinstance(child, ast.Constant) and child.value == AUTO_APPROVED_VALUE)
        for child in ast.walk(node)
    )


def _sets_status(node: ast.AST) -> ast.AST | None:
    """The value being written when this node sets a status, else None.

    Three ways to set it: `document.status = ...`, a `status=...` argument (a
    constructor or an UPDATE's `.values(...)`), and raw SQL that writes it.
    """
    if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Attribute) and target.attr == "status" for target in node.targets
    ):
        return node.value
    if isinstance(node, ast.keyword) and node.arg == "status":
        return node.value
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and AUTO_APPROVED_VALUE in node.value
        and any(word in node.value.upper() for word in ("UPDATE ", "INSERT "))
    ):
        return node
    return None


def find_auto_approved_writes(root: Path) -> list[str]:
    """Every place that sets a status to auto-approved, as 'file:line'. Reading
    the status (the dashboard, labels, the ERP gateway's check) is not listed."""
    writes = []
    for relative, tree in _python_files(root):
        for node in ast.walk(tree):
            value = _sets_status(node)
            if value is not None and (value is node or _mentions_auto_approved(value)):
                line = getattr(node, "lineno", getattr(value, "lineno", 0))
                writes.append(f"{relative}:{line}")
    return writes
