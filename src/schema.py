# -*- coding: utf-8 -*-
"""
字段规范定义：亚马逊运营分析工作台的规范字段、映射别名、表类型识别。

8 张数据表：
  产品表 Product      — SKU、产品名称、类目、售价、成本、上架日期、产品阶段
  Listing             — SKU、Title、Bullet Points、Main Image、Search Terms、Status
  销售表 Sales         — 日期、SKU、订单量、Session、销售额、退款金额
  库存表 Inventory     — SKU、当前库存、在途库存、日均销量、安全库存
  广告表 Advertising   — 日期、SKU、广告花费、广告销售额、点击、曝光
  搜索词表 Search Term  — SKU、广告活动、关键词、搜索词、曝光、点击、花费、订单、销售额
  竞品表 Competitor    — SKU、ASIN、价格、Rating、Reviews、卖点、来源、采集日期
  利润表 Profit        — SKU、销售额、产品成本、广告花费、平台及物流费、退款、利润、毛利率
"""
import re

TABLE_PRODUCT = "产品表"
TABLE_LISTING = "Listing"
TABLE_SALES = "销售表"
TABLE_INVENTORY = "库存表"
TABLE_ADS = "广告表"
TABLE_SEARCH_TERMS = "搜索词表"
TABLE_COMPETITOR = "竞品表"
TABLE_PROFIT = "利润表"

SCHEMA = {
    TABLE_PRODUCT: ["SKU", "产品名称", "类目", "售价", "成本", "上架日期", "产品阶段"],
    TABLE_LISTING: ["SKU", "Title", "Bullet Points", "Main Image", "Search Terms", "Brand Risk", "Variation Status", "Status"],
    TABLE_SALES: ["日期", "SKU", "订单量", "Session", "销售额", "退款金额"],
    TABLE_INVENTORY: ["SKU", "当前库存", "在途库存", "日均销量", "安全库存", "数据日期", "采购周期天", "预计到仓日期"],
    TABLE_ADS: ["日期", "SKU", "广告花费", "广告销售额", "点击", "曝光"],
    TABLE_SEARCH_TERMS: ["SKU", "广告活动", "广告组", "匹配方式", "关键词", "搜索词", "曝光", "点击", "广告花费", "广告订单", "广告销售额"],
    TABLE_COMPETITOR: ["SKU", "竞品ASIN", "竞品名", "竞品价格", "Rating", "Reviews", "核心卖点", "数据来源", "采集日期"],
    TABLE_PROFIT: ["SKU", "销售额", "产品成本", "广告花费", "平台及物流费", "退款金额", "利润", "毛利率"],
}

REQUIRED = {
    TABLE_PRODUCT: ["SKU", "产品名称", "售价", "成本"],
    TABLE_LISTING: ["SKU", "Status"],
    TABLE_SALES: ["日期", "SKU", "订单量", "销售额"],
    TABLE_INVENTORY: ["SKU", "当前库存", "日均销量"],
    TABLE_ADS: ["日期", "SKU", "广告花费", "广告销售额"],
    TABLE_SEARCH_TERMS: ["SKU", "搜索词", "广告花费", "广告销售额"],
    TABLE_COMPETITOR: ["SKU", "竞品名", "竞品价格"],
    TABLE_PROFIT: ["SKU", "销售额", "利润"],
}

