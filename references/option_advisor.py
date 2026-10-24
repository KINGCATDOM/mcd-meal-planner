# -*- coding: utf-8 -*-
"""
套餐选配建议引擎（option_advisor.py）
====================================

输入 `query-meal-detail` 返回的 `rounds`，按用户画像给出「每轮选什么 + 为什么」。

解决的问题：套餐里每轮有 5–20 个可选项，人工挑容易漏掉「−¥0.5」这种倒找钱项，
也容易在用户说"健身"时推一个油炸汉堡。

用法
----
```python
from option_advisor import advise, format_advice

rounds = detail["data"]["rounds"]     # 直接喂接口返回
advice = advise(rounds, high_protein=True, no_spicy=True)
print(format_advice(advice))
```

画像开关（可组合）
------------------
- `high_protein` 高蛋白优先（健身/增肌）
- `low_cal`     低热量优先（减脂/控卡）
- `no_spicy`    不吃辣
- `cheap`       省钱优先（优先负差价项）
- `sweet`       想吃甜的
- `variety`     尽量不重复（默认开启）
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- 词表

SPICY_KWS = ("辣", "龙焰", "韩式", "山葵", "椒盐", "香辣", "麻辣", "胡椒")

# 蛋白密度高的（不是精确值，只用来排序，不用于报数字）
PROTEIN_KWS = (
    "双层吉士", "板烧", "巨无霸", "安格斯", "培根", "牛肉", "牛堡",
    "麦乐鸡", "纯牛奶", "鸡排", "鸡腿堡", "鳕鱼", "麦香鱼", "芝士",
)

# 油炸 / 高热量表征
HEAVY_KWS = ("大薯", "大杯", "麦旋风", "新地", "派", "脆脆", "鸡翅", "十翅", "那么大")

# 低卡友好
LIGHT_KWS = ("无糖", "纯悦", "水", "玉米杯", "红茶", "纯牛奶", "鲜萃咖啡", "苹果片",
              "板烧", "麦香鱼", "鳕鱼")   # 板烧是煎板烤，不是油炸

# 甜品/甜口
SWEET_KWS = ("枫糖", "新地", "麦旋风", "派", "橙", "冰淇淋", "圆筒", "爆爆珠")

# 饮品判定（用于「饮料轮必须选饮料」这类兜底）
DRINK_KWS = ("可乐", "雪碧", "红茶", "咖啡", "牛奶", "果汁", "怡泉", "柠", "橙", "纯悦", "水")

_ROUND_DRINK_KWS = ("饮料", "饮品", "喝")


# ---------------------------------------------------------------- 工具


def parse_diff(diff) -> float:
    """`"+ ¥2.5"` / `"- ¥0.5"` / `"+ ¥0"` → float。解析失败返回 0。"""
    if diff is None:
        return 0.0
    m = re.search(r"[-+]?\s*¥?\s*(\d+(?:\.\d+)?)", str(diff))
    if not m:
        return 0.0
    v = float(m.group(1))
    return -v if str(diff).strip().startswith("-") else v


def _is_drink(round_name: str) -> bool:
    return any(k in round_name for k in _ROUND_DRINK_KWS)


def _score(choice: dict, round_name: str, flags: dict, used: set[str]) -> float:
    """给单个选项打分。分数越高越推荐。"""
    name = choice.get("name", "")
    diff = parse_diff(choice.get("diffPrice"))
    s = 0.0

    # 差价：便宜就是好（负数更优）。权重给足，因为这是实打实的钱
    s -= diff * 6

    if flags.get("no_spicy") and any(k in name for k in SPICY_KWS):
        s -= 1000          # 直接排除

    if flags.get("high_protein"):
        if any(k in name for k in PROTEIN_KWS):
            s += 6
        if any(k in name for k in ("鸡翅", "十翅", "脆脆", "薯条", "薯饼")):
            s -= 2          # 纯油/纯碳水，对蛋白没贡献

    if flags.get("low_cal"):
        if any(k in name for k in LIGHT_KWS):
            s += 6
        if any(k in name for k in HEAVY_KWS):
            s -= 5
        # 油炸类汉堡：麦辣/龙焰/脆皮/鸡翅 都是炸的，低卡时不优先
        if any(k in name for k in ("辣", "龙焰", "脆皮", "鸡翅", "十翅")):
            s -= 4

    if flags.get("sweet"):
        if any(k in name for k in SWEET_KWS):
            s += 5

    if flags.get("cheap"):
        if diff < 0:
            s += 5
        elif diff > 0:
            s -= 4

    # 饮料轮：不选饮料要扣分（避免"玉米杯当饮料"这种奇怪组合，除非用户要低卡）
    if _is_drink(round_name) and not flags.get("low_cal"):
        if any(k in name for k in DRINK_KWS):
            s += 2

    # 多样性：同一轮里避免重复（quantity=2 时第二份会扣分）
    if flags.get("variety", True) and name in used:
        s -= 1.5

    return s


# ---------------------------------------------------------------- 主函数


def advise(rounds: list[dict], **flags) -> list[dict]:
    """
    对每一轮给出建议。

    返回 `[{round, need, picks: [{name, diff, default}], changed, reason}]`
    """
    out: list[dict] = []
    for rd in rounds or []:
        name = rd.get("name") or f"第{rd.get('id')}轮"
        need = rd.get("quantity") or rd.get("maxQuantity") or 1
        if need == -1:          # maxQuantity=-1 表示不限，按 1 处理
            need = 1
        choices = rd.get("choices") or []
        if not choices:
            continue

        used: set[str] = set()
        picks = []
        for _ in range(max(1, int(need))):
            ranked = sorted(
                choices,
                key=lambda c: (-_score(c, name, flags, used),
                               parse_diff(c.get("diffPrice")),
                               c.get("name", "")),
            )
            if not ranked:
                break
            best = ranked[0]
            picks.append({
                "name": best.get("name", ""),
                "diff": parse_diff(best.get("diffPrice")),
                "default": bool(best.get("isDefault")),
            })
            used.add(best.get("name", ""))

        # 默认组合长什么样
        defaults = [c for c in choices if c.get("isDefault") == 1]
        default_names = {c.get("name") for c in defaults}
        chosen_names = {p["name"] for p in picks}
        changed = bool(default_names) and not chosen_names.issubset(default_names)

        total_diff = sum(p["diff"] for p in picks)
        reasons = []
        goal = []
        if flags.get("high_protein"):
            goal.append("高蛋白")
        if flags.get("low_cal"):
            goal.append("低卡")
        if flags.get("sweet"):
            goal.append("甜口")
        if flags.get("no_spicy"):
            goal.append("不辣")
        if goal:
            reasons.append("按" + "/".join(goal) + "选")
        if total_diff < 0:
            reasons.append(f"倒找 ¥{abs(total_diff):.2f}")
        elif total_diff > 0:
            reasons.append(f"加价 ¥{total_diff:.2f}")
        if not changed:
            reasons.append("默认已最优")

        out.append({
            "round": name,
            "need": need,
            "picks": picks,
            "changed": changed,
            "delta": round(total_diff, 2),
            "reason": "；".join(reasons) if reasons else "",
        })
    return out


def format_advice(advice: list[dict]) -> str:
    """转成可以直接贴进回复的表格 + 一句话结论。"""
    if not advice:
        return "（没有可选项）"
    rows = ["| 轮次 | 建议选 | 差价 | 说明 |", "|---|---|---|---|"]
    total = 0.0
    for a in advice:
        names = " + ".join(p["name"] for p in a["picks"])
        delta = a["delta"]
        total += delta
        d = "—" if delta == 0 else (f"−¥{abs(delta):.2f}" if delta < 0 else f"+¥{delta:.2f}")
        tag = "✅ 建议改" if a["changed"] else "默认即可"
        rows.append(f"| {a['round']} ×{a['need']} | {names} | {d} | {tag}；{a['reason']} |")
    tail = ""
    if total < 0:
        tail = f"\n\n**合计比默认便宜 ¥{abs(total):.2f}**"
    elif total > 0:
        tail = f"\n\n**合计比默认贵 ¥{total:.2f}**"
    else:
        tail = "\n\n**与默认同价**"
    return "\n".join(rows) + tail


# ---------------------------------------------------------------- 自测

if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    # 麦麦周末双人餐（9900015151）真实 rounds，门店 3350337，2026-10-24
    ROUNDS = [
        {"id": 1, "name": "枫糖风味厚松饼猪柳蛋堡", "quantity": 1,
         "choices": [{"code": "521730", "name": "枫糖风味厚松饼猪柳蛋堡",
                      "isDefault": 1, "diffPrice": "+ ¥0"}]},
        {"id": 2, "name": "选择汉堡", "quantity": 1, "choices": [
            {"code": "1440", "name": "麦辣鸡腿汉堡", "isDefault": 1, "diffPrice": "+ ¥0"},
            {"code": "1406", "name": "板烧鸡腿堡", "isDefault": 0, "diffPrice": "+ ¥1"},
        ]},
        {"id": 3, "name": "选择套餐内小食", "quantity": 2, "choices": [
            {"code": "4810", "name": "中薯条", "isDefault": 1, "diffPrice": "+ ¥0"},
            {"code": "521741", "name": "脆薯饼", "isDefault": 0, "diffPrice": "+ ¥0"},
            {"code": "4820", "name": "大薯条", "isDefault": 0, "diffPrice": "+ ¥2.5"},
            {"code": "4437", "name": "小杯玉米杯", "isDefault": 0, "diffPrice": "- ¥0.5"},
            {"code": "4438", "name": "大杯玉米杯", "isDefault": 0, "diffPrice": "+ ¥2.5"},
            {"code": "514782", "name": "脆脆薯条", "isDefault": 0, "diffPrice": "+ ¥2.5"},
        ]},
        {"id": 4, "name": "选择套餐内饮料", "quantity": 2, "choices": [
            {"code": "3050", "name": "可乐中杯", "isDefault": 1, "diffPrice": "+ ¥0"},
            {"code": "520689", "name": "小杯鲜萃咖啡", "isDefault": 0, "diffPrice": "+ ¥0"},
            {"code": "521817", "name": "【美汁源】“多汁柠柠”", "isDefault": 0, "diffPrice": "+ ¥1"},
            {"code": "3071", "name": "无糖可口可乐中杯", "isDefault": 0, "diffPrice": "+ ¥0"},
            {"code": "3060", "name": "雪碧中杯", "isDefault": 0, "diffPrice": "+ ¥0"},
            {"code": "515281", "name": "阳光柠檬红茶中杯", "isDefault": 0, "diffPrice": "+ ¥0"},
            {"code": "3755", "name": "纯牛奶", "isDefault": 0, "diffPrice": "+ ¥0.5"},
            {"code": "3100", "name": "可乐大杯", "isDefault": 0, "diffPrice": "+ ¥2"},
            {"code": "3505", "name": "锡兰红茶", "isDefault": 0, "diffPrice": "+ ¥1.5"},
        ]},
    ]

    P = {"no_spicy": True, "high_protein": True}
    L = {"low_cal": True}
    C = {"cheap": True}

    print("=== 场景 A：健身（高蛋白 + 不吃辣）===")
    print(format_advice(advise(ROUNDS, **P)))

    print("\n=== 场景 B：减脂（低卡）===")
    print(format_advice(advise(ROUNDS, **L)))

    print("\n=== 场景 C：只求便宜 ===")
    print(format_advice(advise(ROUNDS, **C)))

    print("\n=== 校验 ===")
    a = advise(ROUNDS, **P)
    spicy = [x["name"] for r in a for x in r["picks"] if "辣" in x["name"]]
    print(f"  不吃辣：挑出的辣味项 {spicy or '无'}  {'OK' if not spicy else 'FAIL'}")
    ch = advise(ROUNDS, **C)
    fries = next(r for r in ch if r["need"] == 2)
    print(f"  省钱：小食轮选 {[p['name'] for p in fries['picks']]}（应含小杯玉米杯）")
    print(f"  默认不变时 changed=False：", [r["changed"] for r in a])
