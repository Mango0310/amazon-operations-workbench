# -*- coding: utf-8 -*-
"""
指标计算引擎：纯 Pandas 逻辑，不依赖 AI。

输入：tables 字典 {表类型: DataFrame（规范字段）}
输出：KPI、趋势、SKU 维度指标、经营分析、SKU 深度诊断。
"""
import pandas as pd

from .schema import (
    TABLE_PRODUCT, TABLE_SALES, TABLE_INVENTORY, TABLE_ADS, TABLE_PROFIT,
)


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _windows(tables):
    """返回 (近7天起, 近7天止, 前7天起, 前7天止, 最新日期)。"""
    sales = tables[TABLE_SALES]
    d = pd.to_datetime(sales["日期"], errors="coerce")
    latest = d.max()
    recent_start = latest - pd.Timedelta(days=6)
    recent_end = latest
    prior_start = latest - pd.Timedelta(days=13)
    prior_end = latest - pd.Timedelta(days=7)
    return recent_start, recent_end, prior_start, prior_end, latest


def _in_window(df, col, start, end):
    d = pd.to_datetime(df[col], errors="coerce")
    return df[(d >= start) & (d <= end)]


def _sum(df, col):
    return _num(df[col]).sum()


def _get(tables, key):
    return tables.get(key)


# ===========================================================================
# 总体 KPI（近30天）
# ===========================================================================
def compute_overview(tables):
    """
    返回 KPI 卡片列表，每项: {"label", "value", "delta"}
    近30天口径。
    """
    sales = tables[TABLE_SALES]
    ads = _get(tables, TABLE_ADS)
    inv = _get(tables, TABLE_INVENTORY)
    profit = _get(tables, TABLE_PROFIT)

    rs, re_, ps, pe, latest = _windows(tables)
    recent = _in_window(sales, "日期", rs, re_)
    prior = _in_window(sales, "日期", ps, pe)

    r_sales = _sum(recent, "销售额")
    p_sales = _sum(prior, "销售额")
    r_orders = _sum(recent, "订单量")

    # 全30天
    total_sales = _sum(sales, "销售额")
    total_orders = _sum(sales, "订单量")

    # 广告（近7天）
    acos = roas = ctr = cpc = None
    if ads is not None:
        r_ads = _in_window(ads, "日期", rs, re_)
        r_spend = _sum(r_ads, "广告花费")
        r_ad_sales = _sum(r_ads, "广告销售额")
        r_clicks = _sum(r_ads, "点击")
        r_impressions = _sum(r_ads, "曝光")
        acos = r_spend / r_ad_sales if r_ad_sales else None
        roas = r_ad_sales / r_spend if r_spend else None
        ctr = r_clicks / r_impressions if r_impressions else None
        cpc = r_spend / r_clicks if r_clicks else None
    else:
        r_spend = None

    # 毛利率（从利润表）
    margin = None
    if profit is not None and "毛利率" in profit.columns:
        total_profit = _sum(profit, "利润")
        total_profit_sales = _sum(profit, "销售额")
        margin = total_profit / total_profit_sales if total_profit_sales else None

    # 库存可售天数（总）
    days_total = None
    if inv is not None:
        total_stock = _sum(inv, "当前库存")
        total_daily = _sum(inv, "日均销量")
        days_total = total_stock / total_daily if total_daily else None

    def pct(cur, base):
        return (cur - base) / base if base else None

    def fmt_pct(x):
        return f"{x*100:+.1f}%" if x is not None else "—"

    cards = [
        {"label": "销售额（近7天）", "value": f"${r_sales:,.0f}", "delta": fmt_pct(pct(r_sales, p_sales))},
        {"label": "订单量（近7天）", "value": f"{r_orders:,.0f}", "delta": None},
        {"label": "广告花费（近7天）", "value": f"${r_spend:,.0f}" if r_spend is not None else "—", "delta": None},
        {"label": "ACOS", "value": f"{acos*100:.1f}%" if acos is not None else "—", "delta": None},
        {"label": "ROAS", "value": f"{roas:.2f}" if roas is not None else "—", "delta": None},
        {"label": "毛利率", "value": f"{margin*100:.1f}%" if margin is not None else "—", "delta": None},
        {"label": "库存可售天数", "value": f"{days_total:.0f}天" if days_total is not None else "—", "delta": None},
        {"label": "CTR", "value": f"{ctr*100:.2f}%" if ctr is not None else "—", "delta": None},
        {"label": "CPC", "value": f"${cpc:.2f}" if cpc is not None else "—", "delta": None},
    ]
    return cards


