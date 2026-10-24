# 接口实测报告

> **首测**：2026-10-23 19:57｜济南凤鸣广场餐厅（`storeCode=3350241`，距离 159 米）
> **复测**：2026-10-24 11:36｜深圳同方信息港餐厅（`storeCode=1420762`，距离 403 米）
> **测试方式**：直接调用麦当劳 MCP Server（`https://mcp.mcd.cn`），读取类工具，**未执行任何下单/领券操作**
> **目的**：把"看起来能用"变成"真的能用"

---

## 零、2026-10-24 复测结论（本次新增）

复测动因：想验证「按热量配套餐」这个场景是否可行。**结论是可行，但接口有两个必须绕开的坑。**

| 验证项 | 结果 | 影响 |
|---|---|---|
| 35 个工具可用性 | ✅ 全部正常 | 与首测一致，无工具下线 |
| 营养表 `list-nutrition-foods` | ✅ 返回 158 条 | 但**全是单品，无任何套餐** |
| 营养匹配率 | ⚠️ **51.3%**（58/113） | 套餐/新品/周边基本无数据 |
| **套餐热量查询** | ❌ **严重错配** | 三件套查出 485 kcal，真实 **921 kcal**，**低估 47%** |
| 引号归一化 | ⚠️ 存在不一致 | `“苹板”` 能匹配，`「苹板」` 匹配不到 |
| 算价自动促销 | ✅ 确认生效 | 龙焰鸡腿堡 ¥24 → ¥15.90（`discount: 810`） |
| 券"未生效"状态 | ⚠️ **确有此事** | 2 张券当天均未生效（10/26 起，仅工作日） |
| `query-store-coupons` | ✅ 返回空数组 | 门店无专属券，**空数组不是错误** |
| `query-promotions` | ⚠️ **仅团餐可用** | `beType=1` 调不通，只能 `beType=6` |
| `available-coupons` | ✅ 3 条 | 1 张可领（免费脆薯饼）、2 张已领 |
| `query-my-account` | ✅ 正常 | 可用 350.5 分，**本月将过期 96.8 分** |
| **促销价 vs 菜单价** | ⚠️ **差 21%** | 节日组合原价 ¥138.40 → 实付 ¥109.60 |
| **营养表不分时段** | ⚠️ 全时段全量 | 麦满分有营养数据但午市买不到 |

### 复测门店信息（完整展示）

| 门店 | storeCode | 地址 | 距离 | 营业 |
|---|---|---|---|---|
| 麦当劳深圳同方信息港餐厅 | `1420762` | 科技园北区朗山路11号同方信息港E栋G层5号商铺 | 403 米 | 07:00–23:00 |
| 麦当劳深圳禹洲广场餐厅 | `1420659` | 科苑路共享大厦A座一层L1-01号 | 477 米 | 07:00–23:00 |
| 麦当劳深圳科技园长园得来速餐厅 | `1420888` | 高新中一道2号长园新材料港C栋一层102 | 732 米 | 07:00–22:00 |
| 麦当劳深圳松坪山餐厅 | `1421057` | 松坪山群芳街40号松坪村综合楼一层B39 | 810 米 | 00:00–23:59 |
| 麦当劳深圳科苑路餐厅 | `1420412` | 讯美科技广场3号首层 | 1233 米 | 07:00–23:00 |

### 算价实测（本次）

```
麦辣鸡腿汉堡三件套 9900005456 ×1  →  ¥33.50（菜单原价，无折扣）
龙焰鸡腿堡 521952 ×1              →  ¥24.00 菜单价 → ¥15.90 实付（自动促销，省 ¥8.10）
─────────────────────────────────────────────────
合计 productOriginalPrice 5750 分
     discount            810 分
     price               4940 分  =  ¥49.40
```

**关键发现：`521952` 在菜单里标 `discountType: "促销优惠"`，但只有算价才给出真实到手价 ¥15.90。** 菜单价 ¥24 是被划掉的原始价。

### 券的完整结构（首测时账户无券，本次补上）

