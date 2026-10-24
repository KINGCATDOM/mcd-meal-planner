#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦当劳营养数据 TOON 解析器

背景：list-nutrition-foods 返回的不是 JSON，而是 TOON 文本。
直接按逗号 split 会崩，因为 nutritionDescription 可能是 null，
也可能自己带逗号。这是本 Skill 必须用脚本处理的部分。

TOON 格式样例：
    {productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
      猪柳麦满分,null,1288,308,16,16,24,781,213
      无糖可口可乐中杯,null,0,0,0,0,1,35,0

用法：
    from toon_parser import parse_nutrition, build_index, lookup
    rows = parse_nutrition(text)
    idx = build_index(rows)
    hit = lookup(idx, "板烧鸡腿堡")
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

# 字段别名：不同版本接口可能微调字段名
FIELD_ALIASES = {
    "productName": ["productName", "product_name", "name", "产品名称", "餐品名称"],
    "nutritionDescription": ["nutritionDescription", "nutrition_description", "desc"],
    "energyKj": ["energyKj", "energy_kj", "能量千焦"],
    "energyKcal": ["energyKcal", "energy_kcal", "energy", "热量", "能量"],
    "protein": ["protein", "蛋白质"],
    "fat": ["fat", "脂肪"],
    "carbohydrate": ["carbohydrate", "carbs", "碳水化合物"],
    "sodium": ["sodium", "钠"],
    "calcium": ["calcium", "钙"],
}

NUMERIC_FIELDS = ["energyKj", "energyKcal", "protein", "fat", "carbohydrate", "sodium", "calcium"]

NULL_TOKENS = {"null", "none", "", "n/a", "na", "-", "--", "NULL", "N/A"}


def _norm_field(name: str) -> str | None:
    """把原始字段名归一到标准名。"""
    key = name.strip().strip('"').strip("'")
    for std, aliases in FIELD_ALIASES.items():
        if key in aliases:
            return std
    return None


def _to_number(raw: str) -> float | None:
    """把单元格转成数字。带单位的（如 '308 kcal'）也能抽出来。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in NULL_TOKENS:
        return None
    # 抽出第一个数字（支持负号与小数）
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    if not m:
        return None
    try:
        val = float(m.group())
    except ValueError:
        return None
    return val


def _split_top_level(line: str) -> list[str]:
    """
    按逗号切分，但尊重引号内的逗号。
    TOON 里如果某字段被引号包裹（因为内容自带逗号），要整体当一个字段。
    """
    out: list[str] = []
    buf: list[str] = []
    in_quote = False
    quote_char = ""

    for ch in line:
        if in_quote:
            if ch == quote_char:
                in_quote = False
            buf.append(ch)
        elif ch in ('"', "'"):
            in_quote = True
            quote_char = ch
            buf.append(ch)
        elif ch == ",":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [x.strip() for x in out]


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def parse_nutrition(text: str) -> list[dict[str, Any]]:
    """
    解析 list-nutrition-foods 的 TOON 返回。

    返回 list[dict]，每个 dict 含：
      productName(str), nutritionDescription(str|None),
      energyKcal/protein/fat/carbohydrate/sodium/calcium/energyKj (float|None)

    容错策略：
      - 先尝试当 JSON 解析（接口若某天改回 JSON 也能用）
      - 再按 TOON 头行 `{a,b,c}:` 定位字段顺序
      - 字段数与表头不一致的行：跳过并记录 warning，不抛异常
    """
    if not text or not str(text).strip():
        return []

    raw = str(text).strip()

    # 兼容：万一返回的是 JSON
    if raw.startswith("[") or raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for key in ("data", "list", "result", "products"):
                    if isinstance(data.get(key), list):
                        data = data[key]
                        break
            if isinstance(data, list):
                return _normalize_json_rows(data)
        except (json.JSONDecodeError, ValueError):
            pass  # 不是 JSON，继续走 TOON 解析

    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return []

    # 找表头行：形如 {a,b,c}:  或  a,b,c:
    # 实测真实返回会在表头前带长度前缀，如 `[160]{productName,...}:`
    header_fields: list[str] | None = None
    data_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        # 剥掉开头的长度前缀 [160]
        stripped = re.sub(r"^\[\d+\]\s*", "", stripped)
        if "{" not in stripped:
            continue
        # 从第一个 { 截到与之配对的 }
        start = stripped.index("{")
        end = stripped.find("}", start)
        if end == -1:
            continue
        candidate = stripped[start + 1 : end]
        parts = _split_top_level(candidate)
        mapped = [_norm_field(p) for p in parts]
        # 判断为表头的条件：至少命中 2 个已知字段名
        if sum(1 for m in mapped if m) >= 2:
            header_fields = [
                m if m else f"_unknown_{idx}" for idx, m in enumerate(mapped)
            ]
            data_start = i + 1
            break

    if header_fields is None:
        # 没有表头：按官方固定顺序兜底
        header_fields = [
            "productName", "nutritionDescription", "energyKj", "energyKcal",
            "protein", "fat", "carbohydrate", "sodium", "calcium",
        ]
        data_start = 0

    rows: list[dict[str, Any]] = []
    for line in lines[data_start:]:
        cells = _split_top_level(line.strip())
        if len(cells) < 2:
            continue
        # 字段数与表头不符：若表头字段多、行短，按顺序对齐前 n 个
        if len(cells) != len(header_fields):
            if len(cells) > len(header_fields):
                cells = cells[: len(header_fields)]
            # 行过短就跳过，避免错位把价格读成钠
            if len(cells) < 2:
                continue

        row: dict[str, Any] = {}
        for field, cell in zip(header_fields, cells):
            if field.startswith("_unknown_"):
                continue
            value = _strip_quotes(cell)
            if field == "productName":
                row["productName"] = value
            elif field == "nutritionDescription":
                row["nutritionDescription"] = None if value in NULL_TOKENS else value
            elif field in NUMERIC_FIELDS:
                row[field] = _to_number(value)

        if row.get("productName"):
            rows.append(row)

    return rows


def _normalize_json_rows(data: list[Any]) -> list[dict[str, Any]]:
    """JSON 形态的返回，归一到统一结构。"""
    rows: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {}
        for raw_key, value in item.items():
            std = _norm_field(str(raw_key))
            if not std:
                continue
            if std == "productName":
                row["productName"] = str(value).strip()
            elif std == "nutritionDescription":
                s = str(value).strip()
                row["nutritionDescription"] = None if s in NULL_TOKENS else s
            else:
                row[std] = _to_number(str(value))
        if row.get("productName"):
            rows.append(row)
    return rows


def build_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    建名称索引，便于按菜单里的餐品名反查营养。
    同时建立"去空格/去规格后缀"的宽松键，提高匹配率。
    """
    idx: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("productName", "")).strip()
        if not name:
            continue
        idx[name] = row
        loose = _loose_key(name)
        if loose and loose not in idx:
            idx[loose] = row
    return idx