# ===========================================================================
# 每日趋势（近30天）
# ===========================================================================
def compute_daily_trend(tables):
    """返回按日汇总：日期、销售额、订单量、广告花费。"""
    sales = tables[TABLE_SALES]
    ads = _get(tables, TABLE_ADS)

    s = sales.groupby("日期", as_index=False).agg(
        销售额=("销售额", "sum"),
        订单量=("订单量", "sum"),
    )
    s["日期"] = pd.to_datetime(s["日期"])

    if ads is not None:
        a = ads.groupby("日期", as_index=False).agg(广告花费=("广告花费", "sum"))
        a["日期"] = pd.to_datetime(a["日期"])
        df = s.merge(a, on="日期", how="left")
    else:
        df = s
        df["广告花费"] = 0
    df["广告花费"] = df["广告花费"].fillna(0)
    df = df.sort_values("日期")
    df["日期"] = df["日期"].dt.strftime("%Y-%m-%d")
    return df


# ===========================================================================
# SKU 维度指标
# ===========================================================================
def compute_sku_metrics(tables):
    """
    返回按 SKU 汇总的指标表。
    列：SKU、产品名称、类目、售价、成本、产品阶段、销售额、订单量、销售环比、
        Session、CVR、广告花费、ACOS、TACOS、ROAS、CTR、CPC、当前库存、可售天数、毛利率
    """
    sales = tables[TABLE_SALES]
    prod = _get(tables, TABLE_PRODUCT)
    ads = _get(tables, TABLE_ADS)
    inv = _get(tables, TABLE_INVENTORY)
    profit = _get(tables, TABLE_PROFIT)

    rs, re_, ps, pe, latest = _windows(tables)
    recent = _in_window(sales, "日期", rs, re_)
    prior = _in_window(sales, "日期", ps, pe)

    g_recent = recent.groupby("SKU").agg(
        销售额=("销售额", "sum"),
        订单量=("订单量", "sum"),
        Session=("Session", "sum"),
    )
    g_prior = prior.groupby("SKU").agg(前7天销售额=("销售额", "sum"))

    df = g_recent.join(g_prior, how="left")
    df["前7天销售额"] = df["前7天销售额"].fillna(0)
    df["销售环比"] = (df["销售额"] - df["前7天销售额"]) / df["前7天销售额"].replace(0, pd.NA)
    df["CVR"] = df["订单量"] / df["Session"].replace(0, pd.NA)

    # 广告（近7天）
    if ads is not None:
        a_recent = _in_window(ads, "日期", rs, re_).groupby("SKU").agg(
            广告花费=("广告花费", "sum"),
            广告销售额=("广告销售额", "sum"),
            点击=("点击", "sum"),
            曝光=("曝光", "sum"),
        )
        df = df.join(a_recent, how="left")
        for c in ["广告花费", "广告销售额", "点击", "曝光"]:
            df[c] = df[c].fillna(0)
        df["ACOS"] = df["广告花费"] / df["广告销售额"].replace(0, pd.NA)
        # TACOS 以全部销售额为分母，用于判断广告投入对整体经营利润的影响。
        df["TACOS"] = df["广告花费"] / df["销售额"].replace(0, pd.NA)
        df["ROAS"] = df["广告销售额"] / df["广告花费"].replace(0, pd.NA)
        df["CTR"] = df["点击"] / df["曝光"].replace(0, pd.NA)
        df["CPC"] = df["广告花费"] / df["点击"].replace(0, pd.NA)
    else:
        for c in ["广告花费", "广告销售额", "点击", "曝光", "ACOS", "TACOS", "ROAS", "CTR", "CPC"]:
            df[c] = pd.NA

    # 库存：可售天数 = 当前库存 / 日均销量
    if inv is not None:
        inv_map = inv.set_index("SKU")[["当前库存", "在途库存", "日均销量", "安全库存"]]
        df = df.join(inv_map, how="left")
        df["可售天数"] = df["当前库存"] / df["日均销量"].replace(0, pd.NA)
    else:
        for c in ["当前库存", "在途库存", "日均销量", "安全库存", "可售天数"]:
            df[c] = pd.NA

    # 产品信息
    if prod is not None:
        prod_map = prod.set_index("SKU")[["产品名称", "类目", "售价", "成本", "产品阶段"]]
        df = df.join(prod_map, how="left")
    else:
        for c in ["产品名称", "类目", "售价", "成本", "产品阶段"]:
            df[c] = pd.NA

    # 毛利率
    if profit is not None and "毛利率" in profit.columns:
        profit_map = profit.set_index("SKU")["毛利率"]
        df = df.join(profit_map.rename("毛利率"), how="left")
    else:
        df["毛利率"] = pd.NA

    df = df.reset_index()
    return df


