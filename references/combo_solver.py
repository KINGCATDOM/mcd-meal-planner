#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
组合求解器：套餐组合、三档方案、凑单陷阱检测、聚餐配比。

本 Skill 的核心场景（套餐推荐 / 麦门省钱 / 聚餐一键点）主线都是
「在目标和预算下，找出最划算的一单」，所以这里以价格优化为主。
营养相关求解见 nutrition_helper.py。

为什么需要本地求解？
    接口限流 600 次/分钟。若把每一种组合都丢给 calculate-price 试错，
    一局对话就能把额度打光。本脚本先在本地枚举、过滤、排序，
    只把 Top-K 候选交给远程算价。

    实测：22 主餐 × 5 小食 × 11 饮品 = 1210 个组合全部本地算完，
    远程调用 0 次。

重要：本脚本只负责"缩小候选集"，不能替代官方算价。
     最终价格、优惠可用性、商品状态一律以 calculate-price 返回为准。

用法：
    from combo_solver import Item, Budget, solve, split_catalog
    from combo_solver import find_threshold_upgrade, party_plan, three_tiers
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Item:
    """一个可点商品。价格单位统一为「元」，调用方负责把接口的「分」换算过来。"""
    name: str
    price: float                      # 元
    code: str | None = None           # 餐品编码（对应接口的 productCode）
    category: str = "main"            # main / side / drink / dessert / combo / extra
    tags: list[str] = field(default_factory=list)
    # 营养字段可选，不传不参与计算
    energy_kcal: float | None = None
    protein: float | None = None
    sodium: float | None = None


@dataclass
class Budget:
    max_price: float | None = None
    min_price: float | None = None
    # 营养约束可选
    max_kcal: float | None = None
    min_protein: float | None = None
    max_sodium: float | None = None


@dataclass
class Combo:
    items: list[Item]
    price: float

    @property
    def names(self) -> list[str]:
        return [i.name for i in self.items]

    def total(self, attr: str) -> float:
        return sum(getattr(i, attr) or 0.0 for i in self.items)

    def violates(self, b: Budget) -> list[str]:
        """返回违反的约束名列表，空列表表示满足。"""
        bad: list[str] = []
        if b.max_price is not None and self.price > b.max_price:
            bad.append("price")
        if b.min_price is not None and self.price < b.min_price:
            bad.append("price_min")
        if b.max_kcal is not None and self.total("energy_kcal") > b.max_kcal:
            bad.append("kcal")
        if b.min_protein is not None and self.total("protein") < b.min_protein:
            bad.append("protein")
        if b.max_sodium is not None and self.total("sodium") > b.max_sodium:
            bad.append("sodium")
        return bad

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [
                {"name": i.name, "code": i.code, "price": round(i.price, 2),
                 "category": i.category}
                for i in self.items
            ],
            "price": round(self.price, 2),
            "kcal": round(self.total("energy_kcal"), 1),
            "protein": round(self.total("protein"), 1),
            "sodium": round(self.total("sodium"), 1),
        }


def build_combo(items: list[Item]) -> Combo:
    return Combo(items=list(items), price=sum(i.price for i in items))


def split_catalog(items: list[Item]) -> tuple[list[Item], list[Item], list[Item]]:
    """按 category 拆成 主餐 / 小食 / 饮品 三个池。"""
    mains = [i for i in items if i.category == "main"]
    sides = [i for i in items if i.category == "side"]
    drinks = [i for i in items if i.category == "drink"]
    return mains, sides, drinks


def _balanced_score(c: Combo) -> float:
    """
    均衡度打分：件数够、有饮品、有套餐的得分高。
    用于"推荐"场景，避免只推最便宜的（可能吃不饱）或最贵的。
    """
    score = 0.0
    n = len(c.items)
    if n >= 3:
        score += 2.0
    elif n == 2:
        score += 1.0
    if any(i.category == "drink" for i in c.items):
        score += 1.0
    if any(i.category == "combo" for i in c.items):
        score += 1.5
    return score


