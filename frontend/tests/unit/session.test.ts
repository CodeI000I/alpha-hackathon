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

  it("persists and clears the current user in the versioned API namespace", () => {
    expect(currentUserId("api")).toBeNull();

    setCurrentUserId(42, "api");
    expect(currentUserId("api")).toBe(42);
    expect(localStorage.getItem("signal.session.v2.api.userId")).toBe("42");

    clearCurrentUserId("api");
    expect(currentUserId("api")).toBeNull();
    expect(localStorage.getItem("signal.session.v2.api.userId")).toBeNull();
  });

  it("isolates API and demo sessions", () => {
    setCurrentUserId(41, "api");
    expect(currentUserId("demo")).toBeNull();
    setCurrentUserId(2, "demo");

    expect(currentUserId("api")).toBe(41);
    expect(currentUserId("demo")).toBe(2);
  });

  it("does not migrate the unversioned legacy identifier", () => {
    localStorage.setItem("alpha.userId", "99");
    localStorage.setItem("alpha.pendingCompanyId", "88");

    expect(currentUserId("api")).toBeNull();
    expect(pendingCompanyId("api")).toBeNull();
  });

  it("ignores invalid user identifiers", () => {
    for (const value of ["", "0", "-1", "1.5", "NaN", "9007199254740992"]) {
      localStorage.setItem("signal.session.v2.api.userId", value);
      expect(currentUserId("api")).toBeNull();
      expect(localStorage.getItem("signal.session.v2.api.userId")).toBeNull();
    }

    setCurrentUserId(0, "api");
    expect(localStorage.getItem("signal.session.v2.api.userId")).toBeNull();
  });

  it("keeps a pending company independently so onboarding can resume", () => {
    setPendingCompanyId(17, "demo");
    setCurrentUserId(9, "demo");

    clearCurrentUserId("demo");
    expect(pendingCompanyId("demo")).toBe(17);
    expect(localStorage.getItem("signal.session.v2.demo.pendingCompanyId")).toBe("17");

    clearPendingCompanyId("demo");
    expect(pendingCompanyId("demo")).toBeNull();
  });
});
