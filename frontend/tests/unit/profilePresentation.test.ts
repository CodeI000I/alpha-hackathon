import { describe, expect, it } from "vitest";
import { profileBlockLabel, profileValueText } from "../../src/profilePresentation";

describe("profile presentation", () => {
  it("uses descriptive group labels without changing unknown catalog names", () => {
    expect(profileBlockLabel("Бизнес")).toBe("Деятельность и финансы");
    expect(profileBlockLabel("Среда")).toBe("Рынок и регулирование");
    expect(profileBlockLabel("Дополнительная группа")).toBe("Дополнительная группа");
  });
  it("shows scalar values, empty values, and scalar lists without JSON syntax", () => {
    expect(profileValueText("Производство", false)).toBe("Производство");
    expect(profileValueText(null, false)).toBe("Не указано");
    expect(profileValueText(false, false)).toBe("Нет");
    expect(profileValueText(["Москва", "Казань"], false)).toBe("Москва; Казань");
  });
  it("formats only documented demo shapes and never assumes their API meaning", () => {
    expect(profileValueText({ floatingRateShare: 0.42 }, true)).toBe("Доля долга с плавающей ставкой: 42 %");
    expect(profileValueText({ industry: "Разработка ПО" }, true)).toBe("Отрасль: Разработка ПО");
    expect(profileValueText({ industry: "Разработка ПО" }, false)).toBeUndefined();
    expect(profileValueText({ unknown: "value" }, true)).toBeUndefined();
    expect(profileValueText([{ region: "Москва" }], false)).toBeUndefined();
  });
});
