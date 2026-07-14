import assert from "node:assert/strict";
import test from "node:test";

type ValidationModule = typeof import("./legal-document-file-validation");
type TestFile = Pick<File, "name" | "size" | "type">;

const validationModule = (await import(
  new URL("./legal-document-file-validation.ts", import.meta.url).href
)) as ValidationModule;

const { validateLegalDocumentFile } = validationModule;

function createFile(name: string, type: string, size = 1): TestFile {
  return { name, size, type };
}

function assertAccepted(moduleId: "case" | "contract", file: TestFile) {
  assert.equal(
    validateLegalDocumentFile(file, moduleId),
    null,
    `${moduleId} 应接受 ${file.name} (${file.type || "<empty>"})`,
  );
}

function assertRejected(moduleId: "case" | "contract", file: TestFile) {
  assert.match(
    validateLegalDocumentFile(file, moduleId) ?? "",
    /请上传/,
    `${moduleId} 应拒绝 ${file.name} (${file.type || "<empty>"})`,
  );
}

test("案件材料按扩展名匹配规范化后的 MIME", () => {
  const acceptedFiles = [
    createFile("evidence.PDF", " Application/PDF ; charset=binary"),
    createFile(
      "pleading.DOCX",
      "APPLICATION/VND.OPENXMLFORMATS-OFFICEDOCUMENT.WORDPROCESSINGML.DOCUMENT; VERSION=1",
    ),
    createFile("notes.md", "text/markdown"),
    createFile("notes.MD", "Text/X-Markdown; charset=utf-8"),
    createFile("notes.md", "text/plain"),
    createFile("record.txt", "TEXT/PLAIN; charset=UTF-8"),
    createFile("evidence.pdf", "application/octet-stream"),
    createFile("pleading.docx", ""),
    createFile("notes.md", "   "),
    createFile("record.txt", "application/octet-stream"),
  ];

  for (const file of acceptedFiles) {
    assertAccepted("case", file);
  }
});

test("案件材料同时校验扩展名与 MIME，拒绝交叉伪装", () => {
  const rejectedFiles = [
    createFile(
      "renamed.pdf",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    createFile("renamed.docx", "application/pdf"),
    createFile("renamed.txt", "text/x-markdown"),
    createFile("renamed.md", "application/pdf"),
    createFile("archive.exe", "application/octet-stream"),
  ];

  for (const file of rejectedFiles) {
    assertRejected("case", file);
  }
});

test("合同材料仅允许对应 MIME 的 PDF 或 DOCX", () => {
  assertAccepted("contract", createFile("contract.pdf", "application/pdf; charset=binary"));
  assertAccepted(
    "contract",
    createFile(
      "contract.docx",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
  );
  assertAccepted("contract", createFile("contract.PDF", ""));
  assertAccepted("contract", createFile("contract.DOCX", "application/octet-stream"));

  assertRejected("contract", createFile("contract.md", "text/markdown"));
  assertRejected("contract", createFile("contract.txt", "text/plain"));
  assertRejected(
    "contract",
    createFile(
      "contract.pdf",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
  );
  assertRejected("contract", createFile("contract.docx", "application/pdf"));
});

test("文件大小仍以 20 MiB 为单文件上限", () => {
  assertAccepted("case", createFile("within-limit.pdf", "application/pdf", 20 * 1024 * 1024));
  assert.match(
    validateLegalDocumentFile(
      createFile("too-large.pdf", "application/pdf", 20 * 1024 * 1024 + 1),
      "case",
    ) ?? "",
    /20 MiB/,
  );
});
