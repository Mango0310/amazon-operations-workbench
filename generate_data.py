# -*- coding: utf-8 -*-
"""
生成模拟数据：亚马逊运营分析工作台。

20 个 SKU × 30 天，故意设计不同业务情况：
  高销量 3 / 普通 7 / 新品 3 / 高ACOS 2 / 库存预警 2 / 销量下降 2 / 高毛利 1

输出 8 张数据表（CSV，UTF-8 BOM，Excel 可直接打开）：
  产品表 Product     — SKU、产品名称、类目、售价、成本、上架日期、产品阶段
  Listing            — SKU、Title、Bullet Points、Main Image、Search Terms、Status
  销售表 Sales        — 日期、SKU、订单量、销售额、退款金额
  库存表 Inventory    — SKU、当前库存、在途库存、日均销量、安全库存
  广告表 Advertising  — 日期、SKU、广告花费、广告销售额、点击、曝光
  搜索词表 Search Term — 广告活动、关键词、搜索词、匹配方式、花费、订单、销售额
  竞品表 Competitor   — SKU、ASIN、价格、Rating、Reviews、卖点、来源、采集日期
  利润表 Profit       — 由产品+销售+广告计算（销售额-成本-广告-物流-平台费）

运行：python generate_data.py
"""
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

np.random.seed(42)

END = datetime(2026, 8, 20)
DATES = [END - timedelta(days=i) for i in range(29, -1, -1)]  # 30 天升序
DATE_STR = [d.strftime("%Y-%m-%d") for d in DATES]

# ---------------------------------------------------------------------------
# 20 个 SKU 定义
# 字段：SKU, 产品名称(英文), 类目, 售价, 成本, 上架日期, 产品阶段, 业务标签
# 业务标签：hot(高销量) normal(普通) new(新品) high_acos(高ACOS) low_stock(库存预警) decline(销量下降) high_margin(高毛利)
# ---------------------------------------------------------------------------
SKUS = [
    ("A001", "Portable Blender", "Kitchen", 39.99, 12.0, "2026-03-01", "成熟", "hot"),
    ("A002", "Pet Water Fountain", "Pet Supplies", 32.99, 9.0, "2026-02-15", "成熟", "hot"),
    ("A003", "LED Desk Lamp", "Home Office", 24.99, 7.0, "2026-03-20", "成熟", "hot"),
    ("A004", "Yoga Mat", "Sports", 19.99, 6.0, "2026-04-10", "成熟", "normal"),
    ("A005", "Phone Stand", "Electronics", 12.99, 3.5, "2026-04-25", "成熟", "normal"),
    ("A006", "Insulated Water Bottle", "Outdoor", 22.99, 7.0, "2026-05-01", "成熟", "normal"),
    ("A007", "Desk Organizer", "Office", 16.99, 5.0, "2026-05-15", "成熟", "normal"),
    ("A008", "Wireless Charger", "Electronics", 29.99, 10.0, "2026-05-20", "成长", "low_stock"),
    ("A009", "Air Fryer Liners", "Kitchen", 11.99, 3.0, "2026-06-01", "成熟", "normal"),
    ("A010", "Resistance Bands", "Sports", 15.99, 4.5, "2026-06-10", "成熟", "normal"),
    ("A011", "Smart Doorbell", "Electronics", 59.99, 22.0, "2026-08-01", "新品", "new"),
    ("A012", "Car Vacuum Cleaner", "Automotive", 45.99, 16.0, "2026-08-05", "新品", "new"),
    ("A013", "Hair Dryer Brush", "Beauty", 35.99, 12.0, "2026-07-20", "新品", "new"),
    ("A014", "Coffee Grinder", "Kitchen", 27.99, 9.0, "2026-02-01", "衰退", "decline"),
    ("A015", "Laptop Stand", "Office", 25.99, 8.0, "2026-03-10", "成熟", "high_acos"),
    ("A016", "Dog Grooming Kit", "Pet Supplies", 28.99, 9.0, "2026-05-25", "成熟", "normal"),
    ("A017", "Solar String Lights", "Outdoor", 18.99, 5.5, "2026-06-15", "成长", "low_stock"),
    ("A018", "Neck Massager", "Health", 42.99, 14.0, "2026-01-20", "衰退", "decline"),
    ("A019", "Travel Backpack", "Luggage", 49.99, 13.0, "2026-04-01", "成长", "high_margin"),
    ("A020", "Electric Kettle", "Kitchen", 33.99, 11.0, "2026-02-20", "成熟", "high_acos"),
]

# 基础日均订单量（按标签）
BASE_ORDERS = {
    "hot": 50, "normal": 20, "new": 8, "high_acos": 25,
    "low_stock": 30, "decline": 18, "high_margin": 15,
}


