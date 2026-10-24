#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦门挑战套餐生成器

从当前门店真实在售的菜品里，拼出各种「整活」组合，并配上吐槽文案。

设计原则：
    1. 只用传入的菜单数据 —— 不凭空发明菜品，保证推荐的东西真的能点到
    2. 挑战是玩，不追求营养均衡，但**不隐瞒翻车风险**
    3. 吐槽文案损一点没关系，但要具体、不油腻、不空洞

用法：
    from challenge_generator import Item, CHALLENGES, build
    items = [Item("巨无霸", 26.5, "1100", "main", ["100%纯牛肉"]), ...]
    result = build("carb_bomb", items)
    print(result["name"], result["items"], result["roast"])
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Item:
    name: str
    price: float
    code: str = ""
    category: str = "main"          # main / side / drink / dessert / sauce
    tags: list[str] = field(default_factory=list)


# ---------- 品类推断（菜单只给名字和 tags 时用） ----------

DRINK_KWS = ("可乐", "雪碧", "红茶", "咖啡", "牛奶", "果汁", "纯悦", "怡泉",
             "柠柠", "橙橙", "雪冰", "豆浆", "朱古力", "美式", "拿铁", "奶铁",
             "卡布奇诺", "玛奇朵", "阿芙佳朵", "红茶")
DESSERT_KWS = ("麦旋风", "新地", "冰淇淋", "圆筒", "派", "拉明顿", "饼干")
# 注意：「薯饼」属于 SIDE 不属于 DESSERT，别按"甜"误判
SAUCE_KWS = ("酱",)
SIDE_KWS = ("薯条", "薯饼", "麦乐鸡", "鸡翅", "鸡排", "鸡球", "鸡块", "鸡柳",
            "玉米杯", "苹果片", "鸡腿", "V翅", "脆汁鸡", "扭扭薯", "芝士条", "笋卷")


def infer_category(name: str, tags: list[str] | None = None) -> str:
    if any(k in name for k in SAUCE_KWS):
        return "sauce"
    if any(k in name for k in DESSERT_KWS):
        return "dessert"
    if any(k in name for k in DRINK_KWS):
        return "drink"
    if any(k in name for k in SIDE_KWS):
        return "side"
    return "main"


# ---------- 挑战定义 ----------

@dataclass
class Challenge:
    key: str
    name: str
    tagline: str
    pick: Callable[[list[Item]], list[Item]]
    roasts: list[str]
    warning: str
    est_price: str = ""


def _pick_one(pool: list[Item], rng: random.Random) -> Item | None:
    return rng.choice(pool) if pool else None


CHALLENGES: dict[str, Challenge] = {}


def register(c: Challenge) -> None:
    CHALLENGES[c.key] = c


# 1. 一口塞
register(Challenge(
    key="one_bite",
    name="一口塞挑战",
    tagline="所有东西都要能一口进嘴，咀嚼次数不超过 5 次",
    pick=lambda items: [
        i for i in items
        if i.category in ("side", "dessert") and i.price <= 16
        and "杯" not in i.name and "盒" not in i.name
        and "薯条" not in i.name          # 长条状塞不进嘴，这个挑战不成立
        and not any(k in i.name for k in ("8块", "5块", "3块", "4块", "份", "盒", "拼"))
    ][:4],
    roasts=[
        "吃到第三个你会发现，真正的挑战不是塞进去，是咽下去的时候别笑。",
        "建议先拍照，因为你的表情管理最多撑两口。",
        "理论上一口一个，实际上第一个就卡住了 —— 欢迎来到现实。",
    ],
    warning="别真的硬塞，噎住不值得。旁边备一杯饮料。",
))

# 2. 碳水爆炸
register(Challenge(
    key="carb_bomb",
    name="碳水爆炸套餐",
    tagline="主食 + 薯条 + 玉米 + 派 + 冰淇淋，一餐把所有碳水形态集齐",
    pick=lambda items: (
        [i for i in items if i.category == "main"][:1]
        + [i for i in items if i.category == "side" and "薯" in i.name][:1]
        + [i for i in items if "玉米杯" in i.name][:1]
        + [i for i in items if i.category == "dessert"][:2]
    ),
    roasts=[
        "吃完这顿，你的血糖会给你发一条措辞严厉的投诉短信。",
        "这一单的碳水加起来，够你下午开三个会都醒不过来。",
        "不是饭，是一场对胰岛素的压力测试。",
        "别问热量，问就是不知道 —— 反正官方也没收录。",
    ],
    warning="碳水占满一餐容易犯困，下午有重要的事就换个方案。",
))

