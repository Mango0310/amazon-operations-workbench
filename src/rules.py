# -*- coding: utf-8 -*-
"""
异常规则引擎：纯规则判断，不依赖 AI。

异常类型：
  1. 销售下降   — 近7天销售额环比 ≤ -20%
  2. 库存风险   — 可售天数 ≤15（高风险）/ 16-30（预警）
  3. ACOS 超标  — 成熟产品 ACOS >40%；新品 >45% 才提示（结合产品阶段）
  4. 退款率高   — 退款金额/销售额 > 5%
  5. 转化率低   — CVR < 5%
"""
import pandas as pd

from .analytics import compute_sku_metrics
from .schema import TABLE_SALES

SALES_DROP_THRESHOLD = -0.20
ACOS_MATURE_TARGET = 0.40
ACOS_NEW_TARGET = 0.45
STOCK_HIGH = 15
STOCK_WARN = 30
REFUND_RATE_HIGH = 0.05
CVR_LOW = 0.05


def detect_anomalies(tables):
    """
    返回异常清单 DataFrame。
    列：SKU、产品名称、异常类型、严重程度、核心指标、建议
    """
    m = compute_sku_metrics(tables)
    sales = tables[TABLE_SALES]

    # 退款率（近30天，按 SKU）
    refund_rate_map = {}
    g = sales.groupby("SKU").agg(销售额=("销售额", "sum"), 退款=("退款金额", "sum"))
    g["退款率"] = g["退款"] / g["销售额"].replace(0, pd.NA)
    refund_rate_map = g["退款率"].to_dict()

    rows = []
    for _, r in m.iterrows():
        sku = r["SKU"]
        name = r.get("产品名称", sku)
        stage = r.get("产品阶段", "")

        # 1) 销售下降
        mom = r.get("销售环比")
        if pd.notna(mom) and mom <= SALES_DROP_THRESHOLD:
            rows.append({
                "SKU": sku, "产品名称": name,
                "异常类型": "销售下降", "严重程度": "🔴",
                "核心指标": f"环比 {mom*100:.1f}%",
                "建议": "排查流量、转化率、广告和竞品价格变化",
            })

        # 2) 库存风险
        days = r.get("可售天数")
        if pd.notna(days):
            if days <= STOCK_HIGH:
                rows.append({
                    "SKU": sku, "产品名称": name,
                    "异常类型": "库存风险", "严重程度": "🔴",
                    "核心指标": f"可售 {days:.0f} 天",
                    "建议": "核实补货周期，评估补货；根据库存控制广告放量",
                })
            elif days <= STOCK_WARN:
                rows.append({
                    "SKU": sku, "产品名称": name,
                    "异常类型": "库存预警", "严重程度": "🟡",
                    "核心指标": f"可售 {days:.0f} 天",
                    "建议": "提前安排补货",
                })

        # 3) ACOS 超标（结合产品阶段）
        acos = r.get("ACOS")
        if pd.notna(acos):
            target = ACOS_NEW_TARGET if stage == "新品" else ACOS_MATURE_TARGET
            if acos > target:
                sev = "🔴" if (acos > target + 0.10) else "🟡"
                note = "（新品期，关注销量增长）" if stage == "新品" else ""
                rows.append({
                    "SKU": sku, "产品名称": name,
                    "异常类型": "ACOS 超标", "严重程度": sev,
                    "核心指标": f"ACOS {acos*100:.1f}%",
                    "建议": f"检查高花费低转化关键词，结合毛利率决定预算{note}",
                })

        # 4) 退款率高
        rr = refund_rate_map.get(sku)
        if rr is not None and rr > REFUND_RATE_HIGH:
            rows.append({
                "SKU": sku, "产品名称": name,
                "异常类型": "退款率高", "严重程度": "🟡",
                "核心指标": f"退款率 {rr*100:.1f}%",
                "建议": "检查产品质量、Listing 描述与实物是否一致",
            })

        # 5) 转化率低
        cvr = r.get("CVR")
        if pd.notna(cvr) and cvr < CVR_LOW and r.get("Session", 0) > 0:
            rows.append({
                "SKU": sku, "产品名称": name,
                "异常类型": "转化率低", "严重程度": "🟡",
                "核心指标": f"CVR {cvr*100:.2f}%",
                "建议": "检查价格、Listing、Review 和竞品变化",
            })

    df = pd.DataFrame(rows, columns=["SKU", "产品名称", "异常类型", "严重程度", "核心指标", "建议"])
    if not df.empty:
        sev_order = {"🔴": 0, "🟡": 1, "🟢": 2}
        df["_s"] = df["严重程度"].map(sev_order).fillna(9)
        df = df.sort_values(["_s", "SKU"]).drop(columns="_s").reset_index(drop=True)
    return df