def gen_daily_orders(base, label, day_idx):
    """某 SKU 某天的订单量（近7天为 idx 23~29）。"""
    rnd = np.random.uniform(0.88, 1.12)
    if label == "decline":
        # 前23天正常，近7天下降约32%
        factor = 0.68 if day_idx >= 23 else 1.0
    elif label == "hot":
        factor = 1.0
    elif label == "new":
        # 新品，后期逐步起量
        factor = 1.0 + 0.03 * day_idx
    else:
        factor = 1.0
    return max(0, round(base * factor * rnd))


def gen_sessions(base, label, day_idx, orders):
    """按转化率反推会话数（Sessions）。"""
    cvr = 0.09
    if label == "decline" and day_idx >= 23:
        cvr = 0.07  # 转化率也略降
    if label == "new":
        cvr = 0.06
    return max(orders, round(orders / cvr))


# ---------------------------------------------------------------------------
# 1) 产品表 Product
# ---------------------------------------------------------------------------
prod_rows = []
for sku, name, cat, price, cost, launch, stage, label in SKUS:
    prod_rows.append([sku, name, cat, price, cost, launch, stage])
prod_df = pd.DataFrame(prod_rows, columns=["SKU", "产品名称", "类目", "售价", "成本", "上架日期", "产品阶段"])

# ---------------------------------------------------------------------------
# 2) Listing
# ---------------------------------------------------------------------------
listing_status = {
    "A001": ("✅", "✅", "✅", "✅", "优化完成"),
    "A002": ("✅", "✅", "✅", "✅", "优化完成"),
    "A003": ("✅", "✅", "✅", "⚠️", "关键词待优化"),
    "A004": ("✅", "✅", "✅", "✅", "优化完成"),
    "A005": ("✅", "⚠️", "✅", "✅", "五点待优化"),
    "A006": ("✅", "✅", "✅", "✅", "优化完成"),
    "A007": ("✅", "✅", "✅", "⚠️", "关键词待优化"),
    "A008": ("✅", "✅", "✅", "✅", "优化完成"),
    "A009": ("✅", "✅", "✅", "✅", "优化完成"),
    "A010": ("⚠️", "✅", "✅", "✅", "标题待优化"),
    "A011": ("✅", "⚠️", "✅", "⚠️", "新品待完善"),
    "A012": ("✅", "✅", "⚠️", "⚠️", "新品待完善"),
    "A013": ("✅", "✅", "✅", "⚠️", "关键词待优化"),
    "A014": ("✅", "✅", "✅", "✅", "优化完成"),
    "A015": ("✅", "✅", "✅", "✅", "优化完成"),
    "A016": ("✅", "✅", "✅", "✅", "优化完成"),
    "A017": ("✅", "✅", "✅", "✅", "优化完成"),
    "A018": ("✅", "✅", "✅", "✅", "优化完成"),
    "A019": ("✅", "✅", "✅", "✅", "优化完成"),
    "A020": ("✅", "✅", "✅", "⚠️", "关键词待优化"),
}
listing_rows = []
for sku, name, cat, price, cost, launch, stage, label in SKUS:
    title_flag, bp_flag, img_flag, kw_flag, status = listing_status[sku]
    title = f"{name} for Home and Travel, Durable Easy-to-Use Design"
    if sku == "A010":
        title = f"BEST #1 {name} - 100% Guaranteed Results"
    elif title_flag == "⚠️":
        title = name
    bullets = "Durable material；Easy to use；Compact design；Simple care；Everyday value"
    if bp_flag == "⚠️":
        bullets = "Durable material；Easy to use"
    main_image = "合规" if img_flag == "✅" else "缺失"
    keywords = f"{name.lower()}, {cat.lower()}, daily use" if kw_flag == "✅" else ""
    brand_risk = "待核验" if sku in ("A012", "A018") else "未发现"
    variation_status = "待检查" if sku in ("A011", "A013") else "正常"
    listing_rows.append([sku, title, bullets, main_image, keywords, brand_risk, variation_status, status])
listing_df = pd.DataFrame(listing_rows, columns=["SKU", "Title", "Bullet Points", "Main Image", "Search Terms", "Brand Risk", "Variation Status", "Status"])

# ---------------------------------------------------------------------------
# 3) 销售表 Sales（20 SKU × 30 天）
# ---------------------------------------------------------------------------
sales_rows = []
for sku, name, cat, price, cost, launch, stage, label in SKUS:
    base = BASE_ORDERS[label]
    for i, d in enumerate(DATE_STR):
        orders = gen_daily_orders(base, label, i)
        sessions = gen_sessions(base, label, i, orders)
        sales = round(orders * price, 2)
        # 退款率：正常约3%，decline 略高
        refund_rate = 0.03 if label != "decline" else 0.06
        refund = round(sales * refund_rate * np.random.uniform(0.5, 1.5), 2)
        sales_rows.append([d, sku, orders, sessions, sales, refund])