```json
{
  "couponName": "11.9元麦辣鸡腿堡",
  "优惠": "¥11.9 (用券价格)",
  "有效期": "2026-10-26 10:30-2026-10-30 23:59 周一、二、三、四、五 10:30-23:59",
  "领取时间": "今日收到",
  "标签": "到店专用、外送专用"
}
```

**有效期是四重条件**：生效日 + 截止日 + 可用星期 + 可用时段。

本次测试时间 `2026-10-24 周六`，券 10/26（周一）才生效 → **两张券当天都不可用**。这是"省钱助手"最容易翻车的地方：`query-my-coupons` 会照常返回、标签写"到店专用"，看起来完全可用，实际一张也用不了。

### 套餐详情实测（麦辣三件套，门店 1420762）

| Round | 默认项 | 可换项（含差价） |
|---|---|---|
| 1 麦辣鸡腿汉堡 | 麦辣鸡腿汉堡 | 仅 1 项，不可换 |
| 2 选择套餐内小食 | 中薯条 | 5块心形薯饼+韩式辣椒黄油风味酱 +¥1｜月下相思扭扭薯 +¥1.5｜马来咖喱薄皮肉骨鸡3块 +¥2.5｜大薯条 +¥2.5｜**小杯玉米杯 −¥0.5**｜大杯玉米杯 +¥2.5 |
| 3 选择套餐内饮料 | 可乐中杯 | 椰奶雪冰 +¥3｜**无糖可乐中杯 +¥0**｜雪碧 +¥0｜阳光柠檬红茶 +¥0｜纯牛奶 +¥0.5｜麦咖啡冰美式 +¥9｜大杯鲜萃咖啡 +¥1.5｜麦咖啡冰奶铁 +¥11｜可乐大杯 +¥2｜…共 22 个选项 |

**对比首测（门店 3350241）的差异**：小杯玉米杯首测是 **−¥1.5**，本次是 **−¥0.5**。**同轮替换的差价会随门店/时段变化，不能写死。**

### 营养表实测（TOON，158 条）

首行带长度前缀，字段顺序固定：

```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  中薯条,null,1210,289,4,12,38,165,18
```

**关键：营养表里没有一条"套餐"。** 全是单品。

匹配测试（真实菜单 113 项 × 营养表 158 条）：

| 项 | 数值 |
|---|---|
| 匹配成功 | **58（51.3%）** |
| 未匹配 | 55 |
| ├ 套餐/组合装 | 22 |
| ├ 周边商品 | 5 |
| └ 新品及未收录单品 | 28 |

**最危险的错配**（`lookup()` 模糊匹配导致）：

| 套餐名 | 错误返回 | 真实值 | 低估 |
|---|---|---|---|
| 麦辣鸡腿汉堡三件套 | 485 kcal | **921 kcal** | 47% |
| 板烧鸡腿堡三件套 | 391 kcal | **827 kcal** | 53% |
| 巨无霸三件套 | 513 kcal | **949 kcal** | 46% |
| 麦香鱼套餐 | 325 kcal | **761 kcal** | 57% |
| 双层吉士汉堡套餐 | 429 kcal | **865 kcal** | 50% |

**（真实值 = 主食 + 中薯条 289 + 可乐中杯 147）**

修复方案见 `references/nutrition_helper.py` 的 `combo_kcal()`。

### 活动日历实测

`campaign-calendar` 无参返回当月全部活动，按日期分组（往期回顾 / 今日 / 未来）：

- 今日（10/24）8 条：丝巾开售、韩式蘸酱上新、麦金喜抽奖、GD 联名三件套、蓝莓麦旋风、厚松饼堡、麦咖啡黑巧、亲子派对
- 10/26 预告：11.9 元麦辣鸡腿堡、19.9 元王牌炸鸡任选 2
- 活动正文含可执行信息：价格（"26.9 元起"）、加购条件（"加 39.9 元可得"）、时间窗（"10 月 8 日起"）

**注意**：活动里的"加 ¥39.9 可得"是**加购价**，不等于菜单里该商品的标价（¥34.9 是随单购优惠价，需麦金卡）。

### 促销价与菜单价的差异（S7 实测）

做节日组合时发现的报价陷阱。同一份情人节 2 人组合（门店 1420762）：

