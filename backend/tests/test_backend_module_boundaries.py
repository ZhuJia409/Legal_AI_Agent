from __future__ import annotations

import ast
import importlib
from pathlib import Path

from app.db.models import Base
from app.main import app

EXPECTED_PUBLIC_ROUTES = {
    ("POST", "/api/v1/case-analyses"),
    ("GET", "/api/v1/case-analyses"),
    ("GET", "/api/v1/case-analyses/{analysis_id}"),
    ("GET", "/api/v1/case-analyses/{analysis_id}/document"),
    ("POST", "/api/v1/contract-reviews"),
    ("POST", "/api/v1/contract-review-reports"),
    ("GET", "/api/v1/contract-review-reports"),
    ("GET", "/api/v1/contract-review-reports/{task_id}"),
    ("GET", "/api/v1/contract-review-reports/{task_id}/document"),
}
EXPECTED_PUBLIC_SCHEMAS = {
    "CaseAnalysisHistoryResponse",
    "CaseAnalysisResponse",
    "ContractBackgroundResponse",
    "ContractReviewHistoryResponse",
    "ContractReviewReportResponse",
}


def test_business_modules_expose_focused_submodules() -> None:
    module_names = (
        "app.api.v1.contract_reviews.routes",
        "app.api.v1.contract_reviews.dependencies",
        "app.api.v1.contract_reviews.request_parsing",
        "app.api.v1.case_analyses.routes",
        "app.api.v1.case_analyses.dependencies",
        "app.api.v1.case_analyses.request_parsing",
        "app.services.contract_review.graph",
        "app.services.contract_review.agents",
        "app.services.contract_review.history",
        "app.services.contract_review.reporting",
        "app.services.case_analysis.graph",
        "app.services.case_analysis.history",
        "app.services.case_analysis.results",
        "app.schemas.contract_review",
        "app.schemas.contract_review.report",
        "app.schemas.case_analysis",
        "app.schemas.case_analysis.models",
        "app.db.models.contract_review",
        "app.db.models.case_analysis",
    )

    for module_name in module_names:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            raise AssertionError(f"missing module: {module_name}") from exc


def test_public_api_route_set_is_unchanged() -> None:
    openapi = app.openapi()
    paths = openapi["paths"]
    actual_routes = {
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/api/v1/")
        for method in operations
        if method.upper() in {"GET", "POST"}
    }

    assert actual_routes == EXPECTED_PUBLIC_ROUTES
    assert EXPECTED_PUBLIC_SCHEMAS <= set(openapi["components"]["schemas"])


def test_all_sqlalchemy_models_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "review_task",
        "review_document",
        "contract_paragraph",
        "context_snapshot",
        "case_analysis_snapshot",
    }


def test_business_service_packages_do_not_import_each_other() -> None:
    services_root = Path(__file__).parents[1] / "app" / "services"
    _assert_no_cross_domain_imports(
        services_root / "contract_review",
        forbidden_prefix="app.services.case_analysis",
    )
    _assert_no_cross_domain_imports(
        services_root / "case_analysis",
        forbidden_prefix="app.services.contract_review",
    )


def test_shared_services_do_not_import_business_services() -> None:
    services_root = Path(__file__).parents[1] / "app" / "services"
    shared_modules = (
        "document_parser.py",
        "history.py",
        "mineru_parser.py",
        "object_storage.py",
        "pdf_runtime.py",
    )

    for filename in shared_modules:
        source_path = services_root / filename
        assert source_path.is_file()
        source_text = source_path.read_text(encoding="utf-8")
        imports = _module_imports(source_path)
        assert not any(
            module.startswith(
                ("app.services.contract_review", "app.services.case_analysis")
            )
            for module in imports
        ), source_path
        if filename == "pdf_runtime.py":
            assert "contract-review" not in source_text
            assert "合同审查" not in source_text


def _assert_no_cross_domain_imports(package: Path, *, forbidden_prefix: str) -> None:
    assert package.is_dir()
    for source_path in package.rglob("*.py"):
        imports = _module_imports(source_path)
        assert not any(module.startswith(forbidden_prefix) for module in imports), source_path


def _module_imports(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
    return imports
