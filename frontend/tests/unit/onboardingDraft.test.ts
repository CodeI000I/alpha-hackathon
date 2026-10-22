import { beforeEach, describe, expect, it } from "vitest";
import { clearOnboardingDraft, readOnboardingDraft, saveOnboardingDraft, validateRegistrationIdentity, type OnboardingDraft } from "../../src/auth/onboardingDraft";

const draft: OnboardingDraft = {
  step: 2,
  form: { fullName: "Анна Петрова", email: "anna@example.ru", companyName: "ООО Север", inn: "7707083893" },
  selectedRoles: ["cfo", "ceo"],
};

describe("two-step registration draft", () => {
  beforeEach(() => sessionStorage.clear());
  it("validates identity without requesting company or roles at step one", () => {
    expect(validateRegistrationIdentity({ fullName: "Анна", email: "anna@example.ru" })).toEqual({});
    expect(validateRegistrationIdentity({ fullName: " ", email: "invalid" })).toEqual({ fullName: "Укажите имя.", email: "Укажите корректную электронную почту." });
  });
  it("restores second step, identity, company and selected roles after reload", () => {
    saveOnboardingDraft(draft, "api");
    expect(readOnboardingDraft("api")).toEqual(draft);
  });
  it("keeps API and demo drafts separate and clears only the completed mode", () => {
    saveOnboardingDraft(draft, "api");
    expect(readOnboardingDraft("demo")).toBeNull();
    saveOnboardingDraft({ ...draft, form: { ...draft.form, fullName: "Демо" } }, "demo");
    clearOnboardingDraft("api");
    expect(readOnboardingDraft("api")).toBeNull();
    expect(readOnboardingDraft("demo")?.form.fullName).toBe("Демо");
  });
  it("restores the first step if identity is invalid and ignores unknown stored fields", () => {
    sessionStorage.setItem("signal.registration-draft.v1.api", JSON.stringify({ ...draft, form: { ...draft.form, email: "", password: "secret" }, password: "secret", selectedRoles: ["cfo", "cfo", 7, null] }));
    expect(readOnboardingDraft("api")).toEqual({ step: 1, form: { ...draft.form, email: "" }, selectedRoles: ["cfo"] });
  });
  it("does not store arbitrary fields or passwords", () => {
    saveOnboardingDraft({ ...draft, password: "secret", form: { ...draft.form, password: "secret" } } as OnboardingDraft, "api");
    expect(sessionStorage.getItem("signal.registration-draft.v1.api")).not.toContain("secret");
    expect(sessionStorage.getItem("signal.registration-draft.v1.api")).not.toContain("password");
  });
  it("ignores malformed persisted data", () => {
    sessionStorage.setItem("signal.registration-draft.v1.api", "{broken");
    expect(readOnboardingDraft("api")).toBeNull();
    sessionStorage.setItem("signal.registration-draft.v1.api", JSON.stringify({ step: 2, form: { fullName: 5 } }));
    expect(readOnboardingDraft("api")).toBeNull();
  });
});