# ===========================================================================
# 经营分析（解读，纯规则）
# ===========================================================================
ACOS_TARGET = 0.30
ACOS_NEW_TOLERANCE = 0.45  # 新品期可容忍较高 ACOS


def analyze_business(tables):
    """
    生成经营分析结论。返回 dict：
      销售 / 广告 / 库存 / 利润 四维度解读 + 亮点 + 问题 + 建议
    """
    sales = tables[TABLE_SALES]
    ads = _get(tables, TABLE_ADS)
    profit = _get(tables, TABLE_PROFIT)

    rs, re_, ps, pe, latest = _windows(tables)
    recent = _in_window(sales, "日期", rs, re_)
    prior = _in_window(sales, "日期", ps, pe)

    r_sales = _sum(recent, "销售额")
    p_sales = _sum(prior, "销售额")
    sales_mom = (r_sales - p_sales) / p_sales if p_sales else None

    analysis = {}

    # 销售
    if sales_mom is None:
        analysis["销售"] = "销售数据不足。"
    elif sales_mom <= -0.2:
        analysis["销售"] = f"近7天销售额 ${r_sales:,.0f}，环比 {sales_mom*100:.1f}%，明显下滑，需排查流量和转化。"
    elif sales_mom <= -0.05:
        analysis["销售"] = f"近7天销售额 ${r_sales:,.0f}，环比 {sales_mom*100:.1f}%，小幅回落。"
    elif sales_mom >= 0.05:
        analysis["销售"] = f"近7天销售额 ${r_sales:,.0f}，环比 {sales_mom*100:+.1f}%，增长良好。"
    else:
        analysis["销售"] = f"近7天销售额 ${r_sales:,.0f}，环比 {sales_mom*100:+.1f}%，基本持平。"

    # 广告
    if ads is not None:
        r_ads = _in_window(ads, "日期", rs, re_)
        r_spend = _sum(r_ads, "广告花费")
        r_ad_sales = _sum(r_ads, "广告销售额")
        acos = r_spend / r_ad_sales if r_ad_sales else None
        if acos is None:
            analysis["广告"] = "无广告数据。"
        elif acos > 0.40:
            analysis["广告"] = f"ACOS {acos*100:.1f}%，广告成本偏高，需结合产品阶段判断是否优化。"
        elif acos > ACOS_TARGET:
            analysis["广告"] = f"ACOS {acos*100:.1f}%，超过30%目标线，建议检查高花费关键词。"
        else:
            analysis["广告"] = f"ACOS {acos*100:.1f}%，广告效率健康。"
    else:
        analysis["广告"] = "无广告数据。"

    # 库存
    m = compute_sku_metrics(tables)
    if "可售天数" in m.columns:
        low = m[(m["可售天数"].notna()) & (m["可售天数"] <= 15)]
        warn = m[(m["可售天数"].notna()) & (m["可售天数"] > 15) & (m["可售天数"] <= 30)]
        if len(low):
            names = "、".join(low["SKU"].head(4).tolist())
            analysis["库存"] = f"{len(low)} 个 SKU 可售天数 ≤15 天（高风险）：{names}。"
        elif len(warn):
            analysis["库存"] = f"{len(warn)} 个 SKU 可售 16-30 天（预警）。"
        else:
            analysis["库存"] = "库存整体健康。"
    else:
        analysis["库存"] = "无库存数据。"

    # 利润
    if profit is not None and "毛利率" in profit.columns:
        total_profit = _sum(profit, "利润")
        margin = total_profit / _sum(profit, "销售额") if _sum(profit, "销售额") else None
        analysis["利润"] = f"整体毛利率 {margin*100:.1f}%，净利润 ${total_profit:,.0f}。" if margin is not None else "利润数据不足。"
    else:
        analysis["利润"] = "无利润数据。"

    # 亮点 / 问题
    highlights, problems = [], []
    if "销售环比" in m.columns and "产品名称" in m.columns:
        up = m[m["销售环比"].notna()].sort_values("销售环比", ascending=False)
        down = m[m["销售环比"].notna()].sort_values("销售环比", ascending=True)
        if len(up) and up.iloc[0]["销售环比"] > 0.05:
            highlights.append(f"{up.iloc[0]['产品名称']} 销售环比 {up.iloc[0]['销售环比']*100:+.1f}%，增长最快")
        for _, r in down.head(3).iterrows():
            if r["销售环比"] <= -0.2:
                problems.append(f"{r['产品名称']} 销售下降 {r['销售环比']*100:.1f}%")
        if "ACOS" in m.columns:
            acos_high = m[m["ACOS"].notna()].sort_values("ACOS", ascending=False)
            for _, r in acos_high.head(2).iterrows():
                if r["ACOS"] > 0.40:
                    problems.append(f"{r['产品名称']} ACOS {r['ACOS']*100:.1f}%（需结合产品阶段判断）")

    analysis["亮点"] = highlights or ["暂无特别突出的增长点"]
    analysis["问题"] = problems or ["暂无需要重点关注的问题"]

    # 建议
    suggestions = []
    if sales_mom is not None and sales_mom <= -0.05:
        suggestions.append("销售环比下滑，排查流量/转化变化")
    if ads is not None:
        r_ads = _in_window(ads, "日期", rs, re_)
        r_spend = _sum(r_ads, "广告花费")
        r_ad_sales = _sum(r_ads, "广告销售额")
        acos = r_spend / r_ad_sales if r_ad_sales else None
        if acos is not None and acos > ACOS_TARGET:
            suggestions.append("ACOS 超标，检查高花费低转化关键词")
    if "可售天数" in m.columns:
        n_low = len(m[(m["可售天数"].notna()) & (m["可售天数"] <= 15)])
        if n_low:
            suggestions.append(f"优先处理 {n_low} 个可售天数≤15天的 SKU 补货")
    if not suggestions:
        suggestions.append("整体经营健康，持续监控")
    analysis["建议"] = suggestions

    return analysis