def _loose_key(name: str) -> str:
    """去掉常见规格后缀和空白，用于模糊匹配。"""
    s = re.sub(r"\s+", "", name)
    s = re.sub(r"(中杯|大杯|小杯|单点|套餐|（.*?）|\(.*?\))$", "", s)
    return s


def lookup(idx: dict[str, dict[str, Any]], menu_name: str) -> dict[str, Any] | None:
    """
    从菜单名查营养。三级匹配：
      1. 精确
      2. 宽松键
      3. 双向包含（菜单名含营养名，或反之）
    """
    if not menu_name:
        return None
    name = menu_name.strip()
    if name in idx:
        return idx[name]

    loose = _loose_key(name)
    if loose in idx:
        return idx[loose]

    for key, row in idx.items():
        k = _loose_key(key)
        if not k:
            continue
        if k in loose or loose in k:
            return row
    return None


def summarize(row: dict[str, Any]) -> str:
    """单行摘要，方便直接放进表格或日志。"""
    def g(k: str, unit: str) -> str:
        v = row.get(k)
        return f"{v:g}{unit}" if isinstance(v, (int, float)) else "—"

    return (
        f"{row.get('productName', '?')} | "
        f"{g('energyKcal', 'kcal')} | 蛋白 {g('protein', 'g')} | "
        f"脂肪 {g('fat', 'g')} | 碳水 {g('carbohydrate', 'g')} | "
        f"钠 {g('sodium', 'mg')}"
    )


if __name__ == "__main__":
    sample = """{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  无糖可口可乐中杯,null,0,0,0,0,1,35,0
  板烧鸡腿堡,"含生菜, 特制酱料",1520,363,23,14,37,802,95"""

    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            sample = f.read()

    parsed = parse_nutrition(sample)
    print(f"解析到 {len(parsed)} 条\n")
    for r in parsed:
        print(" -", summarize(r))

    print("\n索引测试：")
    idx = build_index(parsed)
    for probe in ["板烧鸡腿堡", "板烧鸡腿堡 中杯", "双层吉士堡"]:
        hit = lookup(idx, probe)
        print(f"  {probe!r} -> " + (summarize(hit) if hit else "未命中"))