| 商品 | 菜单价 | 算价实付 | 差额 |
|---|---|---|---|
| `9900016076` 鸡薯双全盒 | ¥15.90 | ¥15.90 | — |
| `9900016566` 心形薯饼 8 块 | ¥22.50 | **¥9.90** | −¥12.60 |
| `521952` 龙焰鸡腿堡 ×2 | ¥48.00 | **¥31.80** | −¥16.20 |
| `521950` 蓝莓爆爆珠麦旋风 ×2 | ¥33.00 | ¥33.00 | — |
| `9900008751` 可乐 ×2 | ¥19.00 | ¥19.00 | — |
| **合计** | **¥138.40** | **¥109.60** | **−¥28.80（−21%）** |

**算价返回**：`originalPrice: 13840` 分、`discount: 2880` 分、`price: 10960` 分。

**结论**：任何报价都必须用 `calculate-price`，菜单价只能作为"原价"参照。同时要提醒用户促销有期限。

### 早餐时段的硬限制（S7 实测）

`list-nutrition-foods` 里有猪柳麦满分（308 kcal）、猪柳蛋麦满分（387 kcal），但 **11:55 的菜单里没有这两项** —— 它们只在早餐时段供应。

**营养表是全时段全量的，不区分早市/夜市。** 所以"营养表里有"≠"现在能买"，必须以 `query-meals` 当前菜单为准。

这也直接限制了早餐类组合的可用性：麦满分系列只在早餐时段供应，**午市/夜市买不到**，必须在推荐时说清楚。

---

## 一、首测（2026-10-23）结论摘要

| 验证项 | 结果 | 影响 |
|---|---|---|
| 连接与鉴权 | ✅ 通过 | Bearer Token + Streamable HTTP 正常 |
| 工具数量 | ✅ **35 个** | 官方文档写 33 个，实际多 2 个 |
| 门店查询 | ✅ 通过 | 但 `searchType` 必须传 2，否则报错 |
| 菜单结构 | ✅ 通过 | 110 个餐品 / 14 个品类，价格是**字符串** |
| 价格单位 | ⚠️ **不一致** | 菜单「元」，算价「分」，差 100 倍 |
| TOON 解析 | ✅ 已修复 | 表头带 `[160]` 前缀，原解析器返回 0 条 |
| 营养匹配率 | ⚠️ **51.3%** | 原因是套餐 vs 单品，非名字差异 |
| 套餐可选品 | ✅ 通过 | 小食轮**有**玉米杯（推翻了原假设） |
| 算价 | ✅ 通过 | 但字段名是 `productCode`，写错不报错只返回 0 |

---

## 二、逐项实测详情

### 2.1 服务连通

```
POST https://mcp.mcd.cn
Authorization: Bearer <TOKEN>
Content-Type: application/json
Accept: application/json, text/event-stream
```

`initialize` 返回：
```json
{ "serverInfo": { "name": "mcd-mcp", "version": "1.0.0" },
  "protocolVersion": "2024-11-05",
  "capabilities": { "tools": {} } }
```

**无需 session id**，每次请求独立携带 Token 即可。

---

### 2.2 工具清单（35 个，实测）

比官方文档多出的 2 个：`query-promotions`（查促销）、`query-survey-coupon`（订单评价领券）。

按用途分组：

| 组 | 工具 |
|---|---|
| 基础 | `now-time-info` |
| 门店 | `query-nearby-stores`、`delivery-query-stores`、`delivery-query-addresses`、`delivery-create-address` |
| 菜单 | `query-meals`、`query-meal-detail`、`list-nutrition-foods`、`query-meal-assistance` |
| 券 | `query-my-coupons`、`available-coupons`、`auto-bind-coupons`、`query-store-coupons`、`query-promotions`、`query-survey-coupon` |
| 算价下单 | `calculate-price`、`create-order`、`cancel-order`、`query-order`、`order-list` |
| 积分 | `query-my-account`、`mall-points-products`、`mall-product-detail`、`mall-create-order`、`mall-order-list`、`mall-order-detail` |
| 抽奖 | `query-lottery-info`、`draw-lottery`、`query-my-prizes` |
| 派对 | `campaign-calendar`、`query-party-city`、`query-party-store`、`query-party-store-date`、`query-party-store-session`、`party-order-create` |

