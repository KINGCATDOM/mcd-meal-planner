#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
营养配餐辅助：安全匹配、套餐热量累加、控卡/口味配餐求解。

为什么需要这个脚本？
    「按热量配套餐」听起来简单，实测有两个坑会让结果错得很离谱：

    坑 1｜套餐被错配成单品热量
        lookup("麦辣鸡腿汉堡三件套") 会模糊命中「麦辣鸡腿汉堡」→ 485 kcal
        真实值应为 汉堡485 + 中薯289 + 可乐147 = 921 kcal
        低估 47%。用它做减脂建议，等于在骗人。

    坑 2｜营养表只收录单品，套餐/新品/周边一律没有
        实测 113 个菜单餐品，匹配率 51.3%。剩下 48.7% 里：
          套餐/组合装 22 个、周边商品 5 个、新品及未收录单品 28 个

    所以本脚本的核心不是"算得更准"，而是"该拒绝时坚决拒绝"。
    套餐一律拆 round 累加；查不到就返回 None，由上层如实告诉用户"官方无数据"。

用法：
    from nutrition_helper import safe_lookup, combo_kcal, control_calorie_plan
"""

from __future__ import annotations

import re
from typing import Any

# 套餐/组合装关键字：命中则禁止直接匹配单条营养数据，必须拆 round
COMBO_MARKERS = (
    "三件套", "四件套", "五件套", "套餐", "双人餐", "亲子餐",
    "随心选", "随心配", "小食盘", "分享", "拼盘", "组盒",
    "件任选", "全盒", "桶",
)

# 周边商品：本就没有营养数据，直接排除出配餐候选
MERCH_MARKERS = ("帽", "徽章", "丝巾", "按摩捶", "痒痒挠", "百宝袋", "棒球帽")

# 口味关键词（基于菜名 + tags 推断，官方无结构化口味字段）
FLAVOR_RULES: dict[str, tuple[str, ...]] = {
    "辣": ("辣", "辣椒", "香辛", "龙焰", "韩式辣"),
    "芝士奶香": ("芝士", "奶香", "拉丝", "奶铁", "牛奶", "奶冻"),
    "咖喱": ("咖喱",),
    "甜": ("甜", "糖", "枫糖", "蓝莓", "草莓", "冰淇淋", "新地", "麦旋风",
           "派", "拉明顿", "朱古力", "黑巧"),
    "咖啡": ("咖啡", "美式", "卡布奇诺", "玛奇朵", "雪冰"),
    "清爽果味": ("苹果", "橙", "柠檬", "红茶", "雪碧", "怡泉", "蔬", "沙拉"),
}

# 蛋白质来源（用于忌口过滤）
PROTEIN_RULES: dict[str, tuple[str, ...]] = {
    "牛": ("牛", "安格斯", "吉士", "巨无霸"),
    "鸡": ("鸡", "翅", "麦乐鸡", "鸡排", "鸡腿", "鸡球"),
    "鱼": ("鱼", "鳕"),
    "猪": ("猪", "板烧"),
}


def is_combo(name: str) -> bool:
    return any(k in name for k in COMBO_MARKERS)


def is_merch(name: str) -> bool:
    return any(k in name for k in MERCH_MARKERS)


def safe_lookup(idx: dict[str, Any], name: str, lookup_fn=None) -> dict[str, Any] | None:
    """
    安全查营养：套餐名一律不返回单品数据（避免低估 47%）。

    lookup_fn 传入 toon_parser.lookup；为 None 时只做精确匹配。
    """
    if not name:
        return None
    if is_combo(name):
        return None          # 套餐必须走 combo_kcal 拆 round
    if is_merch(name):
        return None          # 周边无营养数据
    if lookup_fn is None:
        return idx.get(name.strip())
    return lookup_fn(idx, name)


def combo_kcal(
    detail: dict[str, Any],
    idx: dict[str, Any],
    lookup_fn=None,
) -> dict[str, Any]:
    """
    套餐热量 = 各 round 默认选项的热量之和。

    detail 来自 query-meal-detail 的 data 字段。
    每个 round 取 isDefault=1 的 choices（通常每轮 1 个）。

    返回：
      {
        "total_kcal": float | None,     # None 表示有子项查不到
        "parts": [{round, name, code, kcal|None}],
        "missing": [子项名],            # 缺营养数据的子项
        "complete": bool,               # 是否全部子项都有数据
      }
    """
    rounds = (detail or {}).get("rounds") or []
    parts: list[dict[str, Any]] = []
    missing: list[str] = []
    total = 0.0

    for rnd in rounds:
        choices = rnd.get("choices") or []
        picked = [c for c in choices if c.get("isDefault") == 1]
        if not picked:
            continue
        for ch in picked:
            cname = ch.get("name", "")
            row = safe_lookup(idx, cname, lookup_fn)
            kcal = row.get("energyKcal") if row else None
            parts.append({
                "round": rnd.get("name", ""),
                "name": cname,
                "code": ch.get("code"),
                "kcal": kcal,
            })
            if kcal is None:
                missing.append(cname)
            else:
                total += float(kcal)

    return {
        "total_kcal": round(total, 1) if not missing else None,
        "parts": parts,
        "missing": missing,
        "complete": not missing,
    }


def flavor_tags(name: str, tags: list[str] | None = None) -> list[str]:
    """口味归类：菜名 + tags 双通道关键词匹配。"""
    blob = (name or "") + " " + " ".join(tags or [])
    return [f for f, kws in FLAVOR_RULES.items() if any(k in blob for k in kws)]


def protein_source(name: str) -> list[str]:
    """蛋白质来源归类，用于「不吃牛」「想吃鸡」这类忌口/偏好过滤。"""
    return [p for p, kws in PROTEIN_RULES.items() if any(k in name for k in kws)]


def control_calorie_plan(
    candidates: list[dict[str, Any]],
    max_kcal: float,
    min_protein: float | None = None,
    want_flavors: list[str] | None = None,
    avoid_protein: list[str] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """
    控卡配餐：在热量上限内，挑饱腹感与满足度最好的组合。

    candidates 每项需含：name / code / price(元) / kcal / protein / category
    category 取 main / side / drink / dessert

    选法（不是单纯挑热量最低）：
      主食选热量合适的（太低的吃不饱，太高的爆卡）
      饮品优先 0 卡的（无糖可乐实测 0 kcal，这是最划算的替换）
      小食按剩余热量预算补

    返回 {mains, sides, drinks, total_kcal, total_price, warnings}
    """
    def usable(c: dict[str, Any]) -> bool:
        if c.get("kcal") is None:
            return False
        if avoid_protein and set(protein_source(c.get("name", ""))) & set(avoid_protein):
            return False
        if want_flavors:
            got = flavor_tags(c.get("name", ""), c.get("tags"))
            if not (set(got) & set(want_flavors)):
                return False
        return True

    pool = [c for c in candidates if usable(c)]
    mains = [c for c in pool if c.get("category") == "main"]
    sides = [c for c in pool if c.get("category") == "side"]
    drinks = [c for c in pool if c.get("category") == "drink"]

    warnings: list[str] = []
    if not mains:
        return {"error": "没有符合条件且有营养数据的主食，无法配餐",
                "hint": "放宽口味/忌口条件，或换一个主食"}

    # 饮品：优先 0 卡，其次热量最低
    drink = min(drinks, key=lambda c: c["kcal"]) if drinks else None
    if drink and drink["kcal"] == 0:
        warnings.append(f"{drink['name']} 实测 0 kcal，是不花热量预算的替换项")

    # 主食：优先「热量不超过预算 60%」的里面蛋白最高的，都不满足就取最低
    budget_main = max_kcal * 0.6
    ok_mains = [m for m in mains if m["kcal"] <= budget_main]
    if ok_mains:
        main = max(ok_mains, key=lambda c: (c.get("protein") or 0, -c["kcal"]))
    else:
        main = min(mains, key=lambda c: c["kcal"])
        warnings.append(f"没有主食能压在 {budget_main:.0f} kcal 内，已选最低的 {main['name']}")

    used = main["kcal"] + (drink["kcal"] if drink else 0)
    remaining = max_kcal - used

    # 小食：在剩余预算内挑热量最高的（尽量吃饱），一个都放不下就不加
    side = None
    fit_sides = [s for s in sides if s["kcal"] <= remaining]
    if fit_sides:
        side = max(fit_sides, key=lambda c: c["kcal"])
    elif sides:
        cheapest_side = min(sides, key=lambda c: c["kcal"])
        warnings.append(
            f"加任何小食都会超 {max_kcal:.0f} kcal（最轻的 {cheapest_side['name']} "
            f"{cheapest_side['kcal']:.0f} kcal），建议只吃主食+饮品"
        )

    picked = [x for x in (main, side, drink) if x]
    total_kcal = sum(x["kcal"] for x in picked)
    total_price = sum(float(x.get("price") or 0) for x in picked)

    return {
        "items": picked,
        "total_kcal": round(total_kcal, 1),
        "total_price": round(total_price, 2),
        "budget_kcal": max_kcal,
        "remaining_kcal": round(max_kcal - total_kcal, 1),
        "total_protein": round(sum(float(x.get("protein") or 0) for x in picked), 1),
        "warnings": warnings,
        "suggest_empty_sides": not side,
        "alternatives": mains[:top_k],
    }


def swap_saving(idx: dict[str, Any], from_name: str, to_name: str, lookup_fn=None) -> dict[str, Any] | None:
    """
    同轮替换的热量差 —— 「换个小食省 236 kcal」这种结论用它算。

    实测案例：中薯条 289 kcal → 小杯玉米杯 53 kcal，省 236 kcal 且便宜 ¥0.5
    """
    a = safe_lookup(idx, from_name, lookup_fn)
    b = safe_lookup(idx, to_name, lookup_fn)
    if not a or not b:
        return None
    return {
        "from": from_name, "to": to_name,
        "from_kcal": a["energyKcal"], "to_kcal": b["energyKcal"],
        "kcal_saved": round(float(a["energyKcal"]) - float(b["energyKcal"]), 1),
        "sodium_saved": round(float(a.get("sodium") or 0) - float(b.get("sodium") or 0), 1),
    }


if __name__ == "__main__":
    import io
    import os
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    # 用真实营养表片段自测
    from toon_parser import parse_nutrition, build_index, lookup

    sample = """[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  麦辣鸡腿汉堡,null,2029,485,24,24,42,1208,154
  板烧鸡腿堡,null,1638,391,23,17,35,1041,93
  巨无霸,null,2146,513,27,26,42,961,171
  中薯条,null,1210,289,4,12,38,165,18
  小杯玉米杯,null,223,53,2,1,7,1,6
  可乐中杯,null,616,147,0,0,36,0,10
  无糖可口可乐中杯,null,0,0,0,0,1,35,0
  麦乐鸡5块,null,890,213,12,12,13,422,9
"""
    idx = build_index(parse_nutrition(sample))

    print("=== 1. 安全匹配：套餐必须拒绝 ===")
    for n in ["麦辣鸡腿汉堡三件套", "麦辣鸡腿汉堡", "巨无霸三件套", "巨无霸"]:
        r = safe_lookup(idx, n, lookup)
        print(f"  {n:14s} -> " + (f"{r['energyKcal']:.0f} kcal" if r else "拒绝（须拆 round）"))

    print("\n=== 2. 套餐热量拆 round 累加 ===")
    fake_detail = {"rounds": [
        {"name": "主食", "choices": [{"code": "1440", "name": "麦辣鸡腿汉堡", "isDefault": 1}]},
        {"name": "小食", "choices": [{"code": "4810", "name": "中薯条", "isDefault": 1}]},
        {"name": "饮料", "choices": [{"code": "3050", "name": "可乐中杯", "isDefault": 1}]},
    ]}
    res = combo_kcal(fake_detail, idx, lookup)
    print(f"  合计 {res['total_kcal']} kcal（完整={res['complete']}）")
    for p in res["parts"]:
        print(f"    {p['round']:6s} {p['name']:12s} {p['kcal']}")

    print("\n=== 3. 控卡配餐（≤600 kcal）===")
    cands = [
        {"name": "麦辣鸡腿汉堡", "code": "1440", "price": 22.5, "kcal": 485, "protein": 24, "category": "main"},
        {"name": "板烧鸡腿堡", "code": "1406", "price": 23.5, "kcal": 391, "protein": 23, "category": "main"},
        {"name": "中薯条", "code": "4810", "price": 13.5, "kcal": 289, "protein": 4, "category": "side"},
        {"name": "小杯玉米杯", "code": "4437", "price": 13, "kcal": 53, "protein": 2, "category": "side"},
        {"name": "可乐中杯", "code": "3050", "price": 9.5, "kcal": 147, "protein": 0, "category": "drink"},
        {"name": "无糖可口可乐中杯", "code": "3071", "price": 9.5, "kcal": 0, "protein": 0, "category": "drink"},
    ]
    plan = control_calorie_plan(cands, max_kcal=600)
    for it in plan["items"]:
        print(f"  {it['name']:18s} {it['kcal']:5.0f} kcal  ¥{it['price']}")
    print(f"  合计 {plan['total_kcal']} kcal / ¥{plan['total_price']} / 蛋白 {plan['total_protein']}g")
    for w in plan["warnings"]:
        print(f"  ! {w}")

    print("\n=== 4. 同轮替换省多少 ===")
    sw = swap_saving(idx, "中薯条", "小杯玉米杯", lookup)
    print(f"  {sw['from']} → {sw['to']}：省 {sw['kcal_saved']:.0f} kcal、{sw['sodium_saved']:.0f} mg 钠")
