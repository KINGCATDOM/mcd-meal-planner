# 麦当劳 MCP 工具速查

> 服务地址 `https://mcp.mcd.cn` ｜ 协议 Streamable HTTP ｜ 鉴权 `Authorization: Bearer <TOKEN>`
> 限流 600 次/分钟（超限 429）｜ Token 无效 401

## 一、常用工具（本 Skill 实际调用的 15 个）

### 1. `now-time-info` — 当前时间

无参数。**每次会话第一个调**，用于判断早市/正餐/夜市。

返回大致结构：
```json
{ "datetime": "2026-10-23 19:30:00", "weekday": "星期五", "timestamp": 1761... }
```

判断规则（本 Skill 采用）：
- 05:00–10:30 → 早市（只卖早餐菜单）
- 10:30–22:00 → 正餐
- 22:00–05:00 → 夜市（部分门店，菜单受限）

### 2. `query-nearby-stores` — 附近门店

| 参数 | 类型 | 说明 |
|---|---|---|
| `city` / `keyword` / `address` | string | 地址或商圈关键词 |

**硬约束：每次固定只返回 5 家门店，无分页。** 地址太模糊容易查不准，尽量给到"区 + 商圈/路名"。

返回每家店含 `storeCode`（后续 `query-meals` 必须用它）、店名、地址、营业状态。

### 3. `query-meals` — 门店菜单

| 参数 | 类型 | 说明 |
|---|---|---|
| `storeCode` | string | 门店编码 |
| `beType` | int | 就餐方式：`1` = 到店自取 |

**坑：返回价格单位是「元」，且通常是字符串。** 例如 `"price": "23.5"`。

返回结构（简化）：
```json
{
  "categories": [
    {
      "name": "汉堡",
      "items": [
        { "code": "M001", "name": "板烧鸡腿堡", "price": "20.0", "tags": ["招牌"] }
      ]
    }
  ]
}
```

### 4. `query-meal-detail` — 套餐详情

| 参数 | 类型 | 说明 |
|---|---|---|
| `storeCode` | string | |
| `mealCode` | string | 套餐编码 |
| `beType` | int | `1` = 到店自取 |

返回 `rounds`（轮次）数组，每个 round 下有可选项。

**硬约束：替换只能在同一 round 内。** 板烧三件套的"小食轮"里可能根本没有玉米杯，别凭常识猜。想做替换，先调这个接口看真实选项。

### 5. `list-nutrition-foods` — 营养数据

无参数（一次拉全量）。

**坑：返回 TOON 文本，不是 JSON。** 必须用 `references/toon_parser.py` 解析，不要手写 split。

原始样例：
```
{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  无糖可口可乐中杯,null,0,0,0,0,1,35,0
```

注意 `nutritionDescription` 可能是 `null`，也可能自带逗号（如 `"含生菜, 特制酱料"`）——这就是不能简单 split 的原因。

### 6. `calculate-price` — 算价

| 参数 | 类型 | 说明 |
|---|---|---|
| `storeCode` | string | |
| `items` | array | `[{code, quantity}]` |
| `couponId` | string | 可选，指定用哪张券 |
| `beType` | int | `1` = 到店自取 |

**坑：返回价格单位是「分」。** 展示前必须 `/100`。

返回大致结构：
```json
{
  "originalAmount": 4700,     // 分
  "discountAmount": 500,
  "payAmount": 4200,          // 分 = ¥42.00
  "deliveryFee": 0,
  "availableCoupons": [...]
}
```

### 7–10. 券相关

| Tool | 参数 | 用途 |
|---|---|---|
| `query-store-coupons` | `storeCode` | 当前门店可用的券 |
| `query-my-coupons` | 无 | 我账户里已有的券（含有效期字段） |
| `available-coupons` | 无 | 还没领、当前可领的券 |
| `auto-bind-coupons` | 无 | **写操作**：一键领光所有可领券 |

`auto-bind-coupons` 只领券不花钱，但仍是写操作，**需要用户说"领吧"才调**。

### 11. `campaign-calendar` — 活动日历

无参数。返回当月进行中/往期/未来活动。用于判断当季新品、限定活动，可作为推荐加分项。

### 12. `query-my-account` — 积分

无参数。返回可用积分、累计积分、冻结积分、**即将过期积分**。做券/积分建议时有用。

### 13. `order-list` — 历史订单

无参数或带时间范围。近期的到店/外送订单（不含商城订单）。

**S2 的延伸用法**：汇总最近几单的营养，给用户一份"近期摄入画像"。这是很低成本的高价值输出。

### 14. `create-order` — 创建订单（写）

| 参数 | 类型 | 说明 |
|---|---|---|
| `storeCode` | string | |
| `beType` | int | 就餐方式 |
| `items` | array | `[{code, quantity, modification?}]` |
| `couponId` | string | 可选 |

**返回 `orderId` 和支付链接。这是真实建单，会占用你的下单资格。**

调用前置条件（本 Skill 强制执行）：
1. 已经把完整方案（含餐品、数量、价格、用券）展示给用户
2. 用户明确说出"下单""就这个""帮我点"之类的话
3. 价格已核对过单位

### 15. `cancel-order` — 取消订单（写）

| 参数 | 说明 |
|---|---|
| `orderId` | 订单号 |

## 二、其余工具一览

| Tool | 说明 |
|---|---|
| `delivery-query-addresses` | 我的配送地址列表（**隐私数据，输出时脱敏**） |
| `delivery-create-address` | 新增配送地址（写） |
| `delivery-query-stores` | 可配送门店（外送场景用，不是 `query-nearby-stores`） |
| `query-meal-assistance` | 团餐助餐服务（仅企业团餐） |
| `query-order` | 订单详情/状态 |
| `mall-points-products` | 积分商城商品列表 |
| `mall-product-detail` | 商城商品详情 |
| `mall-create-order` | 积分兑换下单（写，会扣积分） |
| `query-lottery-info` | 积分抽奖活动信息 |
| `draw-lottery` | 抽奖（写，耗积分/次数） |
| `query-my-prizes` | 我的奖品 |
| `mall-order-list` | 商城订单列表 |
| `mall-order-detail` | 商城订单详情 |
| `query-party-city` | 派对活动城市 |
| `query-party-store` | 派对活动门店 |
| `query-partystore-date` | 可预约日期 |
| `query-partystore-session` | 可预约场次 |
| `party-order-create` | 派对订单创建（写） |

> 派对/团餐这套工具本 Skill 当前不做主推，但 S3 聚餐场景可以做延伸：如果用户说"公司团建要包场"，可以路由到 `query-party-city` → `query-party-store` → `query-partystore-date` 这条链。

## 三、错误码处理

| code | 含义 | 本 Skill 的处理 |
|---|---|---|
| 401 | Token 无效/过期/未带 | 告知去 open.mcd.cn/mcp 重新激活并更新连接器，**不重试** |
| 429 | 超 600 次/分钟 | 停止调用，提示等一分钟 |

## 四、调用节奏建议

- 一次完整 S2 会话大约调用 8–10 次工具（时间 1 + 门店 1 + 菜单 1 + 详情 2–3 + 营养 1 + 券 2 + 算价 2）。远低于限流，不需要刻意省。
- 真正的浪费在于**对每个候选组合都调 `calculate-price`**。本地求解器就是为了避免这个。
- `list-nutrition-foods` 一次拉全量后复用，不要按餐品逐个查（接口也不支持按餐品查）。