sales_df = pd.DataFrame(sales_rows, columns=["日期", "SKU", "订单量", "Session", "销售额", "退款金额"])

# ---------------------------------------------------------------------------
# 4) 库存表 Inventory
# ---------------------------------------------------------------------------
inv_rows = []
for sku, name, cat, price, cost, launch, stage, label in SKUS:
    base = BASE_ORDERS[label]
    daily = base
    if label == "low_stock":
        current = round(daily * 12)   # 约12天，触发高风险
        safety = round(daily * 15)
    elif label == "hot":
        current = round(daily * 35)
        safety = round(daily * 20)
    elif label == "decline":
        current = round(daily * 45)
        safety = round(daily * 20)
    elif label == "new":
        current = round(daily * 25)
        safety = round(daily * 15)
    else:
        current = round(daily * 40)
        safety = round(daily * 20)
    inbound = round(daily * 10) if label != "low_stock" else 0
    lead_time = 35 if label == "low_stock" else (30 if label in ("new", "hot") else 25)
    eta = (END + timedelta(days=lead_time)).strftime("%Y-%m-%d") if inbound else ""
    inv_rows.append([sku, current, inbound, daily, safety, END.strftime("%Y-%m-%d"), lead_time, eta])
inv_df = pd.DataFrame(inv_rows, columns=["SKU", "当前库存", "在途库存", "日均销量", "安全库存", "数据日期", "采购周期天", "预计到仓日期"])

# ---------------------------------------------------------------------------
# 5) 广告表 Advertising（20 SKU × 30 天）
# ---------------------------------------------------------------------------
ad_rows = []
for sku, name, cat, price, cost, launch, stage, label in SKUS:
    base = BASE_ORDERS[label]
    for i, d in enumerate(DATE_STR):
        orders = gen_daily_orders(base, label, i)
        sales = round(orders * price, 2)
        # 广告销售额约为总销售的 50%
        ad_sales = round(sales * 0.5, 2)
        # ACOS 设计
        if label == "high_acos":
            # 成熟品 ACOS 突然升高：前23天25%，近7天42%
            acos = 0.42 if i >= 23 else 0.25
        elif label == "new":
            # 新品高 ACOS 40%（新品期允许）
            acos = 0.40
        elif label == "decline":
            acos = 0.35
        else:
            acos = 0.24
        spend = round(ad_sales * acos, 2)
        # 点击、曝光：CPC 约 $0.8，CTR 约 0.5%
        clicks = round(spend / 0.8)
        impressions = round(clicks / 0.005)
        ad_rows.append([d, sku, spend, ad_sales, clicks, impressions])
ad_df = pd.DataFrame(ad_rows, columns=["日期", "SKU", "广告花费", "广告销售额", "点击", "曝光"])

# ---------------------------------------------------------------------------
# 6) 搜索词表（每 SKU 4 条，模拟可执行的关键词诊断场景）
# ---------------------------------------------------------------------------
search_rows = []
match_types = ["精准", "词组", "广泛", "自动"]
for sku, name, cat, price, cost, launch, stage, label in SKUS:
    terms = [name.lower(), f"best {name.lower()}", f"cheap {cat.lower()}", f"{name.lower()} accessory"]
    for idx, term in enumerate(terms):
        impressions = 12000 - idx * 1800 + np.random.randint(-500, 500)
        clicks = max(1, round(impressions * (0.006 - idx * 0.0008)))
        spend = round(clicks * (0.75 + idx * 0.12), 2)
        if idx == 0:
            orders = max(2, round(clicks * 0.12))
        elif idx == 1:
            orders = max(1, round(clicks * 0.07))
        elif idx == 2:
            orders = 0  # 高花费无订单：否定词候选
        else:
            orders = max(1, round(clicks * 0.035))
        ad_sales = round(orders * price, 2)
        search_rows.append([
            sku, f"SP-{sku}-Core", f"AG-{sku}", match_types[idx],
            name.lower(), term, impressions, clicks, spend, orders, ad_sales,
        ])
search_df = pd.DataFrame(search_rows, columns=["SKU", "广告活动", "广告组", "匹配方式", "关键词", "搜索词", "曝光", "点击", "广告花费", "广告订单", "广告销售额"])