def solve(
    mains: list[Item],
    sides: list[Item],
    drinks: list[Item],
    budget: Budget,
    top_k: int = 5,
    rank: str = "price",
    require_side: bool = True,
    require_drink: bool = True,
) -> dict[str, Any]:
    """
    枚举 主餐 × 小食 × 饮品，按约束过滤后排序取 Top-K。

    rank 选项：
      price       价格最低（S2 最省档）
      balanced    均衡度（推荐场景 / 均衡档）

    require_side / require_drink 设为 False 时，允许该位置为空
    （比如"只要一个汉堡加杯饮料"就不需要小食）。
    """
    feasible: list[Combo] = []
    near_miss: list[Combo] = []
    total = 0

    side_pool = sides if require_side else [None] + list(sides)
    drink_pool = drinks if require_drink else [None] + list(drinks)

    for combo_items in itertools.product(mains, side_pool, drink_pool):
        total += 1
        picked = [x for x in combo_items if x is not None]
        c = build_combo(picked)
        bad = c.violates(budget)
        if not bad:
            feasible.append(c)
        elif len(bad) == 1:
            near_miss.append(c)

    if rank == "balanced":
        feasible.sort(key=lambda c: (-_balanced_score(c), c.price))
    else:
        feasible.sort(key=lambda c: c.price)

    near_miss.sort(key=lambda c: c.price)

    return {
        "feasible": feasible[:top_k],
        "near_miss": near_miss[:top_k],
        "total_evaluated": total,
    }


