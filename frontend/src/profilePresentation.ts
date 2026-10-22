const blockLabels: Record<string, string> = {
  Идентификация: "Сведения о компании",
  Бизнес: "Деятельность и финансы",
  География: "Регионы работы и поставок",
  Среда: "Рынок и регулирование",
};

export function profileBlockLabel(block: string): string {
  return blockLabels[block] ?? (block || "Другие сведения");
}

function scalar(value: unknown): string | undefined {
  if (value === null || value === undefined || value === "") return "Не указано";
  if (typeof value === "string") return value;
  if (typeof value === "number") return value.toLocaleString("ru-RU");
  if (typeof value === "boolean") return value ? "Да" : "Нет";
  return undefined;
}

// These names describe only the prepared demo fixtures, not an assumed Go contract.
const demoFields: Record<string, string> = {
  status: "Статус", region: "Регион", industry: "Отрасль", revenue: "Выручка",
  currency: "Валюта", year: "Год", employees: "Численность сотрудников",
  floatingRateShare: "Доля долга с плавающей ставкой",
  importedComponentsShare: "Доля импортных комплектующих",
};

export function profileValueText(value: unknown, demo: boolean): string | undefined {
  const simple = scalar(value);
  if (simple !== undefined) return simple;
  if (Array.isArray(value)) {
    const values = value.map(scalar);
    return values.every((item) => item !== undefined) ? values.join("; ") : undefined;
  }
  if (!demo || typeof value !== "object" || value === null) return undefined;
  const entries = Object.entries(value);
  if (!entries.length || entries.some(([key, item]) => !demoFields[key] || scalar(item) === undefined)) return undefined;
  return entries.map(([key, item]) => {
    const text = key === "year" ? String(item) : key === "currency" && item === "RUB" ? "Рубли" :
      (key === "floatingRateShare" || key === "importedComponentsShare") && typeof item === "number"
        ? item.toLocaleString("ru-RU", { style: "percent", maximumFractionDigits: 1 }) : scalar(item);
    return `${demoFields[key]}: ${text}`;
  }).join("\n");
}
