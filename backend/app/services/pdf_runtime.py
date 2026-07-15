"""法律文书 PDF 共用的 Tectonic 编译与 LaTeX 安全边界。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Protocol

from jinja2 import BaseLoader, Environment, FileSystemLoader, StrictUndefined


class ReportPdfGenerationError(RuntimeError):
    """报告模板渲染或 PDF 结果校验失败。"""

    def __init__(
        self,
        message: str,
        *,
        failure_stage: str,
        cause_type: str | None = None,
        return_code: int | None = None,
    ) -> None:
        # 仅携带可安全进入日志的分类信息，不保存合同、LaTeX 或编译器输出。
        super().__init__(message)
        self.failure_stage = failure_stage
        self.cause_type = cause_type
        self.return_code = return_code


class PdfRendererUnavailableError(ReportPdfGenerationError):
    """Tectonic 不存在或无法启动，调用方可将其映射为 503。"""


class ReportPdfCompiler(Protocol):
    """外部 PDF 编译边界；实现方不得把合同正文写入不受控日志。"""

    async def compile(self, latex_source: str) -> bytes: ...


class TectonicCompiler:
    """在隔离临时目录中调用本地 Tectonic，且不开放 shell 解释边界。"""

    def __init__(
        self,
        *,
        tectonic_path: str | Path = ".tools/tectonic/tectonic.exe",
        timeout_seconds: float = 90,
        repository_root: Path | None = None,
        cache_directory: str | Path | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        resolved_root = repository_root or Path(__file__).resolve().parents[3]
        configured_path = Path(tectonic_path).expanduser()
        self._executable_path = (
            configured_path
            if configured_path.is_absolute()
            else resolved_root / configured_path
        ).resolve()
        configured_cache = Path(cache_directory or ".tools/tectonic/cache").expanduser()
        self._cache_directory = (
            configured_cache
            if configured_cache.is_absolute()
            else resolved_root / configured_cache
        ).resolve()
        self._timeout_seconds = timeout_seconds

    @property
    def executable_path(self) -> Path:
        """暴露最终路径便于启动诊断；相对配置始终锚定仓库根目录。"""

        return self._executable_path

    @property
    def cache_directory(self) -> Path:
        """项目缓存固定在仓库工具目录，避免依赖具体服务账号的用户缓存。"""

        return self._cache_directory

    async def compile(self, latex_source: str) -> bytes:
        # Windows reload/multi-worker 使用 SelectorEventLoop，需在线程中隔离同步子进程边界。
        return await asyncio.to_thread(self._compile_sync, latex_source)

    def _compile_sync(self, latex_source: str) -> bytes:
        if not self._executable_path.is_file():
            missing_error = FileNotFoundError(self._executable_path)
            raise PdfRendererUnavailableError(
                "Tectonic PDF 渲染器不可用",
                failure_stage="renderer_unavailable",
                cause_type=missing_error.__class__.__name__,
            ) from missing_error

        # 临时目录退出即清理 LaTeX、日志和辅助文件，避免合同正文残留在工作树。
        with tempfile.TemporaryDirectory(prefix="legal-document-pdf-") as temp_dir:
            working_directory = Path(temp_dir)
            source_path = working_directory / "report.tex"
            output_path = working_directory / "report.pdf"
            source_path.write_text(latex_source, encoding="utf-8")
            process_environment = os.environ.copy()
            process_environment["TECTONIC_CACHE_DIR"] = str(self._cache_directory)

            command = [
                str(self._executable_path),
                "--only-cached",
                "--keep-logs",
                "--outdir",
                str(working_directory),
                "report.tex",
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(working_directory),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=process_environment,
                    timeout=self._timeout_seconds,
                    check=False,
                    shell=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ReportPdfGenerationError(
                    "法律文书 PDF 编译超时",
                    failure_stage="compile_timeout",
                    cause_type=exc.__class__.__name__,
                ) from exc
            except OSError as exc:
                raise PdfRendererUnavailableError(
                    "Tectonic PDF 渲染器无法启动",
                    failure_stage="process_start",
                    cause_type=exc.__class__.__name__,
                ) from exc
            except Exception as exc:
                # 未知 runner 异常只保留类型，避免异常原文携带合同或命令输出进入日志。
                raise ReportPdfGenerationError(
                    "Tectonic 编译通信失败",
                    failure_stage="compile_exit",
                    cause_type=exc.__class__.__name__,
                ) from exc

            if completed.returncode != 0:
                raise ReportPdfGenerationError(
                    f"Tectonic 编译失败（退出码 {completed.returncode}）",
                    failure_stage="compile_exit",
                    return_code=completed.returncode,
                )
            if not output_path.is_file():
                raise ReportPdfGenerationError(
                    "Tectonic 未生成报告 PDF 文件",
                    failure_stage="output_validation",
                )

            content = output_path.read_bytes()
            if not content:
                raise ReportPdfGenerationError(
                    "Tectonic 生成了空的报告 PDF 文件",
                    failure_stage="output_validation",
                )
            if not content.startswith(b"%PDF-"):
                raise ReportPdfGenerationError(
                    "Tectonic 输出缺少有效的 PDF 文件头",
                    failure_stage="output_validation",
                )
            return content


def latex_escape(value: object) -> str:
    """把不可信文本转换为普通 LaTeX 文本，禁止注入命令或环境。"""

    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "\n": r"\par{}",
        "\t": "    ",
    }
    escaped: list[str] = []
    for character in text:
        if character in replacements:
            escaped.append(replacements[character])
            continue
        # Cc/Cf 等控制字符可能改变编译行为；换行与制表符已在上方受控处理。
        if unicodedata.category(character).startswith("C"):
            continue
        escaped.append(character)
    return "".join(escaped)


def latex_escape_breakable_filename(value: object) -> str:
    """安全转义文件名，并允许连续无空格字符在固定宽度列内换行。"""

    normalized = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    # 逐字符转义后再插入断行点，避免在 LaTeX 控制序列内部插入命令。
    escaped_characters = [latex_escape(character) for character in normalized]
    return r"\allowbreak{}".join(filter(None, escaped_characters))


def create_latex_environment(*, loader: BaseLoader | None = None) -> Environment:
    """创建与 LaTeX 定界符隔离、缺字段即失败的 Jinja2 环境。"""

    template_loader = loader or FileSystemLoader(
        Path(__file__).resolve().parents[1] / "templates"
    )
    environment = Environment(
        loader=template_loader,
        undefined=StrictUndefined,
        autoescape=False,
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["latex_escape"] = latex_escape
    environment.filters["latex_escape_breakable_filename"] = (
        latex_escape_breakable_filename
    )
    return environment
