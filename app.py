# -*- coding: utf-8 -*-
"""亚马逊经营工作台：目标、诊断、动作与复盘。"""
import os

import pandas as pd
import streamlit as st

from src.analytics import compute_daily_trend, compute_sku_metrics, analyze_sku
from src.ai_provider import generate_review, list_ollama_models
from src.importer import (
    ERROR, check_sku_consistency, detect_table_type,
    normalize_dates, read_file, validate_table,
)
from src.rules import detect_anomalies
from src.schema import (
    SCHEMA, TABLE_ADS, TABLE_COMPETITOR, TABLE_INVENTORY, TABLE_LISTING,
    TABLE_PRODUCT, TABLE_PROFIT, TABLE_SALES, TABLE_SEARCH_TERMS, suggest_mapping,
)

st.set_page_config(page_title="亚马逊经营工作台", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .block-container {padding-top: 1.8rem; padding-bottom: 3rem; max-width: 1500px;}
    [data-testid="stSidebar"] {background: linear-gradient(180deg, #f7f9fc 0%, #eef3f8 100%);}
    [data-testid="stMetric"] {background: #ffffff; border: 1px solid #e6ebf1; border-radius: 14px; padding: 14px 16px; box-shadow: 0 4px 14px rgba(30, 50, 80, 0.05);}
    [data-testid="stMetricLabel"] {font-weight: 600; color: #526173;}
    div[data-testid="stDataFrame"] {border: 1px solid #e6ebf1; border-radius: 12px; overflow: hidden;}
    h1 {letter-spacing: -0.02em;}
    h2, h3 {color: #1d2a3a;}
    .ai-badge {display: inline-block; padding: 4px 9px; border-radius: 999px; background: #e8f0ff; color: #2855a6; font-size: 0.78rem; font-weight: 700; margin-bottom: 6px;}
    .section-note {color: #64748b; font-size: 0.9rem; margin-top: -8px; margin-bottom: 12px;}
</style>
""", unsafe_allow_html=True)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PAGES = ["经营驾驶舱", "SKU 经营诊断", "广告与利润", "库存管理", "listing", "行动与复盘", "数据中心"]
CORE_TABLES = [TABLE_PRODUCT, TABLE_SALES, TABLE_ADS, TABLE_INVENTORY, TABLE_PROFIT]
ALL_TABLES = [TABLE_PRODUCT, TABLE_LISTING, TABLE_SALES, TABLE_INVENTORY, TABLE_ADS, TABLE_SEARCH_TERMS, TABLE_COMPETITOR, TABLE_PROFIT]

if "tables" not in st.session_state:
    st.session_state.tables = {}
# 兼容改名前已经加载到浏览器会话中的旧键名。
if "Listing表" in st.session_state.tables and TABLE_LISTING not in st.session_state.tables:
    st.session_state.tables[TABLE_LISTING] = st.session_state.tables.pop("Listing表")


def _apply_schema(df):
    table_type = detect_table_type(df.columns)
    mapping = suggest_mapping(list(df.columns))
    mapped = df.rename(columns={column: field for column, field in mapping.items() if field})
    if table_type == TABLE_LISTING and "关键词" in mapped.columns and "Search Terms" not in mapped.columns:
        mapped = mapped.rename(columns={"关键词": "Search Terms"})
    all_fields = set().union(*SCHEMA.values())
    mapped = mapped[[column for column in mapped.columns if column in all_fields]]
    mapped, _ = normalize_dates(mapped)
    return mapped, table_type


def merge_imported_table(existing, incoming, table_type):
    """将分批上传的数据合并进当前会话；同一业务主键以新文件为准。"""
    if existing is None or existing.empty:
        return incoming.copy()
    if table_type == TABLE_COMPETITOR:
        return incoming.copy()
    if table_type in (TABLE_SALES, TABLE_ADS):
        keys = ["日期", "SKU"]
    elif table_type == TABLE_SEARCH_TERMS:
        keys = ["SKU", "广告活动", "搜索词"]
    else:
        keys = ["SKU"]
    keys = [key for key in keys if key in existing.columns and key in incoming.columns]
    if not keys:
        return incoming.copy()
    combined = pd.concat([existing, incoming], ignore_index=True, sort=False)
    return combined.drop_duplicates(subset=keys, keep="last").reset_index(drop=True)


def load_example_data():
    loaded = {}
    for filename in sorted(os.listdir(DATA_DIR)):
        if filename.endswith(".csv"):
            frame = pd.read_csv(os.path.join(DATA_DIR, filename), encoding="utf-8-sig")
            mapped, table_type = _apply_schema(frame)
            if table_type:
                loaded[table_type] = mapped
    return loaded


def fmt_ratio(value, digits=1):
    return f"{value * 100:.{digits}f}%" if pd.notna(value) else "—"


def fmt_money(value):
    return f"${value:,.0f}" if pd.notna(value) else "—"


def fmt_number(value, digits=0):
    number = pd.to_numeric(value, errors="coerce")
    return f"{number:,.{digits}f}" if pd.notna(number) else "—"


def render_detail_cards(detail, columns=3):
    """用可换行卡片展示明细，避免交互表格在窄屏或 Tab 中被截断。"""
    records = detail.to_dict("records")
    for start in range(0, len(records), columns):
        card_columns = st.columns(columns)
        for column, record in zip(card_columns, records[start:start + columns]):
            with column:
                with st.container(border=True):
                    st.caption(str(record.get("指标", "")))
                    st.markdown(f"**{record.get('数值', '—')}**")
                    st.caption(str(record.get("说明", "")))


def prepare_listing_review(source):
    """把原始 Listing 字段转换成面向运营人员的检查结果。"""
    legacy_columns = {
        "标题": "Title", "五点": "Bullet Points", "主图": "Main Image",
        "关键词": "Search Terms", "品牌风险": "Brand Risk",
        "变体状态": "Variation Status", "状态": "Status",
    }
    listing = source.copy().rename(columns={old: new for old, new in legacy_columns.items() if old in source.columns and new not in source.columns})
    for column in ["Title", "Bullet Points", "Main Image", "Search Terms", "Brand Risk", "Variation Status", "Status"]:
        if column not in listing.columns:
            listing[column] = ""
    sensitive_pattern = r"(?i)(?:best|#1|100%|guaranteed|cure|miracle)"
    listing["Title Length"] = listing["Title"].fillna("").astype(str).str.len()
    listing["Title Check"] = listing["Title Length"].apply(lambda value: "过短" if value < 30 else ("过长" if value > 200 else "通过"))
    listing["Bullet Points Count"] = listing["Bullet Points"].fillna("").astype(str).apply(lambda value: len([x for x in value.split("；") if x.strip()]))
    listing["Bullet Points Check"] = listing["Bullet Points Count"].apply(lambda value: "不足" if value < 3 else "通过")
    listing["Main Image Check"] = listing["Main Image"].fillna("").astype(str).apply(lambda value: "通过" if value in ("合规", "✅") else "需处理")
    listing["Search Terms Check"] = listing["Search Terms"].fillna("").astype(str).apply(lambda value: "缺失" if not value.strip() else "通过")
    listing["Risk Claim Check"] = listing["Title"].fillna("").astype(str).str.contains(sensitive_pattern, regex=True).map({True: "发现风险词", False: "未发现"})

    def summarize(row):
        issues = []
        actions = []
        for column, label, action in [
            ("Title Check", "Title", "修改 Title 长度或表述"),
            ("Bullet Points Check", "Bullet Points", "补充至少 3 条有效 Bullet Points"),
            ("Main Image Check", "Main Image", "补充并人工核验 Main Image"),
            ("Search Terms Check", "Search Terms", "补充相关 Search Terms"),
        ]:
            if row[column] != "通过":
                issues.append(f"{label}{row[column]}")
                actions.append(action)
        if row["Risk Claim Check"] != "未发现":
            issues.append("Title 含风险表述")
            actions.append("人工核验并删除绝对化表述")
        if str(row.get("Brand Risk", "")) not in ("", "未发现", "正常"):
            issues.append("Brand Risk 需核验")
            actions.append("核验 Brand 授权或侵权风险")
        if str(row.get("Variation Status", "")) not in ("", "正常"):
            issues.append("Variation 需检查")
            actions.append("检查 Variation 关系是否合理")
        return pd.Series({
            "问题项": "；".join(issues) if issues else "未发现基础问题",
            "建议动作": "；".join(dict.fromkeys(actions)) if actions else "保持并定期复查",
            "预检结论": "高风险" if len(issues) >= 3 else ("待处理" if issues else "通过"),
        })

    listing[["问题项", "建议动作", "预检结论"]] = listing.apply(summarize, axis=1)
    return listing


def sales_ready():
    return TABLE_SALES in st.session_state.tables and not st.session_state.tables[TABLE_SALES].empty


def sku_metrics():
    return compute_sku_metrics(st.session_state.tables) if sales_ready() else pd.DataFrame()


def anomaly_data():
    return detect_anomalies(st.session_state.tables) if sales_ready() else pd.DataFrame()


def require_sales(message="请先在「数据中心」导入销售表，或加载示例数据。"):
    if sales_ready():
        return True
    st.info(message)
    return False


@st.cache_data(ttl=10, show_spinner=False)
def cached_ollama_models(base_url):
    return list_ollama_models(base_url)


ai_provider = "ollama"
ai_base_url = ""
ai_model = ""
ai_api_key = ""


with st.sidebar:
    st.markdown("## 亚马逊经营工作台")
    st.caption("目标 → 诊断 → 动作 → 复盘")
    st.divider()
    page = st.radio("导航", PAGES, label_visibility="collapsed")
    st.divider()
    loaded_count = len(st.session_state.tables)
    st.markdown(f"**数据状态：{loaded_count}/8 张表**")
    missing_core = [name for name in CORE_TABLES if name not in st.session_state.tables]
    st.caption(f"核心表待补充：{'、'.join(missing_core)}" if missing_core else "核心经营数据已具备")
    if st.button("加载示例数据", type="primary", width="stretch"):
        st.session_state.tables = load_example_data()
        st.session_state.pop("action_board", None)
        st.rerun()
    if loaded_count and st.button("清空当前数据", width="stretch"):
        st.session_state.tables = {}
        st.session_state.pop("action_board", None)
        st.rerun()
    st.divider()

    with st.expander("AI 连接设置", expanded=False):
        provider_label = st.radio("AI 来源", ["本地 Ollama", "自定义云端接口"], key="ai_provider")
        ai_provider = "ollama" if provider_label == "本地 Ollama" else "compatible"
        if ai_provider == "ollama":
            ai_base_url = st.text_input("Ollama 地址", value="http://localhost:11434", key="ollama_url")
            st.caption("基础地址；系统自动调用 /api/tags 和 /api/chat。")
            models, model_error = cached_ollama_models(ai_base_url)
            if models:
                ai_model = st.selectbox("本地模型", models, key="ollama_model")
                st.success("本地 AI 已连接")
            else:
                ai_model = st.text_input("模型名称", placeholder="例如：qwen3:4b", key="ollama_model_manual")
                st.warning("未检测到 Ollama 模型")
                if model_error:
                    st.caption(model_error)
        else:
            cloud_service = st.selectbox("云端服务", ["DeepSeek", "阿里云百炼 / 通义千问", "其他兼容服务"], key="cloud_ai_service")
            if cloud_service == "DeepSeek":
                ai_base_url = st.text_input("接口地址", value="https://api.deepseek.com/chat/completions", key="deepseek_ai_url")
                ai_model = st.text_input("模型名称", value="deepseek-v4-flash", key="deepseek_ai_model")
            elif cloud_service == "阿里云百炼 / 通义千问":
                st.caption("将 {WorkspaceId} 替换为百炼业务空间 ID。")
                ai_base_url = st.text_input("接口地址", value="https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions", key="qwen_ai_url")
                ai_model = st.text_input("模型名称", placeholder="填写可用模型 ID", key="qwen_ai_model")
            else:
                ai_base_url = st.text_input("接口地址", placeholder="https://服务商地址/v1/chat/completions", key="custom_ai_url")
                ai_model = st.text_input("模型名称", placeholder="填写模型 ID", key="custom_ai_model")
            ai_api_key = st.text_input("API Key", type="password", key="custom_ai_key", help="仅保存在当前会话，不写入文件。")
            if ai_base_url and ai_model and ai_api_key:
                st.success("云端 AI 参数已填写")

    st.divider()


if page == "经营驾驶舱":
    st.title("经营驾驶舱")
    st.caption("先看目标是否达成，再决定今天优先处理什么。默认经营窗口为最近 7 天。")

    if require_sales():
        tables = st.session_state.tables
        trend = compute_daily_trend(tables)
        recent = trend.tail(7)
        prior = trend.iloc[-14:-7] if len(trend) >= 14 else pd.DataFrame()
        actual_sales = pd.to_numeric(recent["销售额"], errors="coerce").sum()
        prior_series = prior["销售额"] if "销售额" in prior.columns else pd.Series(dtype=float)
        prior_sales = pd.to_numeric(prior_series, errors="coerce").sum()
        sales_change = (actual_sales - prior_sales) / prior_sales if prior_sales else None

        metrics = sku_metrics()
        ad_spend = pd.to_numeric(metrics.get("广告花费", pd.Series(dtype=float)), errors="coerce").sum()
        ad_sales = pd.to_numeric(metrics.get("广告销售额", pd.Series(dtype=float)), errors="coerce").sum()
        acos = ad_spend / ad_sales if ad_sales else None

        operating_margin = None
        if TABLE_PROFIT in tables:
            profit_table = tables[TABLE_PROFIT]
            total_profit = pd.to_numeric(profit_table["利润"], errors="coerce").sum()
            profit_sales = pd.to_numeric(profit_table["销售额"], errors="coerce").sum()
            operating_margin = total_profit / profit_sales if profit_sales else None
        estimated_profit = actual_sales * operating_margin if operating_margin is not None else None

        with st.expander("设置本周期经营目标"):
            g1, g2, g3, g4 = st.columns(4)
            sales_target = g1.number_input("销售目标（$）", min_value=0.0, value=float(round(actual_sales * 1.10)), step=100.0)
            profit_default = max(0.0, float(round((estimated_profit or 0) * 1.10)))
            profit_target = g2.number_input("经营利润目标（$）", min_value=0.0, value=profit_default, step=100.0)
            margin_target = g3.number_input("经营利润率目标（小数）", min_value=0.0, max_value=1.0, value=0.20, step=0.01, format="%.2f")
            acos_limit = g4.number_input("ACOS 控制线（小数）", min_value=0.0, max_value=1.0, value=0.30, step=0.01, format="%.2f")
            g3.caption(f"当前设定 {margin_target:.0%}")
            g4.caption(f"当前设定 {acos_limit:.0%}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("销售额（近 7 天）", fmt_money(actual_sales), fmt_ratio(sales_change) if sales_change is not None else None)
        c2.metric("销售目标达成率", fmt_ratio(actual_sales / sales_target) if sales_target else "未设置")
        c3.metric("经营利润估算（近 7 天）", fmt_money(estimated_profit), help="近 7 天销售额 × 利润表导入期的经营利润率，仅用于快速判断。")
        c4.metric("ACOS（近 7 天）", fmt_ratio(acos), delta=f"控制线 {acos_limit:.0%}" if acos is not None else None, delta_color="off")

        status_items = [
            {"经营维度": "销售", "当前值": fmt_money(actual_sales), "目标/控制线": fmt_money(sales_target), "状态": "达成" if sales_target and actual_sales >= sales_target else "待提升"},
            {"经营维度": "利润", "当前值": fmt_money(estimated_profit), "目标/控制线": fmt_money(profit_target), "状态": "达成" if estimated_profit is not None and profit_target and estimated_profit >= profit_target else "待提升"},
            {"经营维度": "经营利润率", "当前值": fmt_ratio(operating_margin), "目标/控制线": fmt_ratio(margin_target), "状态": "达成" if operating_margin is not None and operating_margin >= margin_target else "待提升"},
            {"经营维度": "广告效率", "当前值": fmt_ratio(acos), "目标/控制线": fmt_ratio(acos_limit), "状态": "健康" if acos is not None and acos <= acos_limit else "需优化"},
        ]

        st.divider()
        left, right = st.columns([1.35, 1])
        with left:
            st.subheader("销售与广告趋势")
            chart = trend.set_index("日期")
            st.line_chart(chart[[column for column in ["销售额", "广告花费"] if column in chart.columns]])
        with right:
            st.subheader("目标状态")
            st.dataframe(pd.DataFrame(status_items), width="stretch", hide_index=True)

        st.divider()
        left, right = st.columns([1.2, 1])
        with left:
            st.subheader("SKU 销售贡献 Top 8")
            top = metrics.sort_values("销售额", ascending=False).head(8).copy()
            top["销售额"] = top["销售额"].apply(fmt_money)
            top["销售环比"] = top["销售环比"].apply(fmt_ratio)
            st.dataframe(top[["SKU", "产品名称", "销售额", "销售环比"]], width="stretch", hide_index=True)
        with right:
            st.subheader("今日优先事项")
            anomalies = anomaly_data()
            if anomalies.empty:
                st.success("暂无规则异常，继续跟踪目标达成。")
            else:
                for _, row in anomalies.head(5).iterrows():
                    priority = "P0" if row["严重程度"] == "🔴" else "P1"
                    st.markdown(f"**{priority} · {row['SKU']} · {row['异常类型']}**  \n{row['建议']}")


elif page == "SKU 经营诊断":
    st.title("SKU 经营诊断")
    st.caption("围绕一个 SKU 集中判断销售、流量、转化、广告、库存和利润。")
    if require_sales():
        sales = st.session_state.tables[TABLE_SALES]
        selected = st.selectbox("选择 SKU", sorted(sales["SKU"].dropna().unique().tolist()))
        diagnosis = analyze_sku(st.session_state.tables, selected)
        st.subheader(f"{diagnosis['产品名称']} · {selected} · {diagnosis['产品阶段']}")
        items = [
            ("Sales / 销售", "销售"),
            ("Sessions / 流量", "流量"),
            ("CVR / 转化", "转化"),
            ("Ads / 广告", "广告"),
            ("Inventory / 库存", "库存"),
            ("Profit / 利润", "利润"),
        ]
        for start in range(0, len(items), 3):
            cards = st.columns(3)
            for column, (label, key) in zip(cards, items[start:start + 3]):
                with column:
                    with st.container(border=True):
                        st.caption(label)
                        st.markdown(f"**{diagnosis[key]}**")

        with st.expander("Operating Metrics / 完整经营指标", expanded=True):
            metric_table = sku_metrics()
            metric_row = metric_table[metric_table["SKU"] == selected].iloc[0]
            latest_date = pd.to_datetime(sales["日期"], errors="coerce").max()
            recent_start = latest_date - pd.Timedelta(days=6)
            selected_sales = sales[(sales["SKU"] == selected) & (pd.to_datetime(sales["日期"], errors="coerce").between(recent_start, latest_date))]
            st.caption(f"经营指标口径：{recent_start:%Y-%m-%d} 至 {latest_date:%Y-%m-%d}；利润表、库存和 Listing 使用各自最新导入记录。")

            profit_record = {}
            if TABLE_PROFIT in st.session_state.tables:
                matched = st.session_state.tables[TABLE_PROFIT]
                matched = matched[matched["SKU"] == selected]
                if not matched.empty:
                    profit_record = matched.iloc[0].to_dict()
            inventory_record = {}
            if TABLE_INVENTORY in st.session_state.tables:
                matched = st.session_state.tables[TABLE_INVENTORY]
                matched = matched[matched["SKU"] == selected]
                if not matched.empty:
                    inventory_record = matched.iloc[0].to_dict()
            listing_record = {}
            if TABLE_LISTING in st.session_state.tables:
                matched = st.session_state.tables[TABLE_LISTING]
                matched = matched[matched["SKU"] == selected]
                if not matched.empty:
                    listing_record = prepare_listing_review(matched).iloc[0].to_dict()
            ad_orders = None
            if TABLE_SEARCH_TERMS in st.session_state.tables:
                matched_terms = st.session_state.tables[TABLE_SEARCH_TERMS]
                matched_terms = matched_terms[matched_terms["SKU"] == selected]
                if "广告订单" in matched_terms.columns:
                    ad_orders = pd.to_numeric(matched_terms["广告订单"], errors="coerce").sum()

            sales_detail = pd.DataFrame([
                {"指标": "Sales / 销售额（近 7 天）", "数值": fmt_money(metric_row.get("销售额")), "说明": "当前诊断周期销售额"},
                {"指标": "Sales / 销售额（前 7 天）", "数值": fmt_money(metric_row.get("前7天销售额")), "说明": "用于计算环比"},
                {"指标": "Sales WoW / 销售环比", "数值": fmt_ratio(metric_row.get("销售环比")), "说明": "近 7 天相对前 7 天"},
                {"指标": "Orders / 订单量", "数值": fmt_number(metric_row.get("订单量")), "说明": "近 7 天订单"},
                {"指标": "Sessions / 访问会话数", "数值": fmt_number(metric_row.get("Session")), "说明": "近 7 天访问会话"},
                {"指标": "CVR / 转化率", "数值": fmt_ratio(metric_row.get("CVR"), 2), "说明": "订单量 ÷ Sessions"},
                {"指标": "Refund / 退款金额", "数值": fmt_money(pd.to_numeric(selected_sales.get("退款金额", pd.Series(dtype=float)), errors="coerce").sum()), "说明": "近 7 天退款"},
            ])
            ad_detail = pd.DataFrame([
                {"指标": "Ad Spend / 广告花费", "数值": fmt_money(metric_row.get("广告花费")), "说明": "近 7 天"},
                {"指标": "Ad Sales / 广告销售额", "数值": fmt_money(metric_row.get("广告销售额")), "说明": "近 7 天广告归因销售"},
                {"指标": "Ad Orders / 广告订单", "数值": fmt_number(ad_orders), "说明": "来自当前搜索词表"},
                {"指标": "Impressions / 曝光", "数值": fmt_number(metric_row.get("曝光")), "说明": "广告展示次数"},
                {"指标": "Clicks / 点击", "数值": fmt_number(metric_row.get("点击")), "说明": "广告点击次数"},
                {"指标": "CTR / 点击率", "数值": fmt_ratio(metric_row.get("CTR"), 2), "说明": "点击 ÷ 曝光"},
                {"指标": "CPC / 单次点击成本", "数值": f"${fmt_number(metric_row.get('CPC'), 2)}", "说明": "花费 ÷ 点击"},
                {"指标": "ACOS / 广告销售成本比", "数值": fmt_ratio(metric_row.get("ACOS")), "说明": "广告花费 ÷ 广告销售额"},
                {"指标": "TACOS / 广告销售总成本比", "数值": fmt_ratio(metric_row.get("TACOS")), "说明": "广告花费 ÷ 全部销售额"},
                {"指标": "ROAS / 广告投入产出比", "数值": fmt_number(metric_row.get("ROAS"), 2), "说明": "广告销售额 ÷ 广告花费"},
            ])
            available_days = metric_row.get("可售天数")
            snapshot = pd.to_datetime(inventory_record.get("数据日期"), errors="coerce")
            stockout_date = snapshot + pd.to_timedelta(available_days, unit="D") if pd.notna(snapshot) and pd.notna(available_days) else pd.NaT
            inventory_detail = pd.DataFrame([
                {"指标": "Snapshot Date / 库存日期", "数值": snapshot.strftime("%Y-%m-%d") if pd.notna(snapshot) else "—", "说明": "库存快照日期"},
                {"指标": "Available / 当前库存", "数值": fmt_number(metric_row.get("当前库存")), "说明": "当前可售库存"},
                {"指标": "Inbound / 在途库存", "数值": fmt_number(metric_row.get("在途库存")), "说明": "尚未到仓"},
                {"指标": "Daily Sales / 日均销量", "数值": fmt_number(metric_row.get("日均销量"), 1), "说明": "当前库存表口径"},
                {"指标": "Safety Stock / 安全库存", "数值": fmt_number(metric_row.get("安全库存")), "说明": "风险缓冲"},
                {"指标": "Days of Supply / 可售天数", "数值": f"{fmt_number(available_days)} 天", "说明": "当前库存 ÷ 日均销量"},
                {"指标": "Stockout Date / 预计断货日", "数值": stockout_date.strftime("%Y-%m-%d") if pd.notna(stockout_date) else "—", "说明": "按当前日均销量估算"},
                {"指标": "Lead Time / 采购周期", "数值": f"{fmt_number(inventory_record.get('采购周期天'))} 天", "说明": "从采购到到仓"},
                {"指标": "ETA / 预计到仓日", "数值": pd.to_datetime(inventory_record.get("预计到仓日期"), errors="coerce").strftime("%Y-%m-%d") if pd.notna(pd.to_datetime(inventory_record.get("预计到仓日期"), errors="coerce")) else "—", "说明": "当前计划"},
            ])
            profit_detail = pd.DataFrame([
                {"指标": "Price / 售价", "数值": fmt_money(metric_row.get("售价")), "说明": "产品表当前售价"},
                {"指标": "COGS / 产品成本", "数值": fmt_money(profit_record.get("产品成本", metric_row.get("成本"))), "说明": "利润表导入期"},
                {"指标": "Ad Spend / 广告花费", "数值": fmt_money(profit_record.get("广告花费")), "说明": "利润表导入期"},
                {"指标": "Amazon Fees / 平台及物流费", "数值": fmt_money(profit_record.get("平台及物流费")), "说明": "利润表导入期"},
                {"指标": "Refund / 退款金额", "数值": fmt_money(profit_record.get("退款金额")), "说明": "利润表导入期"},
                {"指标": "Profit / 经营利润", "数值": fmt_money(profit_record.get("利润")), "说明": "扣除项目中列示成本费用"},
                {"指标": "Profit Margin / 经营利润率", "数值": fmt_ratio(metric_row.get("毛利率")), "说明": "经营利润 ÷ 销售额"},
                {"指标": "Lifecycle / 产品阶段", "数值": metric_row.get("产品阶段", "—"), "说明": "新品/成熟品等"},
            ])
            listing_detail = pd.DataFrame([
                {"指标": "Listing Status / 状态", "数值": listing_record.get("Status", "—"), "说明": "导入数据中的维护状态"},
                {"指标": "Pre-check / 预检结论", "数值": listing_record.get("预检结论", "—"), "说明": "项目基础检查"},
                {"指标": "Issues / 问题项", "数值": listing_record.get("问题项", "—"), "说明": "需要人工核验"},
                {"指标": "Actions / 建议动作", "数值": listing_record.get("建议动作", "—"), "说明": "不代表平台最终审核"},
            ])
            detail_tabs = st.tabs([
                "Sales & Traffic / 销售与流量",
                "Ads / 广告",
                "Inventory / 库存",
                "Profit / 利润",
                "Listing",
            ])
            detail_groups = [sales_detail, ad_detail, inventory_detail, profit_detail, listing_detail]
            detail_columns = [3, 3, 3, 3, 2]
            for tab, detail, columns in zip(detail_tabs, detail_groups, detail_columns):
                with tab:
                    render_detail_cards(detail, columns=columns)
        st.divider()
        a, b, c = st.columns(3)
        for container, heading, key in [(a, "发现", "可能原因"), (b, "判断", "初步判断"), (c, "下一步动作", "建议")]:
            with container:
                st.subheader(heading)
                for item in diagnosis[key]:
                    st.markdown(f"- {item}")
        anomalies = anomaly_data()
        sku_anomalies = anomalies[anomalies["SKU"] == selected].copy() if not anomalies.empty else pd.DataFrame()
        st.subheader("当前经营风险")
        if sku_anomalies.empty:
            st.success("当前未发现需要优先处理的经营风险。")
        else:
            risk_view = sku_anomalies[["严重程度", "异常类型", "核心指标", "建议"]].rename(columns={
                "严重程度": "风险等级",
                "异常类型": "风险事项",
                "建议": "建议动作",
            })
            st.dataframe(risk_view, width="stretch", hide_index=True)

        competitor_context = []
        with st.expander("竞品对比与数据来源", expanded=True):
            if TABLE_COMPETITOR not in st.session_state.tables:
                st.info("尚未导入竞品表。")
            else:
                competitors = st.session_state.tables[TABLE_COMPETITOR]
                competitors = competitors[competitors["SKU"] == selected].copy()
                if competitors.empty:
                    st.info("该 SKU 暂无竞品记录。")
                else:
                    own_price = None
                    if TABLE_PRODUCT in st.session_state.tables:
                        product_row = st.session_state.tables[TABLE_PRODUCT]
                        product_row = product_row[product_row["SKU"] == selected]
                        if not product_row.empty:
                            own_price = pd.to_numeric(product_row.iloc[0].get("售价"), errors="coerce")
                    if own_price is not None and pd.notna(own_price):
                        competitors.insert(1, "自己售价", own_price)
                        competitors["与竞品价差"] = own_price - pd.to_numeric(competitors["竞品价格"], errors="coerce")
                    competitor_context = competitors.to_dict(orient="records")
                    source_name = competitors.iloc[0].get("数据来源", "未标注来源")
                    collected_at = pd.to_datetime(competitors.iloc[0].get("采集日期"), errors="coerce")
                    st.info(f"当前数据来源：{source_name}；采集日期：{collected_at:%Y-%m-%d}" if pd.notna(collected_at) else f"当前数据来源：{source_name}；采集日期未标注")
                    competitor_columns = ["竞品ASIN", "竞品名", "自己售价", "竞品价格", "与竞品价差", "Rating", "Reviews", "核心卖点", "数据来源", "采集日期"]
                    st.dataframe(competitors[[column for column in competitor_columns if column in competitors.columns]], width="stretch", hide_index=True)
                    st.caption("示例数据由 generate_data.py 模拟生成，并非真实抓取。真实使用时可由人工调研、公司已有竞品台账或合规数据服务导入；竞品信息只用于提出验证方向。")

        with st.container(border=True):
            st.markdown('<span class="ai-badge">AI 经营复盘助手</span>', unsafe_allow_html=True)
            st.markdown("#### 生成可验证的复盘草稿")
            st.markdown('<div class="section-note">AI 只读取当前 SKU 的汇总指标、风险和竞品摘要；输出必须由运营人员审核。</div>', unsafe_allow_html=True)

            context = {
                "SKU": selected,
                "产品名称": diagnosis["产品名称"],
                "产品阶段": diagnosis["产品阶段"],
                "销售": diagnosis["销售"],
                "流量": diagnosis["流量"],
                "转化": diagnosis["转化"],
                "广告": diagnosis["广告"],
                "库存": diagnosis["库存"],
                "利润": diagnosis["利润"],
                "系统发现": diagnosis["可能原因"],
                "当前风险": sku_anomalies[["异常类型", "核心指标"]].to_dict(orient="records") if not sku_anomalies.empty else [],
                "竞品摘要": competitor_context,
            }
            ready = bool(ai_model and ai_base_url and (ai_provider == "ollama" or ai_api_key))
            connection_name = "本地 Ollama" if ai_provider == "ollama" else "自定义云端接口"
            st.caption(f"当前 AI：{connection_name} · {ai_model or '尚未配置模型'}（连接参数在左侧设置）")
            if st.button("生成 AI 复盘草稿", type="primary", disabled=not ready, key="generate_ai_review"):
                try:
                    with st.spinner("正在基于当前经营数据生成复盘草稿…"):
                        review = generate_review(ai_provider, context, model=ai_model, base_url=ai_base_url, api_key=ai_api_key)
                    st.session_state.setdefault("ai_reviews", {})[selected] = review
                except RuntimeError as exc:
                    st.error(str(exc))

            review = st.session_state.get("ai_reviews", {}).get(selected)
            if review:
                st.markdown("##### AI 摘要")
                st.write(review.get("summary", ""))
                r1, r2 = st.columns(2)
                with r1:
                    st.markdown("**待验证假设**")
                    for item in review.get("hypotheses", []):
                        st.markdown(f"- {item}")
                with r2:
                    st.markdown("**风险提醒**")
                    for item in review.get("risks", []):
                        st.markdown(f"- {item}")
                actions = review.get("actions", [])
                if actions:
                    action_view = pd.DataFrame(actions).rename(columns={
                        "action": "优先动作",
                        "expected_impact": "预期影响",
                        "verify_metric": "验证指标",
                        "review_time": "复盘时间",
                    })
                    st.markdown("**行动建议**")
                    st.dataframe(action_view, width="stretch", hide_index=True)
                st.caption("AI 生成内容仅作为复盘初稿，执行前必须核验原始数据、利润底线、库存和平台合规要求。")


elif page == "广告与利润":
    st.title("广告与利润")
    st.caption("广告指标采用最近 7 天；利润指标采用利润表的导入周期，两个口径分开展示。")
    if require_sales():
        metrics = sku_metrics()
        if TABLE_ADS not in st.session_state.tables:
            st.info("尚未导入广告表，暂时只能查看销售和利润数据。")
        else:
            spend = pd.to_numeric(metrics["广告花费"], errors="coerce").sum()
            ad_sales = pd.to_numeric(metrics["广告销售额"], errors="coerce").sum()
            total_sales = pd.to_numeric(metrics["销售额"], errors="coerce").sum()
            acos = spend / ad_sales if ad_sales else None
            tacos = spend / total_sales if total_sales else None
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("广告花费（近 7 天）", fmt_money(spend))
            c2.metric("广告销售额（近 7 天）", fmt_money(ad_sales))
            c3.metric("ACOS（近 7 天）", fmt_ratio(acos))
            c4.metric("TACOS（近 7 天）", fmt_ratio(tacos))
            st.subheader("各 SKU 广告效率")
            columns = ["SKU", "产品名称", "产品阶段", "广告花费", "广告销售额", "ACOS", "TACOS", "ROAS", "CTR", "CPC", "毛利率"]
            raw = metrics[[column for column in columns if column in metrics.columns]].copy()
            if "ACOS" in raw.columns:
                raw = raw.sort_values("ACOS", ascending=False, na_position="last")
            display = raw.copy()
            for column in ["ACOS", "TACOS", "CTR", "毛利率"]:
                if column in display.columns:
                    display[column] = display[column].apply(fmt_ratio)
            for column in ["广告花费", "广告销售额"]:
                if column in display.columns:
                    display[column] = display[column].apply(fmt_money)
            if "ROAS" in display.columns:
                display["ROAS"] = display["ROAS"].apply(lambda value: f"{value:.2f}" if pd.notna(value) else "—")
            if "CPC" in display.columns:
                display["CPC"] = display["CPC"].apply(lambda value: f"${value:.2f}" if pd.notna(value) else "—")
            st.dataframe(display, width="stretch", hide_index=True)

            st.subheader("搜索词诊断")
            st.caption("从 SKU 汇总继续下钻，识别浪费词、低相关词和可扩量词。")
            if TABLE_SEARCH_TERMS not in st.session_state.tables:
                st.info("尚未导入搜索词表。数据中心加载示例数据后可查看诊断。")
            else:
                terms = st.session_state.tables[TABLE_SEARCH_TERMS].copy()
                for column in ["曝光", "点击", "广告花费", "广告订单", "广告销售额"]:
                    terms[column] = pd.to_numeric(terms[column], errors="coerce").fillna(0)
                terms["CTR"] = terms["点击"] / terms["曝光"].replace(0, pd.NA)
                terms["CVR"] = terms["广告订单"] / terms["点击"].replace(0, pd.NA)
                terms["CPC"] = terms["广告花费"] / terms["点击"].replace(0, pd.NA)
                terms["ACOS"] = terms["广告花费"] / terms["广告销售额"].replace(0, pd.NA)

                def term_action(row):
                    if row["广告花费"] >= 15 and row["广告订单"] == 0:
                        return "P0 · 否定或暂停：高花费无订单"
                    if pd.notna(row["ACOS"]) and row["ACOS"] > 0.45:
                        return "P1 · 降低竞价并核查搜索意图"
                    if row["广告订单"] >= 3 and pd.notna(row["ACOS"]) and row["ACOS"] <= 0.25:
                        return "P1 · 保留并测试精准扩量"
                    if pd.notna(row["CTR"]) and row["CTR"] < 0.004:
                        return "P2 · 核查关键词相关性和主图"
                    return "观察 · 保持并积累数据"

                terms["建议动作"] = terms.apply(term_action, axis=1)
                action_filter = st.selectbox("动作筛选", ["全部", "P0", "P1", "P2", "观察"], key="term_action_filter")
                if action_filter != "全部":
                    terms = terms[terms["建议动作"].str.startswith(action_filter)]
                terms = terms.sort_values(["广告订单", "广告花费"], ascending=[True, False])
                term_view = terms[["SKU", "广告活动", "匹配方式", "关键词", "搜索词", "曝光", "点击", "CTR", "CPC", "广告订单", "广告销售额", "ACOS", "建议动作"]].copy()
                for column in ["CTR", "ACOS"]:
                    term_view[column] = term_view[column].apply(fmt_ratio)
                term_view["CPC"] = term_view["CPC"].apply(lambda value: f"${value:.2f}" if pd.notna(value) else "—")
                term_view["广告销售额"] = term_view["广告销售额"].apply(fmt_money)
                st.dataframe(term_view, width="stretch", hide_index=True)

        st.divider()
        st.subheader("经营利润（利润表导入期）")
        if TABLE_PROFIT not in st.session_state.tables:
            st.info("尚未导入利润表。利润分析需要销售额、产品成本、广告费、平台物流费、退款和利润字段。")
        else:
            profit = st.session_state.tables[TABLE_PROFIT].copy()
            total_profit = pd.to_numeric(profit["利润"], errors="coerce").sum()
            profit_sales = pd.to_numeric(profit["销售额"], errors="coerce").sum()
            margin = total_profit / profit_sales if profit_sales else None
            p1, p2 = st.columns(2)
            p1.metric("经营利润", fmt_money(total_profit))
            p2.metric("经营利润率", fmt_ratio(margin), help="已扣除项目数据中的产品成本、广告、平台物流费和退款。")
            if TABLE_PRODUCT in st.session_state.tables:
                profit = profit.merge(st.session_state.tables[TABLE_PRODUCT][["SKU", "产品名称"]], on="SKU", how="left")
            profit = profit.sort_values("利润", ascending=False)
            show_columns = ["SKU", "产品名称", "销售额", "产品成本", "广告花费", "平台及物流费", "退款金额", "利润", "毛利率"]
            display = profit[[column for column in show_columns if column in profit.columns]].copy()
            for column in ["销售额", "产品成本", "广告花费", "平台及物流费", "退款金额", "利润"]:
                if column in display.columns:
                    display[column] = display[column].apply(fmt_money)
            if "毛利率" in display.columns:
                display = display.rename(columns={"毛利率": "经营利润率"})
                display["经营利润率"] = display["经营利润率"].apply(fmt_ratio)
            st.dataframe(display, width="stretch", hide_index=True)


elif page == "库存管理":
    st.title("库存管理")
    st.caption("先判断什么时候可能断货，再结合采购周期和预计到仓日安排补货。")
    if TABLE_INVENTORY not in st.session_state.tables:
        st.info("尚未导入库存表。")
    else:
        inventory = st.session_state.tables[TABLE_INVENTORY].copy()
        current_stock = pd.to_numeric(inventory["当前库存"], errors="coerce")
        inbound_source = inventory["在途库存"] if "在途库存" in inventory.columns else pd.Series(0, index=inventory.index)
        inbound_stock = pd.to_numeric(inbound_source, errors="coerce").fillna(0)
        daily_sales = pd.to_numeric(inventory["日均销量"], errors="coerce")
        lead_source = inventory["采购周期天"] if "采购周期天" in inventory.columns else pd.Series(30, index=inventory.index)
        lead_days = pd.to_numeric(lead_source, errors="coerce").fillna(30)
        snapshot_source = inventory["数据日期"] if "数据日期" in inventory.columns else pd.Series(pd.Timestamp.today().strftime("%Y-%m-%d"), index=inventory.index)
        snapshot = pd.to_datetime(snapshot_source, errors="coerce").fillna(pd.Timestamp.today().normalize())
        inventory["可售天数"] = current_stock / daily_sales.replace(0, pd.NA)
        inventory["预计断货日期"] = (snapshot + pd.to_timedelta(inventory["可售天数"].fillna(0), unit="D")).dt.strftime("%Y-%m-%d")
        inventory["建议补货量"] = (daily_sales * (lead_days + 15) - current_stock - inbound_stock).clip(lower=0).round()
        inventory["风险等级"] = inventory["可售天数"].apply(lambda value: "高风险" if pd.notna(value) and value <= 15 else ("预警" if pd.notna(value) and value <= 30 else "正常"))
        if "预计到仓日期" in inventory.columns:
            eta = pd.to_datetime(inventory["预计到仓日期"], errors="coerce")
            stockout = pd.to_datetime(inventory["预计断货日期"], errors="coerce")
            inventory["到仓判断"] = ["可能断货" if pd.notna(e) and pd.notna(s) and e > s else ("无在途" if pd.isna(e) else "可衔接") for e, s in zip(eta, stockout)]
        if TABLE_PRODUCT in st.session_state.tables:
            inventory = inventory.merge(st.session_state.tables[TABLE_PRODUCT][["SKU", "产品名称"]], on="SKU", how="left")
        inventory["_rank"] = inventory["风险等级"].map({"高风险": 0, "预警": 1, "正常": 2})
        inventory = inventory.sort_values(["_rank", "可售天数"]).drop(columns="_rank")
        i1, i2, i3 = st.columns(3)
        i1.metric("高风险 SKU", int((inventory["风险等级"] == "高风险").sum()))
        i2.metric("预警 SKU", int((inventory["风险等级"] == "预警").sum()))
        i3.metric("到仓可能偏晚", int((inventory.get("到仓判断", pd.Series(dtype=str)) == "可能断货").sum()))
        inventory_columns = ["风险等级", "SKU", "产品名称", "当前库存", "在途库存", "日均销量", "可售天数", "预计断货日期", "采购周期天", "预计到仓日期", "到仓判断", "建议补货量"]
        st.dataframe(inventory[[column for column in inventory_columns if column in inventory.columns]], width="stretch", hide_index=True)
        st.caption("建议补货量按“采购周期 + 15 天安全缓冲”估算，真实下单还需考虑季节性、起订量、物流和资金安排。")


elif page == "listing":
    st.title("Listing")
    st.caption("先看哪些 SKU 有问题，再打开单个 SKU，逐项理解问题和处理方法。")
    if TABLE_LISTING not in st.session_state.tables:
        st.info("尚未导入 Listing。")
    else:
        listing = prepare_listing_review(st.session_state.tables[TABLE_LISTING])
        if TABLE_PRODUCT in st.session_state.tables:
            listing = listing.merge(st.session_state.tables[TABLE_PRODUCT][["SKU", "产品名称"]], on="SKU", how="left")
        high_risk = int((listing["预检结论"] == "高风险").sum())
        pending = int((listing["预检结论"] == "待处理").sum())
        passed = int((listing["预检结论"] == "通过").sum())
        l1, l2, l3, l4 = st.columns(4)
        l1.metric("Listing 总数", len(listing))
        l2.metric("高风险", high_risk)
        l3.metric("待处理", pending)
        l4.metric("通过", passed)

        st.subheader("问题总览")
        status_filter = st.selectbox("状态筛选", ["全部", "高风险", "待处理", "通过"], key="listing_status_filter")
        overview = listing if status_filter == "全部" else listing[listing["预检结论"] == status_filter]
        overview_columns = ["预检结论", "SKU", "产品名称", "问题项", "建议动作"]
        st.dataframe(overview[overview_columns].sort_values(["预检结论", "SKU"]), width="stretch", hide_index=True)

        st.divider()
        st.subheader("单个 SKU 逐项检查")
        selected_listing = st.selectbox("选择 SKU", sorted(listing["SKU"].dropna().unique().tolist()), key="listing_sku")
        record = listing[listing["SKU"] == selected_listing].iloc[0]
        st.markdown(f"**{record.get('产品名称', '')} · {selected_listing} · {record['预检结论']}**")
        check_rows = [
            {"检查项目": "Title", "当前情况": f"{record['Title Length']} 个字符", "检查结果": record["Title Check"], "怎么处理": "保持约 30—200 个字符，并人工核验 Search Terms 和表述"},
            {"检查项目": "Bullet Points", "当前情况": f"{record['Bullet Points Count']} 条", "检查结果": record["Bullet Points Check"], "怎么处理": "至少补充 3 条清晰卖点，避免堆砌"},
            {"检查项目": "Main Image", "当前情况": record["Main Image"], "检查结果": record["Main Image Check"], "怎么处理": "检查是否缺失，并按平台规则人工核验"},
            {"检查项目": "Search Terms", "当前情况": "已填写" if str(record["Search Terms"]).strip() else "未填写", "检查结果": record["Search Terms Check"], "怎么处理": "补充与产品相关的 Search Terms"},
            {"检查项目": "Risk Claims", "当前情况": record["Risk Claim Check"], "检查结果": "通过" if record["Risk Claim Check"] == "未发现" else "需核验", "怎么处理": "删除或核验 best、#1、100% 等绝对化表述"},
            {"检查项目": "Brand Risk", "当前情况": record["Brand Risk"] or "未标注", "检查结果": "通过" if record["Brand Risk"] in ("未发现", "正常", "") else "需核验", "怎么处理": "检查 Brand 授权及潜在侵权风险"},
            {"检查项目": "Variation Status", "当前情况": record["Variation Status"] or "未标注", "检查结果": "通过" if record["Variation Status"] in ("正常", "") else "需核验", "怎么处理": "检查 Variation 关系是否真实、合理"},
        ]
        st.dataframe(pd.DataFrame(check_rows), width="stretch", hide_index=True)
        raw_tab, bullet_tab, keyword_tab = st.tabs(["Title 原文", "Bullet Points 原文", "Search Terms 原文"])
        with raw_tab:
            st.text_area("Title", value=str(record["Title"]), height=100, disabled=True, label_visibility="collapsed")
        with bullet_tab:
            bullets = [item.strip() for item in str(record["Bullet Points"]).split("；") if item.strip()]
            for index, item in enumerate(bullets, 1):
                st.markdown(f"{index}. {item}")
        with keyword_tab:
            st.code(str(record["Search Terms"]) if str(record["Search Terms"]).strip() else "未填写")
        st.warning("本页只是基础预检，帮助发现需要人工检查的地方，不代表亚马逊平台审核结果或法律结论。")


elif page == "行动与复盘":
    st.title("行动与复盘")
    st.caption("把规则异常转成有负责人、有期限、有验证标准的动作台账。")
    if require_sales():
        anomalies = anomaly_data()
        if anomalies.empty:
            st.success("当前未识别到规则异常。")
        else:
            signature = "v2|" + "|".join(anomalies.astype(str).agg("-".join, axis=1).tolist())
            if st.session_state.get("action_signature") != signature or "action_board" not in st.session_state:
                board = anomalies.copy()
                board.insert(0, "优先级", board["严重程度"].map({"🔴": "P0", "🟡": "P1"}).fillna("P2"))
                board["负责人"] = "待分配"
                board["截止时间"] = "7 天内"
                board["验证标准"] = board["异常类型"].apply(lambda value: "3 天看领先指标，7 天看结果" if value != "库存风险" else "确认补货节点并关闭断货风险")
                board["状态"] = "待处理"
                board["执行前指标"] = board["核心指标"]
                board["执行后指标"] = "待填写"
                board["结果判断"] = "待验证"
                board["复盘结论"] = "待填写"
                board["下一步动作"] = "待填写"
                st.session_state.action_board = board[["优先级", "SKU", "产品名称", "异常类型", "建议", "负责人", "截止时间", "验证标准", "状态", "执行前指标", "执行后指标", "结果判断", "复盘结论", "下一步动作"]]
                st.session_state.action_signature = signature
            edited = st.data_editor(
                st.session_state.action_board, width="stretch", hide_index=True, num_rows="fixed",
                column_config={
                    "优先级": st.column_config.SelectboxColumn(options=["P0", "P1", "P2"]),
                    "状态": st.column_config.SelectboxColumn(options=["待处理", "进行中", "待验证", "已关闭"]),
                    "结果判断": st.column_config.SelectboxColumn(options=["待验证", "有效", "无效", "继续观察"]),
                },
                disabled=["SKU", "产品名称", "异常类型", "执行前指标"],
            )
            st.session_state.action_board = edited
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("总动作", len(edited))
            s2.metric("待处理", int((edited["状态"] == "待处理").sum()))
            s3.metric("进行中", int((edited["状态"] == "进行中").sum()))
            s4.metric("已关闭", int((edited["状态"] == "已关闭").sum()))
            st.caption("关闭动作前应填写执行后指标、结果判断和复盘结论；台账保存在当前浏览器会话中。")


elif page == "数据中心":
    st.title("数据中心")
    st.caption("数据可以按来源分批导入；系统负责字段识别、基础校验、增量合并和完整度提示。")
    uploaded_files = st.file_uploader("上传 CSV / Excel，可一次选择多份", type=["csv", "xlsx", "xls"], accept_multiple_files=True)
    if uploaded_files and st.button("识别、校验并合并", type="primary"):
        for uploaded in uploaded_files:
            try:
                raw = read_file(uploaded)
                table_type = detect_table_type(raw.columns)
                if not table_type:
                    st.error(f"{uploaded.name}：无法识别表类型，请检查列名。")
                    continue
                mapping = suggest_mapping(list(raw.columns))
                mapped = raw.rename(columns={column: field for column, field in mapping.items() if field})
                if table_type == TABLE_LISTING and "关键词" in mapped.columns and "Search Terms" not in mapped.columns:
                    mapped = mapped.rename(columns={"关键词": "Search Terms"})
                all_fields = set().union(*SCHEMA.values())
                mapped = mapped[[column for column in mapped.columns if column in all_fields]]
                errors = [item["消息"] for item in validate_table(mapped, table_type) if item["级别"] == ERROR]
                if errors:
                    st.error(f"{uploaded.name} → {table_type}：{'；'.join(errors)}")
                    continue
                mapped, date_errors = normalize_dates(mapped)
                if date_errors:
                    st.error(f"{uploaded.name}：{'；'.join(date_errors)}")
                    continue
                existing = st.session_state.tables.get(table_type)
                merged = merge_imported_table(existing, mapped, table_type)
                st.session_state.tables[table_type] = merged
                mode = "首次导入" if existing is None else "增量更新"
                st.success(f"{uploaded.name} → {table_type}：{mode}完成，当前 {len(merged)} 行。")
            except Exception as exc:
                st.error(f"{uploaded.name}：导入失败——{exc}")

    st.divider()
    st.subheader("数据完整度")
    cadence = {TABLE_SALES: "每日/每周", TABLE_ADS: "每日/每周", TABLE_SEARCH_TERMS: "每周", TABLE_INVENTORY: "每日快照", TABLE_PRODUCT: "产品变化时", TABLE_LISTING: "页面调整后", TABLE_COMPETITOR: "每周/大促前", TABLE_PROFIT: "每周/月"}
    rows = []
    for table_name in ALL_TABLES:
        frame = st.session_state.tables.get(table_name)
        rows.append({"数据表": table_name, "状态": "已导入" if frame is not None else "待导入", "记录数": len(frame) if frame is not None else 0, "更新建议": cadence[table_name]})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if st.session_state.tables:
        consistency = check_sku_consistency(st.session_state.tables)
        if consistency:
            st.subheader("跨表 SKU 检查")
            st.dataframe(pd.DataFrame(consistency), width="stretch", hide_index=True)

    st.divider()
    st.subheader("推荐来源")
    st.markdown("""
    - **销售表**：Amazon Business Reports，按日期和 SKU 增量更新。
    - **广告表**：Sponsored Products 报告，按日期和 SKU 增量更新。
    - **搜索词表**：搜索词报告，按 SKU、活动和搜索词增量更新。
    - **库存表**：库存报告，作为最新快照覆盖。
    - **产品与 Listing**：后台资料或内部产品台账，按 SKU 更新。
    - **竞品表**：当前示例数据由程序模拟；真实数据可来自人工调研、公司竞品台账或合规数据服务，并应填写竞品 ASIN、来源和采集日期。
    - **利润表**：销售、采购成本、广告、平台物流费和退款统一汇总。
    """)

    report_path = os.path.join(os.path.dirname(__file__), "outputs", "亚马逊经营周报.xlsx")
    if os.path.exists(report_path):
        with open(report_path, "rb") as report_file:
            st.download_button(
                "下载示例经营周报（Excel）",
                data=report_file.read(),
                file_name="亚马逊经营周报.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        st.caption("示例周报由项目模拟数据生成，包含经营概览、SKU 利润、搜索词诊断和行动复盘。")

    with st.expander("项目方法：30 天接手业务计划与 AI 辅助边界"):
        plan = pd.DataFrame([
            {"阶段": "第 1 周", "目标": "建立经营基线", "动作": "核验数据口径、SKU 分层、识别增长与风险"},
            {"阶段": "第 2 周", "目标": "验证优先动作", "动作": "处理 P0 风险，测试广告、Listing 或库存动作"},
            {"阶段": "第 3 周", "目标": "放大有效策略", "动作": "扩大有效投放，停止无效动作，守住利润和库存"},
            {"阶段": "第 4 周", "目标": "复盘并标准化", "动作": "复盘目标偏差，沉淀动作台账和下月计划"},
        ])
        st.dataframe(plan, width="stretch", hide_index=True)
        st.markdown("**AI 辅助边界**：AI 用于调研、归纳和初稿；运营负责人核验数据、风险与利润口径，并对最终动作和经营结果负责。")