def find_threshold_upgrade(
    current_total: float,
    catalog: list[Item],
    thresholds: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """
    凑单跨门槛分析 —— S2 的「凑单陷阱」检测核心。

    参数：
      current_total  当前购物车金额（元）
      catalog        可加购的餐品池
      thresholds     [(门槛金额, 减免金额), ...] 例如 [(40, 5), (60, 10)]

    判定：
      net_change < 0  → verdict="worth"  真省钱
      net_change = 0  → verdict="even"   不亏不赚
      net_change > 0  → verdict="trap"   凑单陷阱
    """
    results: list[dict[str, Any]] = []
    pay_before = current_total  # 不凑单则无减免

    for threshold, discount in sorted(thresholds):
        need = threshold - current_total
        if need <= 0:
            continue  # 已经过了这道门槛

        candidates = [i for i in catalog if i.price >= need]
        if not candidates:
            continue
        pick = min(candidates, key=lambda i: i.price)

        new_total = current_total + pick.price
        pay_after = new_total - discount
        net = pay_after - pay_before

        if net < -0.005:
            verdict = "worth"
            note = (f"真省钱：多花 ¥{pick.price:.2f} 但减 ¥{discount:.2f}，"
                    f"净省 ¥{-net:.2f}")
        elif abs(net) <= 0.005:
            verdict = "even"
            note = "不亏不赚，除非你本来就想吃它"
        else:
            verdict = "trap"
            note = (f"凑单陷阱：净多花 ¥{net:.2f} 换一份 {pick.name}，"
                    f"这不是省钱，是多吃")

        results.append({
            "threshold": threshold,
            "discount": discount,
            "need": round(need, 2),
            "add_item": pick.name,
            "add_price": round(pick.price, 2),
            "new_total": round(new_total, 2),
            "pay_before": round(pay_before, 2),
            "pay_after": round(pay_after, 2),
            "net_change": round(net, 2),
            "worth_it": verdict == "worth",
            "verdict": verdict,
            "note": note,
        })

    return results


def three_tiers(candidates: list[Combo]) -> dict[str, Combo | None]:
    """
    S2 的三档方案。

    - cheapest  最省：价格最低
    - balanced  最均衡：均衡度最高
    - fullest   最满足：件数最多，同件数取贵的
    """
    if not candidates:
        return {"cheapest": None, "balanced": None, "fullest": None}

    return {
        "cheapest": min(candidates, key=lambda c: c.price),
        "balanced": max(candidates, key=lambda c: (_balanced_score(c), -c.price)),
        "fullest": max(candidates, key=lambda c: (len(c.items), c.price)),
    }


def party_plan(
    people: int,
    per_person_budget: float,
    catalog: list[Item],
    avoid: list[str] | None = None,
    spicy_ok: bool = True,
) -> dict[str, Any]:
    """
    聚餐方案：先算"够吃"，再算"省钱"。反浪费优先。

    配比原则（宁可少点，让人自己加）：
      主食 = 人数（不 +1）
      小食 = ceil(人数 / 2)
      饮品 = 人数
      优先选分享装（单价更低）
    """
    avoid = avoid or []
    pool = [
        i for i in catalog
        if not any(b in i.name for b in avoid)
        and (spicy_ok or "辣" not in i.name)
    ]

    mains, sides, drinks = split_catalog(pool)
    if not mains:
        return {"error": "catalog 缺少 main 类目，无法组餐"}

    main_pick = min(mains, key=lambda i: i.price)
    n_sides = max(1, math.ceil(people / 2))

    share = [i for i in sides
             if any(k in i.name for k in ("分享", "拼盘", "桶", "多人"))]
    side_pool = share if share else sides
    side_pick = sorted(side_pool, key=lambda i: i.price)[:n_sides]

    drink_pick = min(drinks, key=lambda i: i.price) if drinks else None

    lines: list[dict[str, Any]] = []
    total = 0.0

    def add(item: Item, qty: int) -> None:
        nonlocal total
        sub = item.price * qty
        total += sub
        lines.append({
            "name": item.name, "code": item.code, "qty": qty,
            "unit_price": round(item.price, 2), "subtotal": round(sub, 2),
        })

    add(main_pick, people)
    for s in side_pick:
        add(s, 1)
    if drink_pick:
        add(drink_pick, people)

    target = per_person_budget * people
    return {
        "people": people,
        "target_total": round(target, 2),
        "total": round(total, 2),
        "per_person": round(total / people, 2) if people else 0,
        "over_budget": total > target,
        "remaining": round(target - total, 2),
        "lines": lines,
        "used_share_platter": bool(share),
    }


if __name__ == "__main__":
    # 自测：假数据跑通三条主链路
    catalog = [
        Item("板烧鸡腿堡", 20.0, "M001", "main"),
        Item("双层吉士汉堡", 15.0, "M002", "main"),
        Item("巨无霸", 23.0, "M003", "main"),
        Item("麦辣鸡腿汉堡三件套", 33.5, "M004", "combo"),
        Item("中薯条", 11.0, "S001", "side"),
        Item("小杯玉米杯", 9.5, "S002", "side"),
        Item("麦乐鸡5块", 13.0, "S003", "side"),
        Item("20块分享装", 45.0, "S004", "side"),
        Item("无糖可乐中杯", 0.0, "D001", "drink"),
        Item("可口可乐中杯", 10.0, "D002", "drink"),
    ]
    mains, sides, drinks = split_catalog(catalog)

    print("=== S2 最省档（预算 ≤ ¥35）===")
    r = solve(mains, sides, drinks, Budget(max_price=35), top_k=3, rank="price")
    for c in r["feasible"]:
        print(f"  {' + '.join(c.names)} → ¥{c.price:.2f}")
    if not r["feasible"]:
        print("  无完全满足的方案，以下是最接近的：")
        for c in r["near_miss"]:
            print(f"  {' + '.join(c.names)} → ¥{c.price:.2f}")
    print(f"  评估 {r['total_evaluated']} 个组合（0 次远程调用）")

    print("\n=== S2 凑单陷阱检测（当前 ¥32，满 40 减 5 / 满 60 减 12）===")
    for res in find_threshold_upgrade(32.0, catalog, [(40, 5), (60, 12)]):
        label = {"worth": "✅ 值得", "trap": "⚠️ 别凑", "even": "➖ 不亏不赚"}[res["verdict"]]
        print(f"  门槛 ¥{res['threshold']} 减 ¥{res['discount']} → {label}")
        print(f"    {res['note']}")

    print("\n=== S3 聚餐（4 人 / 人均 40）===")
    p = party_plan(4, 40.0, catalog)
    for ln in p["lines"]:
        print(f"  {ln['name']} ×{ln['qty']} = ¥{ln['subtotal']:.2f}")
    print(f"  合计 ¥{p['total']:.2f}｜人均 ¥{p['per_person']:.2f}｜"
          f"剩余 ¥{p['remaining']:.2f}｜超预算 {p['over_budget']}")