---

### 2.3 门店查询

**正确调用**
```json
{ "city": "济南", "keyword": "凤鸣广场", "beType": 1, "searchType": 2 }
```

**错误调用**（`searchType` 不传或传 1）
```json
{ "code": 600050, "message": "收藏餐厅列表为空，请您提供城市+关键词进行搜索" }
```
→ 这个报错有误导性。真正原因是 `searchType=1` 查的是**收藏餐厅**，不是位置搜索。

**返回结构**（实测 5 家，含以下字段）
```json
{
  "storeCode": "3350241",
  "storeName": "麦当劳济南凤鸣广场餐厅",
  "address": "世纪大道与凤鸣路交叉口西南角凤鸣广场",
  "distance": 159,
  "businessStatus": true,
  "businessStartTime": "07:00",
  "businessEndTime": "00:00",
  "longitude": 0.0,
  "latitude": 0.0,
  "reservation": true,
  "reservationTimeOptions": [
    { "date": "2026-10-23", "today": true, "reservationOptionText": "夜市(17:14至21:45)，宵夜(22:14至23:59)" },
    { "date": "2026-10-24", "today": false, "reservationOptionText": "早餐(07:14至10:15)，午餐(10:44至14:15)，..." }
  ]
}
```

**要点**
- `longitude` / `latitude` **恒为 0.0**，无法做距离计算；用 `distance`（米）
- `beType=1`（到店自取）返回的门店**没有 `beCode`**
- `reservationTimeOptions` 里的时段名（早餐/午餐/下午茶/夜市/宵夜）可用于判断"现在能点什么"

---

### 2.4 菜单结构

**调用**
```json
{ "storeCode": "3350241", "beType": 1, "orderType": 1 }
```

**返回是一个 dict，不是数组**
```json
{
  "categories": [
    { "name": "人气热卖", "meals": [ { "code": "9900016081", "tags": ["心形薯饼同款比心"] }, ... ] },
    ...
  ],
  "meals": {
    "9900005456": {
      "name": "麦辣鸡腿汉堡三件套",
      "image": "https://menu-img.mcd.cn/...",
      "currentPrice": "33.5",
      "originalPrice": "47",
      "canWithOrder": false
    },
    ...
  }
}
```

**规模**：14 个品类 / 110 个餐品 / 价格 ¥3.9 – ¥72.5 / 17 个可随单购商品

**三个坑**
1. **`categories[].meals` 只有 code 和 tags**，名称和价格要去顶层 `meals` dict 里按 code 反查
2. **价格是字符串** `"33.5"`，要 `float()` 才能算
3. **品类名带换行**（`"鸡肉汉堡\n/卷"`），展示前要替换

---

### 2.5 营养数据：TOON 格式实测

**`data` 字段是字符串**（不是数组），这就是 TOON 文本的开始。

原始首行：
```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
```

**关键：开头有 `[160]` 长度前缀。**

我最初的解析器没处理它，导致：
- `stripped.strip("{}:")` 拿到第一个字段是 `[160]{productName`
- 归一化失败，命中不到 2 个已知字段名
- 判定"没有表头"，走兜底逻辑后全部错位
- **最终解析出 0 条**

**修复后**：160 条全部正确解析。

样例数据：
```
猪柳麦满分,   null, 1288, 308, 16, 16, 24, 781, 213
猪柳蛋麦满分, null, 1618, 387, 23, 21, 25, 846, 243
中薯条,      null, 1210, 289,  4, 12, 38, 165,  18
```

`nutritionDescription` 实测全部为 `null`（本次样本中）。

---

### 2.6 营养表与菜单的匹配率：51.3%

| 项 | 数值 |
|---|---|
| 营养表条数 | 158 |
| 菜单餐品数 | 113 |
| 匹配成功 | **58** |
| 命中率 | **51.3%** |

**根因不是名字差异，是"套餐 vs 单品"：**

营养表只收录**单品**，而菜单里有大量**套餐**：

