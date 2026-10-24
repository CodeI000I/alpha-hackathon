import { act, createElement, useEffect } from "react";
import type { Dispatch, SetStateAction } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { localKey, useStoredState } from "../../src/localState";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let roots: Array<ReturnType<typeof createRoot>> = [];

function mount(node: ReturnType<typeof createElement>) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  act(() => root.render(node));
  return root;
}

describe("local state", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    for (const root of roots) act(() => root.unmount());
    roots = [];
    document.body.replaceChildren();
  });

  it("namespaces keys by version, data mode, company and user", () => {
    expect(localKey(7, "saved", 42)).toBe("alpha.insights.v2.api.company.42.user.7.saved");
    expect(localKey(7, "keywords")).toBe("alpha.insights.v2.api.company.none.user.7.keywords");
  });

  it("reloads the stored value when the key changes", () => {
    localStorage.setItem("first", JSON.stringify([1]));
    localStorage.setItem("second", JSON.stringify([2, 3]));
    let observed: number[] = [];

    function Probe({ storageKey }: { storageKey: string }) {
      const [value] = useStoredState<number[]>(storageKey, []);
      useEffect(() => {
        observed = value;
      }, [value]);
      return null;
    }

    const root = mount(createElement(Probe, { storageKey: "first" }));
    expect(observed).toEqual([1]);

    act(() => root.render(createElement(Probe, { storageKey: "second" })));
    expect(observed).toEqual([2, 3]);
  });

  it("synchronizes independent hook instances in the same tab", () => {
    let left = 0;
    let right = 0;
    let setLeft: Dispatch<SetStateAction<number>> | undefined;

    function Probe({ side }: { side: "left" | "right" }) {
      const [value, setValue] = useStoredState("shared", 0);
      useEffect(() => {
        if (side === "left") {
          left = value;
          setLeft = setValue;
        } else {
          right = value;
        }
      }, [setValue, side, value]);
      return null;
    }

    mount(createElement("div", null, createElement(Probe, { side: "left" }), createElement(Probe, { side: "right" })));
    act(() => setLeft?.((value) => value + 1));

    expect(left).toBe(1);
    expect(right).toBe(1);
    expect(localStorage.getItem("shared")).toBe("1");
  });

  it("accepts cross-tab storage updates", () => {
    let observed = "initial";

    function Probe() {
      const [value] = useStoredState("cross-tab", "initial");
      useEffect(() => {
        observed = value;
      }, [value]);
      return null;
    }

    mount(createElement(Probe));
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: "cross-tab", newValue: JSON.stringify("updated") }));
    });
    expect(observed).toBe("updated");
  });

  it("does not resurrect an in-memory value after its storage key is removed", () => {
    let observed = 0;
    let update: Dispatch<SetStateAction<number>> | undefined;

    function Probe() {
      const [value, setValue] = useStoredState("removed", 0);
      useEffect(() => {
        observed = value;
        update = setValue;
      }, [setValue, value]);
      return null;
    }

    const first = mount(createElement(Probe));
    act(() => update?.(7));
    expect(observed).toBe(7);
    act(() => first.unmount());
    roots = roots.filter((root) => root !== first);
    localStorage.removeItem("removed");

    mount(createElement(Probe));
    expect(observed).toBe(0);
  });
});
