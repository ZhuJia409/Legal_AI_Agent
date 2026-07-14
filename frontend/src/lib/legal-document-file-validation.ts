export type LegalDocumentModuleId = "case" | "contract";

export type LegalDocumentFilePolicy = {
  accept: string;
  label: string;
  mediaTypesByExtension: Readonly<Record<string, readonly string[]>>;
};

type LegalDocumentFile = Pick<File, "name" | "size" | "type">;

const MAX_FILE_BYTES = 20 * 1024 * 1024;
const OCTET_STREAM_MIME = "application/octet-stream";
const OFFICE_DOCUMENT_MIME =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

// 浏览器的 accept 仅用于文件选择提示；真正校验必须同时核对扩展名和对应 MIME。
export const LEGAL_DOCUMENT_FILE_POLICIES: Readonly<
  Record<LegalDocumentModuleId, LegalDocumentFilePolicy>
> = {
  case: {
    accept: `.pdf,.docx,.md,.txt,application/pdf,${OFFICE_DOCUMENT_MIME},text/markdown,text/x-markdown,text/plain`,
    label: "PDF、DOCX、MD 或 TXT",
    mediaTypesByExtension: {
      ".pdf": ["application/pdf", OCTET_STREAM_MIME],
      ".docx": [OFFICE_DOCUMENT_MIME, OCTET_STREAM_MIME],
      ".md": ["text/markdown", "text/x-markdown", "text/plain", OCTET_STREAM_MIME],
      ".txt": ["text/plain", OCTET_STREAM_MIME],
    },
  },
  contract: {
    accept: `.pdf,.docx,application/pdf,${OFFICE_DOCUMENT_MIME}`,
    label: "PDF 或 DOCX",
    mediaTypesByExtension: {
      ".pdf": ["application/pdf", OCTET_STREAM_MIME],
      ".docx": [OFFICE_DOCUMENT_MIME, OCTET_STREAM_MIME],
    },
  },
};

export function validateLegalDocumentFile(
  file: LegalDocumentFile,
  moduleId: LegalDocumentModuleId,
): string | null {
  if (file.size > MAX_FILE_BYTES) {
    return `单个文件不能超过 20 MiB（当前 ${formatFileSize(file.size)}）。`;
  }

  const policy = LEGAL_DOCUMENT_FILE_POLICIES[moduleId];
  const extension = fileExtension(file.name);
  const mediaType = normalizeMediaType(file.type);
  const allowedMediaTypes = policy.mediaTypesByExtension[extension];

  return allowedMediaTypes?.includes(mediaType) === true
    ? null
    : `请上传 ${policy.label} 格式的文件。`;
}

function normalizeMediaType(value: string): string {
  // 浏览器可能附带 charset 等参数；空 MIME 与后端一致按二进制流处理。
  return value.split(";", 1)[0].trim().toLowerCase() || OCTET_STREAM_MIME;
}

function fileExtension(filename: string): string {
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : "";
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const unit = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const index = Math.floor(Math.log(bytes) / Math.log(unit));
  return `${parseFloat((bytes / Math.pow(unit, index)).toFixed(1))} ${sizes[index]}`;
}
