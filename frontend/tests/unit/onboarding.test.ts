import { beforeEach, describe, expect, it, vi } from "vitest";
import { createOnboardingProfile, validateOnboarding } from "../../src/pages/OnboardingPage";
import { pendingCompanyId } from "../../src/session";

describe("onboarding validation", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("accepts a complete company and multi-role profile", () => {
    expect(
      validateOnboarding(
        {
          fullName: "Анна Петрова",
          email: "anna@example.ru",
          companyName: "ООО Север",
          inn: "7707083893",
        },
        ["ceo", "cfo"],
      ),
    ).toEqual({});
  });

  it("requires every field and at least one role", () => {
    expect(
      validateOnboarding(
        { fullName: " ", email: "не-email", companyName: "", inn: "123" },
        [],
      ),
    ).toEqual({
      fullName: "Укажите имя.",
      email: "Укажите корректную электронную почту.",
      companyName: "Укажите название компании.",
      inn: "ИНН должен содержать 10 или 12 цифр.",
      roles: "Выберите хотя бы одну роль.",
    });
  });

  it("accepts twelve-digit INNs and enforces text limits after trimming", () => {
    expect(
      validateOnboarding(
        {
          fullName: ` ${"Я".repeat(121)} `,
          email: "owner@example.ru",
          companyName: ` ${"К".repeat(161)} `,
          inn: "781234567890",
        },
        ["strategy"],
      ),
    ).toEqual({
      fullName: "Не больше 120 символов.",
      companyName: "Не больше 160 символов.",
    });
  });

  it("reuses the pending company when user creation succeeds on retry", async () => {
    const form = {
      fullName: " Анна Петрова ",
      email: " anna@example.ru ",
      companyName: " ООО Север ",
      inn: "7707083893",
    };
    const createCompany = vi.fn().mockResolvedValue({
      id: 17,
      inn: "7707083893",
      ogrn: "",
      name: "ООО Север",
      profile: {},
      createdAt: "2026-10-21T09:00:00Z",
      updatedAt: "2026-10-21T09:00:00Z",
    });
    const createUser = vi
      .fn()
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({
        id: 23,
        companyId: 17,
        email: "anna@example.ru",
        fullName: "Анна Петрова",
        roles: ["ceo", "cfo"],
        createdAt: "2026-10-21T09:01:00Z",
      });
    const service = { createCompany, createUser };

    await expect(createOnboardingProfile(form, ["ceo", "cfo"], service)).rejects.toThrow("temporary failure");
    expect(pendingCompanyId()).toBe(17);

    await expect(createOnboardingProfile(form, ["ceo", "cfo"], service)).resolves.toMatchObject({ id: 23 });
    expect(createCompany).toHaveBeenCalledOnce();
    expect(createUser).toHaveBeenCalledTimes(2);
    expect(createUser).toHaveBeenLastCalledWith({
      fullName: "Анна Петрова",
      email: "anna@example.ru",
      companyId: 17,
      roles: ["ceo", "cfo"],
    });
    expect(pendingCompanyId()).toBeNull();
  });
});