FIELD_ALIASES = {
    "日期": ["日期", "date", "时间", "下单日期", "业务日期", "日期时间"],
    "SKU": ["sku", "产品编码", "商品编码", "货号", "asin", "fnsku", "商品编号", "产品sku"],
    "产品名称": ["产品名称", "商品名称", "品名", "title", "商品", "产品名"],
    "类目": ["类目", "分类", "品类", "category", "类目名称"],
    "售价": ["售价", "价格", "price", "销售价", "单价", "售价($)"],
    "成本": ["成本", "cost", "采购成本", "成本价", "单位成本"],
    "上架日期": ["上架日期", "上架时间", "上市日期", "launch", "发布日期"],
    "产品阶段": ["产品阶段", "阶段", "产品周期", "stage", "生命周期"],
    "Title": ["title", "标题", "产品标题", "listing标题"],
    "Bullet Points": ["bullet points", "bullet", "bullets", "五点", "五点描述", "五点卖点"],
    "Main Image": ["main image", "主图", "图片", "主图片", "image", "首图"],
    "Search Terms": ["search terms", "backend search terms", "listing keywords", "listing关键词"],
    "关键词": ["关键词", "keywords", "搜索词", "keyword"],
    "Status": ["status", "状态", "listing状态", "优化状态"],
    "Brand Risk": ["brand risk", "品牌风险", "品牌词风险", "侵权风险"],
    "Variation Status": ["variation status", "变体状态", "变体关系"],
    "订单量": ["订单量", "orders", "销量", "件数", "订单数", "成交件数", "销售件数", "数量"],
    "Session": ["session", "sessions", "会话数", "访问量", "流量", "uv", "浏览量", "访客数"],
    "销售额": ["销售额", "sales", "gmv", "销售金额", "订单金额", "销售总额"],
    "退款金额": ["退款金额", "退款", "refund", "退款额"],
    "当前库存": ["当前库存", "库存", "库存量", "stock", "可售库存", "fba库存", "现库存"],
    "在途库存": ["在途库存", "在途", "inbound", "待入库", "在途数量"],
    "日均销量": ["日均销量", "日销", "日均订单", "daily sales"],
    "安全库存": ["安全库存", "safety stock", "安全线"],
    "数据日期": ["数据日期", "快照日期", "snapshot date"],
    "采购周期天": ["采购周期天", "采购周期", "补货周期", "lead time", "lead time days"],
    "预计到仓日期": ["预计到仓日期", "到仓日期", "预计入库日期", "eta"],
    "广告花费": ["广告花费", "广告费", "ad spend", "spend", "花费", "广告支出"],
    "广告销售额": ["广告销售额", "ad sales", "广告收入", "广告产出", "广告销售金额"],
    "点击": ["点击", "clicks", "点击量", "点击数"],
    "曝光": ["曝光", "impressions", "展示", "曝光量", "展示量"],
    "广告活动": ["广告活动", "campaign", "campaign name", "广告活动名称"],
    "广告组": ["广告组", "ad group", "ad group name", "广告组名称"],
    "匹配方式": ["匹配方式", "match type", "匹配类型"],
    "搜索词": ["搜索词", "customer search term", "search term"],
    "广告订单": ["广告订单", "ad orders", "7 day total orders", "广告订单量"],
    "竞品名": ["竞品名", "竞品名称", "competitor", "竞品"],
    "竞品ASIN": ["竞品asin", "competitor asin", "asin"],
    "竞品价格": ["竞品价格", "竞品价", "comp price", "竞品售价"],
    "Rating": ["rating", "评分", "星级"],
    "Reviews": ["reviews", "评论数", "评价数"],
    "核心卖点": ["核心卖点", "卖点", "selling point", "优势"],
    "数据来源": ["数据来源", "来源", "source", "采集来源"],
    "采集日期": ["采集日期", "抓取日期", "观察日期", "collection date"],
    "产品成本": ["产品成本", "cogs", "货物成本", "商品成本"],
    "平台及物流费": ["平台及物流费", "平台费", "物流费", "fees", "费用"],
    "利润": ["利润", "profit", "净利"],
    "毛利率": ["毛利率", "margin", "利润率", "毛利"],
}

NUMERIC_FIELDS = {
    "售价", "成本", "订单量", "Session", "销售额", "退款金额",
    "当前库存", "在途库存", "日均销量", "安全库存", "采购周期天",
    "广告花费", "广告销售额", "点击", "曝光", "广告订单",
    "竞品价格", "Rating", "Reviews",
    "产品成本", "平台及物流费", "利润", "毛利率",
}

DATE_FIELDS = {"日期", "上架日期", "数据日期", "预计到仓日期", "采集日期"}


def normalize_name(s):
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = s.replace("_", "").replace("-", "").replace("　", "")
    return s


def suggest_mapping(columns):
    """给一组上传列名建议映射到规范字段。返回 dict: {原始列名: 规范字段名 或 None}"""
    result = {}
    canonical_names = {normalize_name(field): field for field in FIELD_ALIASES}
    norm_aliases = {}
    for field, aliases in FIELD_ALIASES.items():
        for a in aliases:
            norm_aliases.setdefault(normalize_name(a), field)

    for col in columns:
        ncol = normalize_name(col)
        matched = None
        # 规范字段名必须优先于别名。例如“搜索词”既可能是 Listing 的
        # 关键词别名，也是真正的搜索词字段，直接上传规范表时不能被覆盖。
        if ncol in canonical_names:
            matched = canonical_names[ncol]
        elif ncol in norm_aliases:
            matched = norm_aliases[ncol]
        else:
            hits = {}
            for anorm, field in norm_aliases.items():
                if len(anorm) >= 2 and (anorm in ncol or ncol in anorm):
                    hits[field] = max(hits.get(field, 0), len(anorm))
            if hits:
                best_len = max(hits.values())
                best_fields = [f for f, l in hits.items() if l == best_len]
                matched = best_fields[0] if len(best_fields) == 1 else None
        result[col] = matched
    return result