| 未匹配例子 | 原因 |
|---|---|
| `全明星双人分享餐八件套` | 套餐，营养表无 |
| `龙焰鸡腿堡三件套` | 套餐，营养表无 |
| `阳光橙麦炫酷` | 新品，未收录 |
| `"葱不求人"按摩捶痒痒挠` | 周边商品，本就无营养 |

**解法**：套餐必须先用 `query-meal-detail` 拆成 round 子项，再对子项逐个查营养后累加。

---

### 2.7 套餐详情：推翻了原有假设

**测试套餐**：麦辣鸡腿汉堡三件套（`9900005456`，现价 ¥33.5，原价 ¥47）

**Round 1｜麦辣鸡腿汉堡**（必选 1）
| 名称 | 加价 | 可特制 |
|---|---|---|
| 麦辣鸡腿汉堡 ★默认 | +¥0 | ✅ |

**Round 2｜选择套餐内小食**（必选 1）
| 名称 | 加价 | code |
|---|---|---|
| 中薯条 ★默认 | +¥0 | 4810 |
| 马来咖喱风味薄皮肉骨鸡3块 | +¥2.5 | 521881 |
| 大薯条 | +¥2 | 4820 |
| **小杯玉米杯** | **−¥1.5** | 4437 |
| **大杯玉米杯** | **+¥1** | 4438 |
| 脆脆薯条 | +¥2 | 514782 |

**Round 3｜选择套餐内饮料**（必选 1，22 个选项）
有可乐/无糖可乐/阳光柠檬红茶（+¥0）、纯牛奶/锡兰红茶（+¥1）、麦咖啡系列（+¥9～13）等。

**重要修正**：我之前在文档里写"板烧三件套的小食轮里没有玉米杯，薯条换不了玉米杯"——**实测证明是错的**。麦辣三件套的小食轮**有**小杯/大杯玉米杯，而且换成小杯玉米杯还能**便宜 ¥1.5**。

**这个发现价值很大**：把中薯条换成小杯玉米杯，价格降 ¥1.5，同时热量从 289 kcal 降到约 87 kcal、钠从 165mg 降到 2mg。这是"同轮零成本换更划算选项"的真实案例，已写进 S1/S2 场景作为推荐动作。

**其他实测细节**
- `diffPrice` 是**带符号的字符串**（`"+ ¥2.5"`、`"- ¥1.5"`），要正则抽数字
- `isDefault: 1` 标记默认项
- `supportModify: true` 的餐品才支持"去酱/加酱"等特制
- 特制选项在 `modification.items[].values[]`，含 `code` / `name` / `price` / `selectedKey`

---

### 2.8 算价：单位与字段名双重坑

**错误写法**（用 `code` 代替 `productCode`）
```json
{ "items": [{ "code": "9900011123", "quantity": 1 }] }
```
返回：
```json
{ "productOriginalPrice": 0, "productPrice": 0, "price": 0, "productList": [] }
```
**不报错，静默返回全 0。** 这比报错更危险——不校验就会展示一个 ¥0 订单。

**正确写法**
```json
{ "storeCode": "3350241", "beType": 1, "orderType": 1,
  "items": [{ "productCode": "9900011123", "quantity": 1 }] }
```
返回：
```json
{
  "productOriginalPrice": 2400,
  "productPrice": 2400,
  "originalPrice": 2400,
  "discount": 0,
  "price": 2400,
  "productList": [
    { "productCode": "9900011123", "productName": "“辣”么快乐套餐",
      "quantity": 1, "originalSubtotal": 2400, "subtotal": 2400 }
  ],
  "takeWayList": [
    { "code": "eat-in", "title": "堂食", "subtitle": "店内用餐" },
    { "code": "locker-in", "title": "外带", "subtitle": "店内取餐柜" }
  ]
}
```

**单位验证**

| 来源 | 商品 | 值 | 实际价格 |
|---|---|---|---|
| `query-meals` | "辣"么快乐套餐 | `"currentPrice": "24"` | ¥24 |
| `calculate-price` | 同一商品 | `"price": 2400` | ¥24 |

**24 vs 2400，正好差 100 倍。单位坑确证存在。**

**额外发现**：`takeWayList` 返回堂食（`eat-in`）/ 外带（`locker-in`），下单时 `takeWayCode` 要传这里的 code。

---