# 3. 咸甜口
register(Challenge(
    key="sweet_savory",
    name="咸甜口组合",
    tagline="先咸后甜，或者一口咸一口甜，味觉反复横跳",
    pick=lambda items: (
        [i for i in items if i.category == "main"][:1]
        + [i for i in items if i.category == "side"][:1]
        + [i for i in items if i.category == "dessert"][:2]
    ),
    roasts=[
        "咸的吃完想吃甜的，甜的吃完又想吃咸的 —— 这就是无限续杯的开始。",
        "据说这是成年人味觉成熟的标志，也可能只是嘴馋。",
        "这道组合的哲学是：人生苦短，先甜后咸。",
    ],
    warning="冰的甜品配热的主食，肠胃弱的人注意顺序。",
))

# 4. 全辣组合
register(Challenge(
    key="all_spicy",
    name="全辣挑战",
    tagline="菜单上带「辣」字的全点一遍，中间不喝水",
    pick=lambda items: sorted(
        [i for i in items if any(k in i.name for k in ("辣", "龙焰", "韩式辣", "香辣"))],
        key=lambda i: i.price)[:4],
    roasts=[
        "吃完你会理解什么叫「嘴在烧，心在笑，胃在报警」。",
        "建议明天不要安排任何需要开口说话的事。",
        "辣度叠加不是加法，是乘法 —— 而且是在你 unprepared 的时候乘。",
    ],
    warning="辣度叠加对胃刺激大，别逞强；有胃病的直接跳过这个。",
))

# 5. 全鸡宴
register(Challenge(
    key="all_chicken",
    name="全鸡宴",
    tagline="从汉堡到小食全是鸡，一只鸡的不同部位开会",
    pick=lambda items: sorted(
        [i for i in items if any(
            k in i.name for k in ("鸡", "翅", "V翅", "鸡块", "鸡柳", "鸡排"))],
        key=lambda i: i.price)[:4],
    roasts=[
        "这一单里可能住了三只鸡，它们生前大概没见过面。",
        "鸡的各个部位在此刻达成了历史性和解。",
        "吃完这顿，你至少有一周不想再看到鸡。",
    ],
    warning="全是油炸的话，口会很干，记得配饮品。",
))

# 6. 一色到底
register(Challenge(
    key="one_color",
    name="一色到底",
    tagline="只点颜色一样的，摆在一起像色卡",
    pick=lambda items: (
        [i for i in items if "薯" in i.name][:2]
        + [i for i in items if "玉米杯" in i.name][:1]
        + [i for i in items if i.category == "dessert" and any(
            k in i.name for k in ("派", "橙", "玉米"))][:1]
    ),
    roasts=[
        "拍照很好看，吃起来就是「今天怎么全是黄的」。",
        "色彩搭配满分，营养搭配不及格。",
        "适合发朋友圈，不适合连吃两天。",
    ],
    warning="同色系通常口味也接近，容易吃腻。",
))

# 7. 全是新品
register(Challenge(
    key="all_new",
    name="新品全收集",
    tagline="把菜单上标了「上新」的全点一遍，一次尝完",
    pick=lambda items: [i for i in items if any(
        "上新" in t for t in i.tags)][:4],
    roasts=[
        "尝鲜有风险，这单里可能有一半是你以后不会再点的。",
        "新品全收集，本质是花自己的钱帮别人做市场调研。",
        "如果全都好吃，那你运气不错；如果不好吃，至少你知道了。",
    ],
    warning="新品可能随时下架或售罄，点之前确认还有货。",
))

# 8. 冰火两重天
register(Challenge(
    key="hot_cold",
    name="冰火两重天",
    tagline="刚出锅的热食 + 冰到牙疼的甜品，一口一轮换",
    pick=lambda items: (
        [i for i in items if i.category == "main"][:1]
        + [i for i in items if i.category == "side" and "薯" in i.name][:1]
        + [i for i in items if i.category == "dessert"][:2]
    ),
    roasts=[
        "牙齿会同时收到冷和热的通知，然后一起抗议。",
        "这就是传说中的「牙医快乐餐」。",
        "冷热交替吃，享受的是刺激，考验的是牙。",
    ],
    warning="牙齿敏感的人别试，真的会疼。",
))

# 9. 最便宜吃饱
register(Challenge(
    key="cheapest",
    name="极限省钱组合",
    tagline="在能吃饱的前提下，把总价压到最低",
    pick=lambda items: _cheapest_filling(items),
    roasts=[
        "这一单的精髓是：吃饱了，但没吃爽。",
        "省钱挑战的终点，往往是「下次一定点好的」。",
        "便宜是真的便宜，快乐也是真的打折。",
    ],
    warning="最便宜的往往是小食，别指望有主食的分量。",
))