# ===========================================================================
# 单 SKU 深度诊断（供快速经营问数）
# ===========================================================================
def analyze_sku(tables, sku):
    """
    针对单个 SKU 深度分析：销售/流量/转化/广告/库存/利润 + 原因 + 判断 + 建议。
    """
    sales = tables[TABLE_SALES]
    prod = _get(tables, TABLE_PRODUCT)
    ads = _get(tables, TABLE_ADS)
    inv = _get(tables, TABLE_INVENTORY)
    profit = _get(tables, TABLE_PROFIT)

    rs, re_, ps, pe, latest = _windows(tables)
    recent = _in_window(sales, "日期", rs, re_)
    prior = _in_window(sales, "日期", ps, pe)
    recent = recent[recent["SKU"] == sku]
    prior = prior[prior["SKU"] == sku]

    name = sku
    price = cost = stage = None
    if prod is not None:
        pr = prod[prod["SKU"] == sku]
        if len(pr):
            name = pr.iloc[0].get("产品名称", sku)
            price = pr.iloc[0].get("售价", None)
            cost = pr.iloc[0].get("成本", None)
            stage = pr.iloc[0].get("产品阶段", None)

    r_sales = _sum(recent, "销售额")
    p_sales = _sum(prior, "销售额")
    r_orders = _sum(recent, "订单量")
    r_sessions = _sum(recent, "Session")
    p_sessions = _sum(prior, "Session")

    sales_mom = (r_sales - p_sales) / p_sales if p_sales else None
    sess_mom = (r_sessions - p_sessions) / p_sessions if p_sessions else None
    cvr = r_orders / r_sessions if r_sessions else None

    acos = roas = None
    if ads is not None:
        r_ads = _in_window(ads, "日期", rs, re_)
        r_ads = r_ads[r_ads["SKU"] == sku]
        spend = _sum(r_ads, "广告花费")
        ad_sales = _sum(r_ads, "广告销售额")
        acos = spend / ad_sales if ad_sales else None
        roas = ad_sales / spend if spend else None

    days = None
    if inv is not None:
        iv = inv[inv["SKU"] == sku]
        if len(iv):
            current = _num(iv.iloc[0]["当前库存"])
            daily = _num(iv.iloc[0]["日均销量"])
            days = float(current) / daily if daily else None

    margin = None
    if profit is not None:
        pf = profit[profit["SKU"] == sku]
        if len(pf):
            margin = pf.iloc[0].get("毛利率", None)

    result = {"SKU": sku, "产品名称": name, "产品阶段": stage or "—"}

    result["销售"] = f"近7天 ${r_sales:,.0f}，环比 {sales_mom*100:+.1f}%" if sales_mom is not None else "销售数据不足"
    result["流量"] = f"Session 环比 {sess_mom*100:+.1f}%" if sess_mom is not None else "流量数据不足"
    result["转化"] = f"转化率 {cvr*100:.2f}%" if cvr is not None else "转化数据不足"
    result["广告"] = f"ACOS {acos*100:.1f}%，ROAS {roas:.2f}" if acos is not None else "无广告数据"
    result["库存"] = f"可售 {days:.0f} 天" if days is not None else "无库存数据"
    result["利润"] = f"毛利率 {margin*100:.1f}%" if margin is not None else "无利润数据"

    # 原因 + 判断 + 建议
    reasons, judgement, suggestions = [], [], []

    if sales_mom is not None and sales_mom <= -0.2:
        if sess_mom is not None and sess_mom <= -0.15:
            reasons.append(f"流量 Session 下降 {sess_mom*100:.1f}%，是销售下降主因")
            judgement.append("优先排查流量，而非转化或库存")
            suggestions.append("检查广告曝光、关键词排名、竞品价格变动")
        elif cvr is not None and cvr < 0.06:
            reasons.append("转化率偏低，流量质量或 Listing 可能有问题")
            judgement.append("优先排查 Listing 转化")
            suggestions.append("优化详情页、检查 Review 和价格竞争力")
    elif sales_mom is not None and sales_mom >= 0.05:
        reasons.append("销售保持增长")
        judgement.append("经营健康，继续保持")
        suggestions.append("关注库存是否跟得上增长，避免断货")

    if acos is not None and acos > 0.40:
        if stage == "新品":
            reasons.append(f"ACOS {acos*100:.1f}% 偏高，但属于新品期，广告承担获取流量作用")
            judgement.append("新品期可容忍较高 ACOS，重点看销量和转化是否提升")
            suggestions.append("持续观察销量增长，设定 ACOS 优化目标")
        else:
            reasons.append(f"ACOS {acos*100:.1f}% 偏高（成熟产品）")
            judgement.append("成熟产品 ACOS 高需排查广告效率")
            suggestions.append("检查高花费低转化关键词，结合毛利率决定预算")

    if days is not None and days <= 15:
        reasons.append(f"库存可售仅 {days:.0f} 天，存在断货风险")
        judgement.append("库存风险需同步关注")
        suggestions.append("核实补货周期，根据库存控制广告放量")

    if not reasons:
        reasons.append("未发现明显异常指标")
        judgement.append("经营正常，持续监控")
        suggestions.append("保持当前节奏，定期回顾")

    result["可能原因"] = reasons
    result["初步判断"] = judgement
    result["建议"] = suggestions
    return result
