"""法律报告共用的 LaTeX 编译与安全转义入口。

当前底层实现沿用已充分测试的合同报告编译器；案件和合同模块通过本入口共享同一套
Tectonic、严格模板和转义边界，避免复制外部进程安全逻辑。
"""

from app.services.contract_review_pdf import (
    PdfRendererUnavailableError,
    ReportPdfCompiler,
    ReportPdfGenerationError,
    TectonicCompiler,
    create_latex_environment,
    latex_escape,
    latex_escape_breakable_filename,
)

__all__ = [
    "PdfRendererUnavailableError",
    "ReportPdfCompiler",
    "ReportPdfGenerationError",
    "TectonicCompiler",
    "create_latex_environment",
    "latex_escape",
    "latex_escape_breakable_filename",
]
