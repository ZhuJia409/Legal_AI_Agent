from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.db.session import build_mysql_session_factory
from app.repositories.contract_review import (
    PymongoContractReviewAuditRepository,
    SqlAlchemyContractReviewSnapshotRepository,
)
from app.services.contract_review.agents import LangChainReviewAgentRunner
from app.services.contract_review.background import ContractBackgroundService
from app.services.contract_review.documents import ContractReviewDocumentService
from app.services.contract_review.graph import ContractReviewGraphService
from app.services.contract_review.history import ContractReviewHistoryService
from app.services.contract_review.pdf import ContractReviewPdfRenderer
from app.services.contract_review.persistence import ContractReviewPersistenceService
from app.services.mineru_parser import DocumentParserProtocol, MineruDocumentParser
from app.services.object_storage import MinioObjectStorage
from app.services.pdf_runtime import TectonicCompiler


def get_contract_background_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractBackgroundService:
    return ContractBackgroundService.from_llm_settings(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        fallback_model=settings.llm_fallback_model,
    )


def get_contract_review_graph_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractReviewGraphService:
    """按官方 LangChain/LangGraph 接口组装完整合同审查 DAG。"""

    background_service = ContractBackgroundService.from_llm_settings(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        fallback_model=settings.llm_fallback_model,
    )
    runner = LangChainReviewAgentRunner(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        fallback_model=settings.llm_fallback_model,
    )
    return ContractReviewGraphService(background_service, runner)


def get_document_parser(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentParserProtocol:
    return MineruDocumentParser(
        api_key=settings.mineru_api_key,
        base_url=settings.mineru_base_url,
        model_version=settings.mineru_model_version,
        poll_interval_seconds=settings.mineru_poll_interval_seconds,
        poll_timeout_seconds=settings.mineru_poll_timeout_seconds,
    )


def get_contract_review_persistence_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractReviewPersistenceService:
    session_factory = build_mysql_session_factory(settings)
    return ContractReviewPersistenceService(
        object_storage=MinioObjectStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
        ),
        snapshot_repository=SqlAlchemyContractReviewSnapshotRepository(session_factory),
        audit_repository=PymongoContractReviewAuditRepository(settings.mongodb_url),
    )


def get_contract_review_pdf_renderer(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractReviewPdfRenderer:
    """使用服务端固定配置组装离线 Tectonic 渲染器。"""

    return ContractReviewPdfRenderer(
        compiler=TectonicCompiler(
            tectonic_path=settings.tectonic_path,
            timeout_seconds=settings.tectonic_timeout_seconds,
        )
    )


def get_contract_review_document_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractReviewDocumentService:
    """组装报告元数据与 MinIO 只读边界，不向浏览器暴露对象地址。"""

    session_factory = build_mysql_session_factory(settings)
    return ContractReviewDocumentService(
        repository=SqlAlchemyContractReviewSnapshotRepository(session_factory),
        object_storage=MinioObjectStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
        ),
    )


def get_contract_review_history_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> ContractReviewHistoryService:
    return ContractReviewHistoryService(
        SqlAlchemyContractReviewSnapshotRepository(build_mysql_session_factory(settings))
    )
