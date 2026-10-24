# -*- coding: utf-8 -*-
"""
套餐比价助手（combo_compare.py）
================================

解决的问题：历史上这个 Skill 拿到菜单后，直接枚举「主餐 × 小食 × 饮品」的单品组合，
**完全没有扫套餐**。结果给用户的报价比套餐贵 ¥11（板烧组合 ¥44 vs 板烧三件套换项 ¥33）。

本脚本提供三件事：

1. `scan(meals)`   —— 从 `query-meals` 原始返回里扫出全部套餐 / 分享装，算折扣率并排序。
                      **任何场景拿到菜单后都要先跑这个。**
2. `quick_pick()`  —— 快速模式专用：捞出「必须给你看的几档」套餐。
                      **核心修复（2026-10-24）**：折扣率 1.0 的无条件真价套餐（如
                      「满分厚松饼堡双人餐 ¥39.9、原价也是 ¥39.9」）会沉到排行底部，
                      导致快速模式只用单品拼方案。快速模式**必须**至少含 1 档真价套餐。
3. `three_line()`  —— 「套餐原样 / 套餐换项 / 单品单点」三线对比，给出该选哪条线。
4. `verdict()`     —— 生成一句人话结论，直接可用于输出。

设计原则：本地算，不打远程。`query-meals` 一次拉全后，扫套餐应该是 0 次额外调用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 关键词

# 有明确结构的值套餐（含主食+小食+饮品，或 N 件任选）
VALUE_KWS = ("三件套", "四件套", "五件套", "套餐", "随心配", "随心选", "单人餐", "双人餐", "亲子餐", "组合")

# 分享型（多人分食，结构不固定）
SHARE_KWS = ("小食盘", "四宫格", "桶", "十翅", "全翅", "拼盘", "拼", "盒", "分享", "双拼")

# 非餐品：会员卡、周边、玩具 —— 必须排除，否则会推荐「麦当劳联名棒球帽」
EXCLUDE_KWS = (
    "卡", "会员", "权益", "券", "帽", "徽章", "丝巾", "袋", "杯套", "玩具",
    "盲盒", "联名款", "抱枕", "挂件", "餐盒", "礼盒", "手提",
)

# 价格字段可能的命名（不同接口版本不一致，全部兜住）
PRICE_KEYS = ("currentPrice", "price", "salePrice")
ORIGIN_KEYS = ("originalPrice", "originPrice", "initPrice", "marketPrice", "linePrice")


# ---------------------------------------------------------------- 数据结构


@dataclass
class Combo:
    code: str
    name: str
    price: float                    # 当前价（元）
    origin: float | None = None     # 原价（元），可能缺
    kind: str = "value"             # value / share
    tags: list[str] = field(default_factory=list)
    needs_card: bool = False        # 菜单价是否为「随单购麦金卡」价
    discount_type: str = ""         # 接口返回的 discountType 原文

    @property
    def real_price(self) -> float:
        """
        未经核实的真实价。

        needs_card=True 时，菜单 currentPrice 是买卡价，**不买卡要按原价算**，
        所以真实价取 origin。这个值只是估算基准，最终必须以 calculate-price 为准。
        """
        if self.needs_card and self.origin:
            return round(self.origin, 2)
        return self.price

    @property
    def saving(self) -> float:
        """省多少钱（元）。无原价返回 0。"""
        if not self.origin or self.origin <= self.price:
            return 0.0
        return round(self.origin - self.price, 2)

    @property
    def discount(self) -> float:
        """
        折扣率，0.52 表示 5.2 折。无原价返回 1.0。

        **买卡价不算折扣** —— 否则所有「随单购麦金卡」的商品都会排到最前面，
        显示成 4.4 折，实际不买卡是原价。这类一律按 1.0 处理，排到最后。
        """
        if not self.origin or self.origin <= 0 or self.needs_card:
            return 1.0
        return round(self.price / self.origin, 3)

    @property
    def has_structure(self) -> bool:
        """是否有明确件数结构（N 件套 / N 人餐）。"""
        return bool(re.search(r"[两二三四五六七八九十\d]\s*(件套|人餐)", self.name))

    @property
    def no_gimmick(self) -> bool:
        """
        无条件真价：不用买卡，菜单 currentPrice 就是实付价。

        **这类套餐即使一分钱折扣都没有，也必须在快速模式里露一次脸。**
        折扣率 1.0 只说明"没便宜"，不说明"不值得点"——双人餐原价卖
        本来就比两份单品加起来便宜，只是它不拿"划线价"讲故事。
        """
        return not self.needs_card

    @property
    def is_people_meal(self) -> bool:
        """双人餐 / 多人餐 / 分享装 —— 人数 ≥2 时必须优先看。"""
        return bool(re.search(r"[两二三四五六七八九十双\d]\s*人", self.name)) or self.kind == "share"


# ---------------------------------------------------------------- 工具函数


def _num(v) -> float | None:
    """把 '24.5' / '¥24.5' / 24.5 统一成 float。解析失败返回 None。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("¥", "").replace(",", "").replace("元", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _pick_numeric(d: dict, keys: tuple[str, ...]) -> float | None:
    for k in keys:
        if k in d:
            n = _num(d[k])
            if n is not None:
                return n
    return None


# ---------------------------------------------------------------- 主流程


def classify(name: str) -> str | None:
    """
    判断一个菜名是哪种套餐。

    返回：
        "value"  —— 有结构的值套餐
        "share"  —— 分享型（小食盘/拼/桶）
        None     —— 不是套餐，或应排除（周边/卡/玩具）
    """
    if not name:
        return None
    # 先排除：周边、会员卡。注意「如意百宝袋」这种名字带"袋"的周边要优先排除
    if any(k in name for k in EXCLUDE_KWS):
        return None
    # 值套餐优先判定（"堡堡随心拼(7件任选)" 含"拼"但也含"件"，应归 value）
    if any(k in name for k in VALUE_KWS) or re.search(r"\d+\s*件", name):
        return "value"
    if any(k in name for k in SHARE_KWS):
        return "share"
    return None


def scan(meals: dict) -> list[Combo]:
    """
    从 `query-meals` 的 meals 字典里扫出全部套餐。

    参数
    ----
    meals : dict
        `{code: {"name": ..., "currentPrice": ..., "originalPrice": ...}}`
        也兼容 `{code: {"shortName": ..., "price": ...}}`

    返回
    ----
    按折扣率升序（越便宜越前）排列的 Combo 列表。无原价的按价格升序殿后。
    """
    out: list[Combo] = []
    for code, d in (meals or {}).items():
        if not isinstance(d, dict):
            continue
        name = d.get("name") or d.get("shortName") or d.get("productName") or ""
        kind = classify(name)
        if not kind:
            continue
        price = _pick_numeric(d, PRICE_KEYS)
        if price is None or price <= 0:
            continue
        origin = _pick_numeric(d, ORIGIN_KEYS)
        tags = d.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        # 「随单购麦金卡」：菜单价是买卡价，不买卡按原价。必须识别出来，否则排名全错
        dtype = d.get("discountType") or ""
        needs_card = bool(d.get("canWithOrder")) and "随单购" in str(dtype)
        out.append(Combo(code=code, name=name, price=round(price, 2),
                         origin=round(origin, 2) if origin else None,
                         kind=kind, tags=list(tags),
                         needs_card=needs_card, discount_type=str(dtype)))

    # 排序：不用买卡的排前面；再按折扣率；同折扣按价格
    # 注：needs_card 必须做第一排序键。否则「买卡价」和「无折扣真价套餐」的
    # 折扣率都是 1.0，会混在末尾，快速模式取 top 时真价套餐被买卡价挤掉。
    out.sort(key=lambda c: (c.needs_card, c.discount if c.origin else 9.9, c.price))
    return out


def quick_pick(combos: list[Combo],
               people: int = 1,
               budget: float | None = None,
               top: int = 2) -> list[Combo]:
    """
    快速模式专用：挑出「必须给你看」的套餐档位。

    规则（按优先级）
    --------------
    1. **只用无条件真价套餐**（`no_gimmick`）。买卡价一律不进快速模式方案，
       顶多在提醒里提一句"加购早餐卡/麦金卡会更便宜"。
    2. `people >= 2` 时优先双人餐 / 多人餐 / 分享装 —— 这一档最容易被打成单品拼盘。
    3. 同优先级按现价升序；有折扣的按折扣率升序。
    4. `budget` 给了就剔除超预算的；但**不许因为超预算返回空**——
       全超预算时给最便宜的那个，让上层标注"最便宜也要 ¥xx，超预算"。
    5. 一个真价套餐都没有时返回 `[]`，上层照实说"这家没有不加卡的套餐"，
       **不许编，也不许假装套餐不存在**。

    返回：最多 `top` 个 Combo，第一个就是该优先展示的。
    """
    pool = [c for c in combos if c.no_gimmick]
    if not pool:
        return []
    if budget:
        within = [c for c in pool if c.price <= budget]
        pool = within or sorted(pool, key=lambda c: c.price)[:1]
    if people and people >= 2:
        people_meals = [c for c in pool if c.is_people_meal]
        if people_meals:
            # 带「人餐」的整餐优先于小食盘/分享装：小食盘再便宜也顶不了一顿正餐
            people_meals.sort(key=lambda c: (0 if re.search(r"人", c.name) else 1, c.price))
            rest = sorted((c for c in pool if c not in people_meals),
                          key=lambda c: (c.discount if c.origin else 9.9, c.price))
            return (people_meals + rest)[:top]
    pool.sort(key=lambda c: (c.discount if c.origin else 9.9, c.price))
    return pool[:top]


def three_line(combo_price: float,
               swap_price: float | None = None,
               single_price: float | None = None) -> dict:
    """
    三线比价：套餐原样 / 套餐换项 / 同内容单品单点。

    参数全是「元」。缺哪条线就传 None。

    返回
    ----
    {"winner": "swap"|"combo"|"single", "lines": {...}, "saving": float}
    """
    lines: dict[str, float] = {}
    if combo_price:
        lines["combo"] = round(combo_price, 2)
    if swap_price:
        lines["swap"] = round(swap_price, 2)
    if single_price:
        lines["single"] = round(single_price, 2)

    if not lines:
        return {"winner": None, "lines": {}, "saving": 0.0}

    winner = min(lines, key=lines.get)
    worst = max(lines.values())
    return {
        "winner": winner,
        "lines": lines,
        "saving": round(worst - lines[winner], 2),
        "price": lines[winner],
    }


_LINE_CN = {"combo": "套餐原样", "swap": "套餐换项", "single": "单品单点"}


def verdict(res: dict, what: str = "这个组合") -> str:
    """把 three_line 的结果翻成一句能直接放输出里的话。"""
    if not res.get("winner"):
        return "无法比价（缺少价格数据）。"
    w = res["winner"]
    price = res["price"]
    if w == "single":
        return f"{what}用单品单点更划算：¥{price:.2f}，比套餐版便宜 ¥{res['saving']:.2f}。"
    if w == "swap":
        return f"{what}走「套餐换项」最划算：¥{price:.2f}，比套餐原样 / 单品都便宜（最多省 ¥{res['saving']:.2f}）。"
    return f"{what}直接点套餐最划算：¥{price:.2f}，比单品单点省 ¥{res['saving']:.2f}。"


def split_by_card(combos: list[Combo]) -> tuple[list[Combo], list[Combo]]:
    """分成 (不用买卡, 需买卡) 两组。需买卡的不能当"最实惠"推荐。"""
    free = [c for c in combos if not c.needs_card]
    card = [c for c in combos if c.needs_card]
    return free, card


def report(combos: list[Combo], top: int = 8) -> str:
    """生成可读排行表，方便直接贴进思考过程或核对。"""
    if not combos:
        return "未扫到任何套餐。"
    rows = [f"{'套餐':<24}{'现价':>8}{'原价':>8}{'折扣':>7}{'省':>8}  备注"]
    rows.append("-" * 70)
    for c in combos[:top]:
        origin = f"¥{c.origin:.2f}" if c.origin else "—"
        disc = f"{c.discount*10:.1f}折" if (c.origin and not c.needs_card) else "—"
        save = f"¥{c.saving:.2f}" if (c.origin and not c.needs_card) else "—"
        note = "⚠需买麦金卡，原价" + f"¥{c.origin:.2f}" if c.needs_card and c.origin else ""
        rows.append(f"{c.name[:22]:<24}¥{c.price:>7.2f}{origin:>8}{disc:>7}{save:>8}  {note}")
    return "\n".join(rows)


# ---------------------------------------------------------------- 自测

if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    # 真实菜单（趵突泉 · 上新街店 3350337，2026-10-24 实测）
    MENU = {
        # 随单购麦金卡：菜单价 ¥49.9 是买卡价，实测算价 ¥114.5
        "9900011056": {"name": "全明星双人分享餐八件套", "currentPrice": "49.9",
                       "originalPrice": "114.5", "canWithOrder": True,
                       "discountType": "随单购麦金卡优惠"},
        # 同类：菜单 ¥28，实测算价 ¥57
        "9900000890": {"name": "板烧鸡腿堡四件套", "currentPrice": "28",
                       "originalPrice": "57", "canWithOrder": True,
                       "discountType": "随单购麦金卡优惠"},
        # 正常套餐，无卡费
        "9900015151": {"name": "麦麦周末双人餐", "currentPrice": "49.9", "originalPrice": "85.5"},
        "9900015602": {"name": "大堡口福三件套", "currentPrice": "22.9", "originalPrice": "47"},
        "9900016073": {"name": "龙焰鸡腿堡三件套", "currentPrice": "26.9", "originalPrice": "47.5"},
        "9900005456": {"name": "麦辣鸡腿汉堡三件套", "currentPrice": "33.5", "originalPrice": "46"},
        "9900013304": {"name": "人气经典随心配", "currentPrice": "14.9", "originalPrice": "14.9"},
        "9900015730": {"name": "BFF四宫格小食盘", "currentPrice": "38.8", "originalPrice": "54.5"},
        "9900004066": {"name": "堡堡随心拼（7件任选）", "currentPrice": "72.5", "originalPrice": "101.5"},
        "521929": {"name": "旋旋水手帽", "currentPrice": "48.8"},              # 周边，应排除
        "521914": {"name": "“葱不求人“按摩捶痒痒挠", "currentPrice": "14.9"},  # 周边，应排除
        "1100": {"name": "巨无霸", "currentPrice": "25.5"},                    # 单品，应排除
    }

    combos = scan(MENU)
    print("=== 扫到的套餐（买卡的排最后）===")
    print(report(combos))

    free, card = split_by_card(combos)
    print(f"\n不用买卡 {len(free)} 个 / 需买卡 {len(card)} 个")

    print("\n=== 排除校验 ===")
    got = {c.name for c in combos}
    for bad in ("旋旋水手帽", "“葱不求人“按摩捶痒痒挠", "巨无霸"):
        print(f"  {'OK  ' if bad not in got else 'FAIL'} 已排除：{bad}")

    print("\n=== 买卡价陷阱校验 ===")
    star = next(c for c in combos if c.name == "全明星双人分享餐八件套")
    print(f"  菜单价 ¥{star.price:.2f} | 真实价(需买卡→原价) ¥{star.real_price:.2f} | needs_card={star.needs_card}")
    print(f"  折扣率被压到 1.0 了吗: {'OK' if star.discount == 1.0 else 'FAIL'}")
    print(f"  → 排序位置应在不用买卡的之后: {'OK' if combos.index(star) >= len(free) else 'FAIL'}")

    print("\n=== 三线比价：板烧鸡腿堡（历史实测数据）===")
    r = three_line(34.50, swap_price=33.00, single_price=44.00)
    print("  ", r)
    print("  →", verdict(r, "板烧鸡腿堡这顿"))

    print("\n=== 反向校验：套餐不一定赢 ===")
    r2 = three_line(33.00, swap_price=None, single_price=31.00)
    print("  →", verdict(r2, "只要汉堡+水"))

    print("\n=== 回归：快速模式必须含无条件真价套餐（济南大学早餐实测）===")
    BREAKFAST = {
        # 无折扣真价双人餐 —— 历史上被「折扣率 1.0 沉底」漏掉
        "9900016136": {"name": "满分厚松饼堡双人餐", "currentPrice": "39.9",
                       "originalPrice": "39.9"},
        # 同价真价组合：单价更低的「组合」，用来验证双人餐不会被价格挤下去
        "9900015604": {"name": "东南亚风味椰香鸡扒堡组合", "currentPrice": "9.9",
                       "originalPrice": "9.9"},
        "9900011872": {"name": "芝芝火腿扒堡组合", "currentPrice": "9.9",
                       "originalPrice": "9.9"},
        # 以下三个都是买卡价，快速模式不许进方案
        "9900016524": {"name": "厚松饼猪柳蛋堡三件套", "currentPrice": "17.94",
                       "originalPrice": "29.9", "canWithOrder": True,
                       "discountType": "随单购早餐卡优惠"},
        "9900003458": {"name": "猪柳蛋麦满分套餐", "currentPrice": "15.60",
                       "originalPrice": "26", "canWithOrder": True,
                       "discountType": "随单购早餐卡优惠"},
        "9900003451": {"name": "大脆鸡扒麦满分套餐", "currentPrice": "10.80",
                       "originalPrice": "18", "canWithOrder": True,
                       "discountType": "随单购早餐卡优惠"},
        "5022": {"name": "猪柳蛋麦满分", "currentPrice": "18"},   # 单品，不是套餐
    }
    bk = scan(BREAKFAST)
    picks = quick_pick(bk, people=2, budget=100)
    print("  quick_pick →", [f"{c.name} ¥{c.price:.2f}" for c in picks])
    print(f"  {'OK  ' if picks and picks[0].name == '满分厚松饼堡双人餐' else 'FAIL'} "
          f"双人餐排第一（一分折扣没有也必须露脸）")
    print(f"  {'OK  ' if all(not c.needs_card for c in picks) else 'FAIL'} 买卡价已被挡在方案外")
    print(f"  {'OK  ' if bk[0].no_gimmick else 'FAIL'} scan() 首条已是真价套餐，买卡价被压到末尾")

    print("\n自测完成。")