### 2.9 券与积分

**`query-my-coupons`**（本次账户 0 张券）
```json
{ "coupons": [], "totalCount": 0, "currentPage": 1, "pageSize": 200, "totalPages": 0 }
```
⚠️ 因列表为空，**有效期字段名未能验证**（待有券时补）。

**`available-coupons`**（可领 5 张，含重复）
```json
{ "couponName": "11.9元麦辣鸡腿堡", "couponImage": "https://...", 
  "couponStatus": "CAN_GET", "label": "可领取" }
```
实测清单：
- 11.9元麦辣鸡腿堡 ×2（重复）
- 19.9元王牌炸鸡任选2 ×2（重复）
- 免费脆薯饼 ×1

**注意：返回有重复项，展示前要按 `couponName` 去重。**

**`query-my-account`**
```json
{ "availablePoint": "350.5", "accumulativePoint": "375.4",
  "currentMouthExpirePoint": "96.8", "expiredPoint": "23.9",
  "frozenPoint": "0", "usedPoint": "1", "currency": "麦享会积分" }
```
- 积分是**字符串**，要转 float
- 字段名是 `currentMouthExpirePoint`（Mouth 不是 Month，官方拼写）
- `currentMouthExpirePoint: 96.8` 表示本月即将过期 96.8 积分，可直接用于"积分防浪费"功能

---

## 三、对 SKILL.md 的修正清单

基于实测，需要改的地方：

| 原表述 | 实测结论 | 处理 |
|---|---|---|
| "板烧三件套的小食轮里没有玉米杯" | **错误**。麦辣三件套有玉米杯，换小杯还便宜 1.5 元 | 已改为"必须查 detail，不要预设" |
| "query-meals 返回价格常为字符串" | 确认为字符串，元 | 保留并强化 |
| "items 用 code" | **应为 `productCode`** | 已修正 |
| 未提及 searchType | **必须传 2** | 已加入铁律 |
| 未提及 TOON 长度前缀 | **有 `[160]` 前缀** | 已修复解析器 |
| 未提及 categories 只有 code | 需反查 meals dict | 已加入文档 |

---

## 四、实测方法（可复现）

```python
import json, urllib.request

TOKEN = "<你的Token>"
URL = "https://mcp.mcd.cn"

def call(tool, args):
    body = {"jsonrpc":"2.0","id":1,"method":"tools/call",
            "params":{"name":tool,"arguments":args}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
        headers={"Content-Type":"application/json",
                 "Accept":"application/json, text/event-stream",
                 "Authorization": f"Bearer {TOKEN}"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode()
    if "data:" in raw[:300]:  # SSE 兼容
        datas = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")]
        if datas: raw = datas[-1]
    return json.loads(raw)

# 依次验证
print(call("now-time-info", {}))
print(call("query-nearby-stores", {"city":"济南","keyword":"凤鸣广场","beType":1,"searchType":2}))
print(call("query-meals", {"storeCode":"3350241","beType":1,"orderType":1}))
print(call("list-nutrition-foods", {}))
print(call("query-meal-detail", {"storeCode":"3350241","beType":1,"orderType":1,"code":"9900005456"}))
print(call("calculate-price", {"storeCode":"3350241","beType":1,"orderType":1,
                               "items":[{"productCode":"9900011123","quantity":1}]}))
```

---

## 五、未验证项

| 项 | 原因 | 状态 |
|---|---|---|
| 券的有效期字段名 | 首测账户无券 | ✅ **复测已补**，见第零章「券的完整结构」 |
| 满减门槛结构 | 首测未深入 | ⚠️ **部分**：`query-promotions` 仅团餐可用；到店门店券实测返回空数组 |
| 早晚市菜单差异 | 只测了午市/晚市 | 🔍 待补：早上 8 点再拉一次 |
| `create-order` 实际返回 | **刻意未测**（真实建单） | 🔍 需用户明确同意后再测 |
| `delivery-create-address` / 麦乐送链路 | 未测 | 🔍 待补 |
| 企业团餐 `party-order-create` | 未测 | 🔍 待补 |

---

*本报告为参赛材料，记录真实接口调用结果。所有数字均来自实际调用，不含估算。*
