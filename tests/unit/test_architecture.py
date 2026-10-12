"""Rules 1 and 4, checked against the real source tree and against trees built wrongly."""

from pathlib import Path

from tests.architecture import (
    AUTO_APPROVE_FILE,
    find_auto_approved_references,
    find_erp_references_outside_gateway,
    find_erp_write_sites,
    find_model_client_imports,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

GATEWAY_WITH_ONE_WRITE = """
async def post_to_erp(session, document_id, invoice):
    entry = ErpEntry(document_id=document_id)
    session.add(entry)
"""


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def _wrong_tree(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    _write(tmp_path, "app/erp/gateway.py", GATEWAY_WITH_ONE_WRITE)
    return tmp_path


# Rule 1: one door to a model


def test_no_model_client_is_imported_outside_inference_and_reading() -> None:
    assert find_model_client_imports(REPO_ROOT) == []


def test_model_client_import_in_another_module_is_caught(tmp_path: Path) -> None:
    root = _wrong_tree(tmp_path)
    _write(root, "app/review/shortcut.py", "from langchain_openai import AzureChatOpenAI\n")
    _write(root, "app/workflow/steps.py", "import openai\n")
    _write(root, "scripts/quick.py", "from azure.ai.documentintelligence import X\n")

    assert find_model_client_imports(root) == [
        "app/review/shortcut.py:1 langchain_openai",
        "app/workflow/steps.py:1 openai",
        "scripts/quick.py:1 azure.ai.documentintelligence",
    ]


def test_model_client_import_inside_the_door_is_allowed(tmp_path: Path) -> None:
    root = _wrong_tree(tmp_path)
    _write(root, "app/inference/azure_openai.py", "from langchain_openai import AzureChatOpenAI\n")
    _write(root, "app/reading/azure_di.py", "from azure.ai.documentintelligence import X\n")

    assert find_model_client_imports(root) == []


# Rule 4: one path to the ERP


def test_the_gateway_is_the_only_code_that_touches_the_erp() -> None:
    assert find_erp_references_outside_gateway(REPO_ROOT) == []


def test_the_gateway_creates_erp_entries_in_exactly_one_place() -> None:
    sites = find_erp_write_sites(REPO_ROOT)
    assert len(sites) == 1
    assert sites[0].startswith("post_to_erp:")


def test_second_erp_path_through_the_model_is_caught(tmp_path: Path) -> None:
    root = _wrong_tree(tmp_path)
    _write(
        root,
        "app/review/approve.py",
        "from app.db.models import ErpEntry\n\ndef fast(session):\n    session.add(ErpEntry())\n",
    )

    violations = find_erp_references_outside_gateway(root)
    assert "app/review/approve.py:1 ErpEntry" in violations
    assert "app/review/approve.py:4 ErpEntry" in violations


def test_second_erp_path_through_raw_sql_is_caught(tmp_path: Path) -> None:
    root = _wrong_tree(tmp_path)
    _write(root, "app/workflow/steps.py", 'SQL = "INSERT INTO erp_entries (id) VALUES (1)"\n')

    assert find_erp_references_outside_gateway(root) == ["app/workflow/steps.py:1 'erp_entries'"]


def test_second_write_inside_the_gateway_is_caught(tmp_path: Path) -> None:
    root = _wrong_tree(tmp_path)
    _write(
        root,
        "app/erp/gateway.py",
        GATEWAY_WITH_ONE_WRITE + "\ndef backdoor(session):\n    session.add(ErpEntry())\n",
    )

    assert len(find_erp_write_sites(root)) == 2


# Rule 3: the model never approves alone


def test_only_the_routing_step_can_make_a_document_auto_approved() -> None:
    references = find_auto_approved_references(REPO_ROOT)

    assert references, "the routing step should set the status"
    assert all(reference.startswith(f"{AUTO_APPROVE_FILE}:") for reference in references)


def test_the_routing_step_approves_only_on_a_stored_decision() -> None:
    """The status is set inside one `if` that tests the decision made by scoring.decide."""
    source = (REPO_ROOT / AUTO_APPROVE_FILE).read_text(encoding="utf-8")

    assert source.count("DocumentStatus.AUTO_APPROVED") == 2  # set before booking, kept after
    guard = source.index("if decision.decision == scoring.AUTO_APPROVE:")
    assert guard < source.index("DocumentStatus.AUTO_APPROVED")


def test_a_shortcut_to_auto_approval_is_caught(tmp_path: Path) -> None:
    root = _wrong_tree(tmp_path)
    _write(
        root,
        "app/agents/extract.py",
        "def confident(document, model_score):\n"
        "    if model_score > 0.99:\n"
        "        document.status = DocumentStatus.AUTO_APPROVED.value\n",
    )
    _write(root, "app/web/quick.py", "STATUS = 'auto_approved'\n")

    assert find_auto_approved_references(root) == ["app/agents/extract.py:3", "app/web/quick.py:1"]
