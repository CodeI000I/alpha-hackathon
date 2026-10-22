import { describe, expect, it } from "vitest";
import { validateDocument } from "../../src/pages/CompanyPage";

describe("company document validation", () => {
  it.each(["contract.pdf", "notes.TXT", "document.docx", "plan.xlsx"])("accepts supported format %s", (name) => {
    expect(validateDocument({ name, size: 10 * 1024 * 1024 })).toBeUndefined();
  });
  it("rejects files over 10 MiB even when backend permits a larger body", () => {
    expect(validateDocument({ name: "big.pdf", size: 10 * 1024 * 1024 + 1 })).toMatch("10 МБ");
  });
  it("rejects unsupported extensions and empty files", () => {
    expect(validateDocument({ name: "archive.zip", size: 10 })).toMatch("PDF, TXT, DOCX и XLSX");
    expect(validateDocument({ name: "empty.txt", size: 0 })).toMatch("пуст");
  });
});
