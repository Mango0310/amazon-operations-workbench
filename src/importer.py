# -*- coding: utf-8 -*-
"""
数据导入层：读取文件、识别表类型、字段映射、数据校验、SKU 一致性检查。

所有分析都只接受经过这里校验、且列名已映射为规范字段的 DataFrame。
"""
import io
import re
import pandas as pd

from .schema import (
    SCHEMA, REQUIRED, NUMERIC_FIELDS, DATE_FIELDS,
    normalize_name, suggest_mapping,
    TABLE_PRODUCT, TABLE_LISTING, TABLE_SALES, TABLE_INVENTORY,
    TABLE_ADS, TABLE_SEARCH_TERMS, TABLE_COMPETITOR, TABLE_PROFIT,
)

# 校验结果级别
PASS = "pass"
WARN = "warn"
ERROR = "error"


# ---------------------------------------------------------------------------
# 读取文件
# ---------------------------------------------------------------------------
def read_file(uploaded):
    """读取上传的 CSV 或 Excel，返回 DataFrame。"""
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded)
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded)
    raise ValueError("仅支持 CSV / Excel 文件")


# ---------------------------------------------------------------------------
# 表类型识别
# ---------------------------------------------------------------------------
def detect_table_type(columns):
    """根据列名映射到的规范字段，判断最可能是哪张表。返回表类型名。"""
    mapping = suggest_mapping(columns)
    mapped_fields = set(v for v in mapping.values() if v is not None)
    scores = {}
    for table, fields in SCHEMA.items():
        scores[table] = len(mapped_fields & set(fields))
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None


# ---------------------------------------------------------------------------
# 字段映射应用
# ---------------------------------------------------------------------------
def apply_mapping(df, mapping):
    """
    按用户确认的映射重命名列。mapping: {原列名: 规范字段名}
    只保留映射到规范字段的列，并按 SCHEMA 顺序输出；未映射的列丢弃。
    """
    rename = {col: field for col, field in mapping.items() if field}
    df = df.rename(columns=rename)
    all_fields = set().union(*SCHEMA.values())
    keep = [c for c in df.columns if c in all_fields]
    return df[keep]


# ---------------------------------------------------------------------------
# 日期标准化
# ---------------------------------------------------------------------------
def _to_standard_date(series):
    """把各种日期格式统一转为 YYYY-MM-DD 字符串，无法解析的置为 NaN。"""
    s = series.astype(str).str.strip()
    # 处理中文格式 "2026年8月16日"
    s = s.str.replace(r"[年月]", "-", regex=True).str.replace("日", "", regex=True)
    # 处理 "8/16/2026" 或 "2026/8/16"
    return pd.to_datetime(s, errors="coerce")


def normalize_dates(df):
    """将日期字段标准化，返回 (df, 错误信息列表)。"""
    errors = []
    for f in DATE_FIELDS:
        if f not in df.columns:
            continue
        parsed = _to_standard_date(df[f])
        bad = df[f][parsed.isna() & df[f].notna() & (df[f].astype(str).str.strip() != "")]
        if len(bad):
            errors.append(f"字段「{f}」存在 {len(bad)} 个无法识别的日期")
        df[f] = parsed.dt.strftime("%Y-%m-%d")
    return df, errors


# ---------------------------------------------------------------------------
# 单表校验
# ---------------------------------------------------------------------------
def validate_table(df, table_type):
    """
    校验单张表，返回校验结果列表。
    每项: {"检查项": str, "级别": pass/warn/error, "消息": str}
    不修改传入的 df。
    """
    df = df.copy()
    results = []
    required = REQUIRED.get(table_type, [])
    fields = list(df.columns)

    # 1) 必填字段
    missing = [f for f in required if f not in fields]
    if missing:
        results.append({"检查项": "必填字段", "级别": ERROR, "消息": f"缺少字段：{', '.join(missing)}"})
    else:
        results.append({"检查项": "必填字段", "级别": PASS, "消息": "必填字段齐全"})

    # 2) SKU 空值
    if "SKU" in fields:
        n_null = df["SKU"].isna().sum()
        if n_null:
            results.append({"检查项": "SKU 空值", "级别": ERROR, "消息": f"存在 {n_null} 行缺少 SKU"})
        else:
            results.append({"检查项": "SKU 空值", "级别": PASS, "消息": "SKU 无空值"})

    # 3) 数值字段：类型 + 负值
    for f in NUMERIC_FIELDS & set(fields):
        conv = pd.to_numeric(df[f], errors="coerce")
        bad = (conv.isna() & df[f].notna() & (df[f].astype(str).str.strip() != "")).sum()
        neg = (conv < 0).sum()
        if bad:
            results.append({"检查项": "数值类型", "级别": ERROR, "消息": f"字段「{f}」存在 {bad} 个非数值"})
        if neg:
            results.append({"检查项": "数值范围", "级别": WARN, "消息": f"字段「{f}」存在 {neg} 个负值"})

    # 4) 日期标准化
    if DATE_FIELDS & set(fields):
        df, date_errs = normalize_dates(df)
        for msg in date_errs:
            results.append({"检查项": "日期格式", "级别": ERROR, "消息": msg})

    # 5) 空行
    empty_rows = df.dropna(how="all").shape[0]
    if empty_rows < len(df):
        results.append({"检查项": "空行", "级别": WARN, "消息": f"存在 {len(df) - empty_rows} 个空行"})

    return results


# ---------------------------------------------------------------------------
# SKU 一致性检查（跨表）
# ---------------------------------------------------------------------------
def check_sku_consistency(tables):
    """
    tables: {表类型: DataFrame（已映射规范字段）}
    检查：各表的 SKU 是否都出现在产品表中。
    返回结果列表。
    """
    results = []
    products_sku = set()
    if TABLE_PRODUCT in tables and "SKU" in tables[TABLE_PRODUCT].columns:
        products_sku = set(tables[TABLE_PRODUCT]["SKU"].dropna())

    for table in (TABLE_LISTING, TABLE_SALES, TABLE_INVENTORY, TABLE_ADS, TABLE_SEARCH_TERMS, TABLE_COMPETITOR, TABLE_PROFIT):
        if table not in tables or "SKU" not in tables[table].columns:
            continue
        skus = set(tables[table]["SKU"].dropna())
        if products_sku:
            extra = skus - products_sku
            if extra:
                results.append({
                    "检查项": "SKU 一致性",
                    "级别": WARN,
                    "消息": f"{table} 存在 {len(extra)} 个产品表中不存在的 SKU：{', '.join(sorted(extra)[:10])}",
                })
            else:
                results.append({"检查项": "SKU 一致性", "级别": PASS, "消息": f"{table} SKU 与产品表一致"})
        else:
            results.append({"检查项": "SKU 一致性", "级别": WARN, "消息": f"产品表未导入，无法校验 {table} 的 SKU 一致性"})
    return results