# 10. 全员带酱
register(Challenge(
    key="sauce_party",
    name="蘸酱派对",
    tagline="所有能蘸的都点上，一种酱配一样",
    pick=lambda items: (
        [i for i in items if i.category == "sauce"][:3]
        + [i for i in items if i.category == "side"][:2]
    ),
    roasts=[
        "酱点多了的后果是：最后你吃的是酱，不是食物。",
        "这一单的主角是配角。",
        "蘸酱派对，主角永远是酱，食物只是载体。",
    ],
    warning="酱料单价低但容易点过头，三份已经够了。",
))



def _cheapest_filling(items: list[Item]) -> list[Item]:
    """
    极限省钱：1 个最便宜主食 + 1 个最便宜小食 + 1 个最便宜饮品。

    为什么不凑 4 件？因为「省钱挑战」的本意是「用最少的钱吃饱」，
    硬凑件数反而更贵 —— 那是和稀泥，不是省钱。
    """
    def cheapest(cat: str) -> Item | None:
        pool = [i for i in items if i.category == cat and i.price > 0]
        return min(pool, key=lambda i: i.price) if pool else None

    picked = [x for x in (cheapest("main"), cheapest("side"), cheapest("drink")) if x]
    # 没有饮品时用小食补一个，保证不至于太寒酸
    if len(picked) < 2:
        extra = cheapest("side")
        if extra and extra not in picked:
            picked.append(extra)
    return picked


def build(
    challenge_key: str,
    items: list[Item],
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """
    生成一个挑战套餐。

    返回：
      {key, name, tagline, items[], total_price, roast, warning, empty}
    """
    rng = rng or random.Random()
    ch = CHALLENGES.get(challenge_key)
    if not ch:
        return {"error": f"未知挑战: {challenge_key}", "available": list(CHALLENGES)}

    picked = ch.pick(items)
    # 去重（同名只留一次）
    seen, uniq = set(), []
    for i in picked:
        if i.name not in seen:
            seen.add(i.name)
            uniq.append(i)

    total = sum(i.price for i in uniq)
    return {
        "key": ch.key,
        "name": ch.name,
        "tagline": ch.tagline,
        "items": uniq,
        "total_price": round(total, 2),
        "roast": rng.choice(ch.roasts),
        "warning": ch.warning,
        "empty": not uniq,
    }


def random_challenge(items: list[Item], rng: random.Random | None = None) -> dict[str, Any]:
    """随机来一个（用户说「不知道吃什么」但没指定类型时用）。"""
    rng = rng or random.Random()
    keys = list(CHALLENGES)
    rng.shuffle(keys)
    for k in keys:
        r = build(k, items, rng)
        if not r.get("empty"):
            return r
    return {"error": "当前菜单凑不出任何挑战，菜品太少了"}


# ---------- 自测 ----------

if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    demo = [
        Item("巨无霸", 26.5, "1100", "main"),
        Item("麦辣鸡腿汉堡", 22.5, "1440", "main"),
        Item("板烧鸡腿堡", 23.5, "1406", "main"),
        Item("龙焰鸡腿堡", 15.9, "521952", "main", ["上新"]),
        Item("中薯条", 14.5, "4810", "side"),
        Item("麦乐鸡", 14.5, "1401", "side"),
        Item("麦辣鸡翅", 15.0, "1700", "side"),
        Item("薄皮焦香V翅", 16.0, "520445", "side"),
        Item("小杯玉米杯", 13.0, "4437", "side"),
        Item("香芋派", 8.0, "9900008752", "dessert"),
        Item("圆筒冰淇淋", 5.0, "515837", "dessert"),
        Item("蓝莓爆爆珠麦旋风", 16.0, "521950", "dessert", ["上新"]),
        Item("经典麦旋风", 15.0, "9900008754", "dessert"),
        Item("韩式烟熏芝士风味酱", 3.0, "521966", "sauce"),
        Item("日式鲜磨山葵酱", 3.0, "521799", "sauce"),
        Item("可乐", 9.5, "9900008751", "drink"),
    ]

    rng = random.Random(7)
    print(f"共 {len(CHALLENGES)} 种挑战\n")
    for key, ch in CHALLENGES.items():
        r = build(key, demo, rng)
        if r["empty"]:
            print(f"【{ch.name}】当前菜单凑不出\n")
            continue
        names = " + ".join(f"{i.name}" for i in r["items"])
        print(f"【{r['name']}】¥{r['total_price']:.2f}")
        print(f"  {r['tagline']}")
        print(f"  {names}")
        print(f"  吐槽：{r['roast']}")
        print(f"  提醒：{r['warning']}\n")

    print("=== 随机一个 ===")
    r = random_challenge(demo, rng)
    print(f"【{r['name']}】{' + '.join(i.name for i in r['items'])}  ¥{r['total_price']:.2f}")