# ---------------------------------------------------------------------------
# 7) 竞品表 Competitor
# ---------------------------------------------------------------------------
competitor_data = {
    "A001": ("Competitor X", 42.99, 4.5, 3200, "大容量电机"),
    "A002": ("Competitor Y", 35.99, 4.3, 1800, "静音设计"),
    "A003": ("Competitor Z", 22.99, 4.2, 950, "无频闪"),
    "A004": ("Competitor X", 24.99, 4.6, 5100, "加厚防滑"),
    "A005": ("Competitor Y", 10.99, 4.0, 700, "折叠便携"),
    "A006": ("Competitor Z", 25.99, 4.7, 6800, "24h保温"),
    "A007": ("Competitor X", 19.99, 4.1, 1100, "多格收纳"),
    "A008": ("Competitor Y", 34.99, 4.4, 2400, "快充15W"),
    "A009": ("Competitor Z", 9.99, 4.0, 400, "可重复使用"),
    "A010": ("Competitor X", 18.99, 4.5, 3900, "多阻力级别"),
    "A011": ("Competitor Y", 69.99, 4.2, 620, "2K画质"),
    "A012": ("Competitor Z", 49.99, 4.3, 1500, "大吸力"),
    "A013": ("Competitor X", 39.99, 4.1, 800, "负离子护发"),
    "A014": ("Competitor Y", 24.99, 4.4, 2600, "陶瓷磨芯"),
    "A015": ("Competitor Z", 29.99, 4.6, 4500, "铝合金散热"),
    "A016": ("Competitor X", 32.99, 4.3, 1300, "专业修剪"),
    "A017": ("Competitor Y", 16.99, 4.0, 900, "防水太阳能"),
    "A018": ("Competitor Z", 45.99, 4.2, 2000, "多模式按摩"),
    "A019": ("Competitor X", 55.99, 4.7, 7800, "大容量防盗"),
    "A020": ("Competitor Y", 36.99, 4.4, 3100, "快速烧水"),
}
comp_rows = []
for sku, name, cat, price, cost, launch, stage, label in SKUS:
    comp_name, comp_price, rating, reviews, selling = competitor_data[sku]
    comp_asin = f"B0SIM{int(sku[1:]):05d}"
    comp_rows.append([sku, comp_asin, comp_name, comp_price, rating, reviews, selling, "模拟数据（非真实抓取）", DATE_STR[-1]])
comp_df = pd.DataFrame(comp_rows, columns=["SKU", "竞品ASIN", "竞品名", "竞品价格", "Rating", "Reviews", "核心卖点", "数据来源", "采集日期"])

# ---------------------------------------------------------------------------
# 8) 利润表 Profit（近30天汇总，每 SKU 一行）
# ---------------------------------------------------------------------------
# 平台费 + 物流费 简化为销售额的固定比例
PLATFORM_FEE_RATE = 0.15   # 平台佣金
LOGISTICS_FEE_RATE = 0.12  # 物流费

profit_rows = []
for sku, name, cat, price, cost, launch, stage, label in SKUS:
    s = sales_df[sales_df["SKU"] == sku]
    total_sales = s["销售额"].sum()
    total_orders = s["订单量"].sum()
    total_refund = s["退款金额"].sum()
    ad = ad_df[ad_df["SKU"] == sku]
    total_ad_spend = ad["广告花费"].sum()
    cogs = total_orders * cost  # 产品成本
    platform_fee = total_sales * PLATFORM_FEE_RATE
    logistics_fee = total_sales * LOGISTICS_FEE_RATE
    profit = total_sales - total_refund - cogs - total_ad_spend - platform_fee - logistics_fee
    margin = profit / total_sales if total_sales else 0
    profit_rows.append([sku, total_sales, cogs, total_ad_spend, platform_fee + logistics_fee, total_refund, profit, margin])
profit_df = pd.DataFrame(profit_rows, columns=["SKU", "销售额", "产品成本", "广告花费", "平台及物流费", "退款金额", "利润", "毛利率"])

# ---------------------------------------------------------------------------
# 写出 CSV
# ---------------------------------------------------------------------------
out = {
    "产品表": prod_df,
    "Listing": listing_df,
    "销售表": sales_df,
    "库存表": inv_df,
    "广告表": ad_df,
    "搜索词表": search_df,
    "竞品表": comp_df,
    "利润表": profit_df,
}
parser = argparse.ArgumentParser(description="生成项目示例数据")
parser.add_argument("--table", choices=list(out), help="只生成指定数据表；默认生成全部")
args = parser.parse_args()
selected_output = {args.table: out[args.table]} if args.table else out
for name, df in selected_output.items():
    path = f"data/{name}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"已生成 {name}.csv（{len(df)} 行）")

print("\n20 个 SKU 分布：高销量3 / 普通7 / 新品3 / 高ACOS2 / 库存预警2 / 销量下降2 / 高毛利1")
