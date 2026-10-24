import { beforeEach, describe, expect, it, vi } from "vitest";
import { getOnboardingRequestKey, clearOnboardingRequestKey } from "../../src/auth/onboardingDraft";
import { createOnboardingProfile, validateOnboarding } from "../../src/pages/OnboardingPage";

describe("onboarding validation", () => {
  beforeEach(() => localStorage.clear());

  it("accepts a complete company, multi-role profile, and password", () => {
    expect(validateOnboarding({ fullName: "Анна Петрова", email: "anna@example.ru", companyName: "ООО Север", inn: "7707083893" }, ["ceo", "cfo"], "a sufficiently long password")).toEqual({});
  });

  it("requires valid identity, company, role, and password values", () => {
    expect(validateOnboarding({ fullName: " ", email: "не-email", companyName: "", inn: "123" }, [], "short")).toEqual({
      fullName: "Укажите имя.",
      email: "Укажите корректную электронную почту.",
      companyName: "Укажите название компании.",
      inn: "ИНН должен содержать 10 или 12 цифр.",
      password: "Пароль должен содержать не менее 10 символов.",
      roles: "Выберите хотя бы одну роль.",
    });
  });

  it("accepts twelve-digit INNs and enforces text limits after trimming", () => {
    expect(validateOnboarding({ fullName: ` ${"Я".repeat(121)} `, email: "owner@example.ru", companyName: ` ${"К".repeat(161)} `, inn: "781234567890" }, ["strategy"], "a sufficiently long password")).toEqual({
      fullName: "Не больше 120 символов.",
      companyName: "Не больше 160 символов.",
    });
  });

  it("retries the atomic onboarding request with the same idempotency key", async () => {
    const form = { fullName: " Анна Петрова ", email: " anna@example.ru ", companyName: " ООО Север ", inn: "7707083893" };
    const user = { id: 23, companyId: 17, email: "anna@example.ru", fullName: "Анна Петрова", roles: ["ceo", "cfo"], createdAt: "2026-10-21T09:01:00Z" };
    const onboard = vi.fn().mockRejectedValueOnce(new Error("temporary failure")).mockResolvedValue({ user });
    const service = { onboard };
    const key = "575f4e25-e79b-4184-aed2-5f0cfa7fb53f";

    await expect(createOnboardingProfile(form, ["cfo", "ceo", "ceo"], "a sufficiently long password", key, service)).rejects.toThrow("temporary failure");
    await expect(createOnboardingProfile(form, ["cfo", "ceo", "ceo"], "a sufficiently long password", key, service)).resolves.toMatchObject({ id: 23 });
    expect(onboard).toHaveBeenCalledTimes(2);
    expect(onboard).toHaveBeenLastCalledWith({
      company: { name: "ООО Север", inn: "7707083893" },
      user: { fullName: "Анна Петрова", email: "anna@example.ru", roles: ["ceo", "cfo"], password: "a sufficiently long password" },
    }, key);
  });

  it("persists and reuses a key until onboarding succeeds or the input changes", () => {
    const key = getOnboardingRequestKey("api");
    expect(getOnboardingRequestKey("api")).toBe(key);
    clearOnboardingRequestKey("api");
    expect(getOnboardingRequestKey("api")).not.toBe(key);
  });
});
