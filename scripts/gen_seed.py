#!/usr/bin/env python3
"""Генерирует backend/migrations/0002_seed.sql из company_research.xlsx.

Использование:
    pip install openpyxl
    python3 scripts/gen_seed.py company_research.xlsx > backend/migrations/0002_seed.sql
"""
import re
import sys

import openpyxl

# Коды ролей стабильны и используются во фронтенде и API.
ROLE_CODES = {
    "Директор по стратегии и развитию": "strategy",
    "Коммерческий директор": "commercial",
    "Директор по закупкам": "procurement",
    "Директор по продажам": "sales",
    "Финансовый директор": "cfo",
    "Генеральный директор": "ceo",
    "Директор по маркетингу": "marketing",
    "Директор по продукту / технический директор": "product",
    "Директор по персоналу / операционный / ИТ-директор": "operations",
}

# Короткие названия ролей в колонке «Роль» листа источников.
ROLE_SHORT = {
    "Стратегия": "strategy",
    "Коммерческий": "commercial",
    "Закупки": "procurement",
    "Продажи": "sales",
    "Финансовый": "cfo",
    "Генеральный": "ceo",
    "Маркетинг": "marketing",
    "Продукт / техн.": "product",
}

ELEMENT_RE = re.compile(r"^[ИБГСО]\d+$")


def q(v):
    if v is None:
        return "''"
    return "'" + str(v).strip().replace("'", "''") + "'"


def main(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    out = ["-- Сгенерировано scripts/gen_seed.py из company_research.xlsx. Не редактировать вручную."]

    ws = wb["1. Профиль компании"]
    elements = set()
    for row in ws.iter_rows(min_row=4, values_only=True):
        code = (row[0] or "").strip() if isinstance(row[0], str) else None
        if not code or not ELEMENT_RE.match(code):
            continue
        elements.add(code)
        out.append(
            "INSERT INTO profile_elements (code, block, name, description, purpose) VALUES "
            f"({q(code)}, {q(row[1])}, {q(row[2])}, {q(row[3])}, {q(row[4])});"
        )

    ws = wb["2. Роли директоров"]
    current = None
    for row in ws.iter_rows(min_row=5, values_only=True):
        if row[0]:
            name = str(row[0]).strip()
            current = ROLE_CODES.get(name)
            if current is None:
                sys.exit(f"неизвестная роль: {name!r}, добавьте её в ROLE_CODES")
            out.append(
                "INSERT INTO roles (code, name, question, focus) VALUES "
                f"({q(current)}, {q(name)}, {q(row[1])}, {q(row[2])});"
            )
        code = str(row[3]).strip() if row[3] else None
        if current and code in elements:
            out.append(
                "INSERT INTO role_profile_elements (role_id, element_code) "
                f"SELECT id, {q(code)} FROM roles WHERE code = {q(current)} ON CONFLICT DO NOTHING;"
            )

    ws = wb["3. Источники"]
    for row in ws.iter_rows(min_row=5, values_only=True):
        sid = row[0]
        if not sid or not str(sid).startswith("S"):
            continue
        adapter = "'alfa'" if row[1] == "Альфа-Банк" else "NULL"
        if adapter == "NULL" and row[5] and "RSS" in str(row[5]):
            adapter = "'rss'"
        out.append(
            "INSERT INTO sources (id, category, name, url, api_access, adapter) VALUES "
            f"({q(sid)}, {q(row[1])}, {q(row[2])}, {q(row[3])}, {q(row[5])}, {adapter});"
        )
        for line in str(row[6] or "").splitlines():
            code = line.split(" ", 1)[0].strip()
            if code in elements:
                out.append(
                    "INSERT INTO source_profile_elements (source_id, element_code) VALUES "
                    f"({q(sid)}, {q(code)}) ON CONFLICT DO NOTHING;"
                )

    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "company_research.xlsx")
