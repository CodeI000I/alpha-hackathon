import { beforeEach, describe, expect, it } from "vitest";
import {
  clearCurrentUserId,
  clearPendingCompanyId,
  currentUserId,
  pendingCompanyId,
  setCurrentUserId,
  setPendingCompanyId,
} from "../../src/session";

describe("browser session", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("persists and clears the current user", () => {
    expect(currentUserId()).toBeNull();

    setCurrentUserId(42);
    expect(currentUserId()).toBe(42);
    expect(localStorage.getItem("alpha.userId")).toBe("42");

    clearCurrentUserId();
    expect(currentUserId()).toBeNull();
    expect(localStorage.getItem("alpha.userId")).toBeNull();
  });

  it("ignores invalid user identifiers", () => {
    for (const value of ["", "0", "-1", "1.5", "NaN", "9007199254740992"]) {
      localStorage.setItem("alpha.userId", value);
      expect(currentUserId()).toBeNull();
    }

    setCurrentUserId(0);
    expect(localStorage.getItem("alpha.userId")).toBeNull();
  });

  it("keeps a pending company independently so onboarding can resume", () => {
    setPendingCompanyId(17);
    setCurrentUserId(9);

    clearCurrentUserId();
    expect(pendingCompanyId()).toBe(17);

    clearPendingCompanyId();
    expect(pendingCompanyId()).toBeNull();
  });
});
