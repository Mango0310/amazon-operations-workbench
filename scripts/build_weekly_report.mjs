import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectDir = path.resolve(__dirname, "..");
const outputDir = path.join(projectDir, "outputs");

function parseCsv(text) {
  const lines = text.replace(/^\uFEFF/, "").trim().split(/\r?\n/);
  const parseLine = (line) => {
    const cells = [];
    let cell = "", quoted = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"' && quoted && line[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = !quoted;
      else if (ch === "," && !quoted) { cells.push(cell); cell = ""; }
      else cell += ch;
    }
    cells.push(cell);
    return cells;
  };
  const headers = parseLine(lines[0]);
  return lines.slice(1).map((line) => Object.fromEntries(headers.map((h, i) => [h, parseLine(line)[i] ?? ""])));
}

async function readCsv(name) {
  return parseCsv(await fs.readFile(path.join(projectDir, "data", `${name}.csv`), "utf8"));
}

const [profits, inventory, searchTerms] = await Promise.all([
  readCsv("利润表"), readCsv("库存表"), readCsv("搜索词表"),
]);

const workbook = Workbook.create();
workbook.comments.setSelf({ displayName: "User" });
const dashboard = workbook.worksheets.add("经营周报");
const skuSheet = workbook.worksheets.add("SKU利润");
const termSheet = workbook.worksheets.add("搜索词诊断");
const actionSheet = workbook.worksheets.add("行动复盘");
const notesSheet = workbook.worksheets.add("数据说明");

const navy = "#17324D", blue = "#2F6BFF", pale = "#EAF1FF", light = "#F5F7FA", green = "#DDF4E7", red = "#FDE2E2", amber = "#FFF1CC", white = "#FFFFFF", gray = "#64748B";
const titleFormat = { fill: navy, font: { bold: true, color: white, size: 18 }, verticalAlignment: "center" };
const sectionFormat = { fill: pale, font: { bold: true, color: navy }, verticalAlignment: "center" };
const headerFormat = { fill: navy, font: { bold: true, color: white }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };

// SKU利润：保持来源明细，利润率为可审计公式。
const sortedProfits = [...profits].sort((a, b) => Number(b["销售额"]) - Number(a["销售额"]));
skuSheet.getRange("A1:I1").values = [["SKU", "销售额", "产品成本", "广告花费", "平台及物流费", "退款金额", "经营利润", "经营利润率", "利润状态"]];
skuSheet.getRange(`A2:G${sortedProfits.length + 1}`).values = sortedProfits.map((r) => [
  r.SKU, Number(r["销售额"]), Number(r["产品成本"]), Number(r["广告花费"]),
  Number(r["平台及物流费"]), Number(r["退款金额"]), Number(r["利润"]),
]);
skuSheet.getRange("H2").formulas = [["=IFERROR(G2/B2,0)"]];
skuSheet.getRange(`H2:H${sortedProfits.length + 1}`).fillDown();
skuSheet.getRange("I2").formulas = [["=IF(H2<10%,\"高风险\",IF(H2<20%,\"关注\",\"健康\"))"]];
skuSheet.getRange(`I2:I${sortedProfits.length + 1}`).fillDown();
skuSheet.getRange("A1:I1").format = headerFormat;
skuSheet.getRange(`B2:G${sortedProfits.length + 1}`).format.numberFormat = '"$"#,##0';
skuSheet.getRange(`H2:H${sortedProfits.length + 1}`).format.numberFormat = "0.0%";
skuSheet.tables.add(`A1:I${sortedProfits.length + 1}`, true, "SkuProfitTable").style = "TableStyleMedium2";
skuSheet.freezePanes.freezeRows(1);
skuSheet.showGridLines = false;
skuSheet.getRange("A:I").format.autofitColumns();
skuSheet.getRange("A:A").format.columnWidth = 12;
skuSheet.getRange("I:I").format.columnWidth = 14;
skuSheet.getRange(`I2:I${sortedProfits.length + 1}`).conditionalFormats.add("containsText", { text: "高风险", format: { fill: red, font: { color: "#9B1C1C", bold: true } } });
skuSheet.getRange(`I2:I${sortedProfits.length + 1}`).conditionalFormats.add("containsText", { text: "健康", format: { fill: green, font: { color: "#176B3A" } } });

// 搜索词诊断：原始字段 + 公式指标 + 公式动作。
termSheet.getRange("A1:O1").values = [["SKU", "广告活动", "匹配方式", "关键词", "搜索词", "曝光", "点击", "广告花费", "广告订单", "广告销售额", "CTR", "CVR", "CPC", "ACOS", "建议动作"]];
termSheet.getRange(`A2:J${searchTerms.length + 1}`).values = searchTerms.map((r) => [
  r.SKU, r["广告活动"], r["匹配方式"], r["关键词"], r["搜索词"], Number(r["曝光"]), Number(r["点击"]),
  Number(r["广告花费"]), Number(r["广告订单"]), Number(r["广告销售额"]),
]);
const termFormulaRows = searchTerms.map((_, index) => {
  const row = index + 2;
  return [
    `=IFERROR(G${row}/F${row},0)`, `=IFERROR(I${row}/G${row},0)`, `=IFERROR(H${row}/G${row},0)`, `=IFERROR(H${row}/J${row},0)`,
    `=IF(I${row}=0,IF(H${row}>=15,"P0 · 否定或暂停","P2 · 继续观察"),IF(N${row}>45%,"P1 · 降低竞价",IF(AND(I${row}>=3,N${row}<=25%),"P1 · 精准扩量","观察")))`,
  ];
});
termSheet.getRange(`K2:O${searchTerms.length + 1}`).formulas = termFormulaRows;
termSheet.getRange("A1:O1").format = headerFormat;
termSheet.getRange(`H2:H${searchTerms.length + 1}`).format.numberFormat = '"$"#,##0.00';
termSheet.getRange(`J2:J${searchTerms.length + 1}`).format.numberFormat = '"$"#,##0';
termSheet.getRange(`K2:L${searchTerms.length + 1}`).format.numberFormat = "0.00%";
termSheet.getRange(`M2:M${searchTerms.length + 1}`).format.numberFormat = '"$"0.00';
termSheet.getRange(`N2:N${searchTerms.length + 1}`).format.numberFormat = "0.0%";
termSheet.tables.add(`A1:O${searchTerms.length + 1}`, true, "SearchTermTable").style = "TableStyleMedium2";
termSheet.freezePanes.freezeRows(1);
termSheet.freezePanes.freezeColumns(1);
termSheet.showGridLines = false;
termSheet.getRange("A:O").format.autofitColumns();
termSheet.getRange("B:B").format.columnWidth = 18;
termSheet.getRange("D:E").format.columnWidth = 24;
termSheet.getRange("O:O").format.columnWidth = 22;
termSheet.getRange(`O2:O${searchTerms.length + 1}`).conditionalFormats.add("beginsWith", { text: "P0", format: { fill: red, font: { color: "#9B1C1C", bold: true } } });
termSheet.getRange(`O2:O${searchTerms.length + 1}`).conditionalFormats.add("beginsWith", { text: "P1", format: { fill: amber, font: { color: "#7A4B00", bold: true } } });

// 行动复盘：从库存风险和搜索词浪费中生成初始动作。
const actions = [];
for (const r of inventory) {
  const days = Number(r["当前库存"]) / Math.max(Number(r["日均销量"]), 1);
  if (days <= 30) actions.push([days <= 15 ? "P0" : "P1", r.SKU, "库存风险", "确认采购周期与建议补货量", "待分配", "7天内", `可售 ${days.toFixed(0)} 天`, "待填写", "待验证", "待填写", "待填写", "待处理"]);
}
for (const r of searchTerms.filter((x) => Number(x["广告花费"]) >= 15 && Number(x["广告订单"]) === 0).sort((a, b) => Number(b["广告花费"]) - Number(a["广告花费"])).slice(0, 7)) {
  actions.push(["P0", r.SKU, `搜索词浪费：${r["搜索词"]}`, "核查相关性后否定或暂停", "待分配", "3天内", `花费 $${Number(r["广告花费"]).toFixed(0)} / 0订单`, "待填写", "待验证", "待填写", "待填写", "待处理"]);
}
actionSheet.getRange("A1:L1").values = [["优先级", "SKU", "问题", "建议动作", "负责人", "截止时间", "执行前指标", "执行后指标", "结果判断", "复盘结论", "下一步动作", "状态"]];
actionSheet.getRange(`A2:L${actions.length + 1}`).values = actions;
actionSheet.getRange("A1:L1").format = headerFormat;
actionSheet.tables.add(`A1:L${actions.length + 1}`, true, "ActionReviewTable").style = "TableStyleMedium2";
actionSheet.getRange(`A2:A${actions.length + 50}`).dataValidation = { rule: { type: "list", values: ["P0", "P1", "P2"] } };
actionSheet.getRange(`I2:I${actions.length + 50}`).dataValidation = { rule: { type: "list", values: ["待验证", "有效", "无效", "继续观察"] } };
actionSheet.getRange(`L2:L${actions.length + 50}`).dataValidation = { rule: { type: "list", values: ["待处理", "进行中", "待验证", "已关闭"] } };
actionSheet.freezePanes.freezeRows(1);
actionSheet.showGridLines = false;
actionSheet.getRange("A:L").format.autofitColumns();
actionSheet.getRange("C:D").format.columnWidth = 28;
actionSheet.getRange("G:K").format.columnWidth = 20;
actionSheet.getRange(`A2:A${actions.length + 1}`).conditionalFormats.add("containsText", { text: "P0", format: { fill: red, font: { color: "#9B1C1C", bold: true } } });

// 经营周报 Dashboard。
dashboard.mergeCells("A1:H2");
dashboard.getRange("A1:H2").values = [["亚马逊经营周报"]];
dashboard.getRange("A1:H2").format = titleFormat;
dashboard.getRange("A3:H3").merge();
dashboard.getRange("A3:H3").values = [["数据周期：示例数据近 30 天｜广告与 SKU 诊断重点展示最近经营表现"]];
dashboard.getRange("A3:H3").format = { fill: light, font: { color: gray }, verticalAlignment: "center" };
dashboard.getRange("A5:B5").values = [["销售额", "经营利润"]];
dashboard.getRange("D5:E5").values = [["经营利润率", "广告花费"]];
dashboard.getRange("G5:H5").values = [["P0 动作", "待关闭动作"]];
for (const range of ["A5:B5", "D5:E5", "G5:H5"]) dashboard.getRange(range).format = sectionFormat;
dashboard.getRange("A6").formulas = [[`=SUM('SKU利润'!B2:B${sortedProfits.length + 1})`]];
dashboard.getRange("B6").formulas = [[`=SUM('SKU利润'!G2:G${sortedProfits.length + 1})`]];
dashboard.getRange("D6").formulas = [["=IFERROR(B6/A6,0)"]];
dashboard.getRange("E6").formulas = [[`=SUM('SKU利润'!D2:D${sortedProfits.length + 1})`]];
dashboard.getRange("G6").formulas = [[`=COUNTIF('行动复盘'!A2:A${actions.length + 1},\"P0\")`]];
dashboard.getRange("H6").formulas = [[`=COUNTIF('行动复盘'!L2:L${actions.length + 1},\"<>已关闭\")`]];
dashboard.getRange("A6:B6").format.numberFormat = '"$"#,##0';
dashboard.getRange("D6").format.numberFormat = "0.0%";
dashboard.getRange("E6").format.numberFormat = '"$"#,##0';
dashboard.getRange("A6:H6").format = { font: { bold: true, size: 16, color: navy }, rowHeight: 34 };

dashboard.getRange("A8:B8").values = [["SKU", "销售额"]];
dashboard.getRange("A8:B8").format = headerFormat;
for (let i = 0; i < 10; i++) {
  dashboard.getRange(`A${9 + i}:B${9 + i}`).formulas = [[`='SKU利润'!A${2 + i}`, `='SKU利润'!B${2 + i}`]];
}
dashboard.getRange("B9:B18").format.numberFormat = '"$"#,##0';
const chart = dashboard.charts.add("bar", dashboard.getRange("A8:B18"));
chart.title = "Top 10 SKU 销售贡献（$）";
chart.hasLegend = false;
chart.xAxis = { axisType: "textAxis", textStyle: { fontSize: 9 } };
chart.yAxis = { numberFormatCode: '"$"#,##0' };
chart.setPosition("D8", "H23");

dashboard.getRange("A21:B21").values = [["行动状态", "数量"]];
dashboard.getRange("A21:B21").format = headerFormat;
dashboard.getRange("A22:A25").values = [["待处理"], ["进行中"], ["待验证"], ["已关闭"]];
for (let i = 0; i < 4; i++) dashboard.getRange(`B${22 + i}`).formulas = [[`=COUNTIF('行动复盘'!L2:L${actions.length + 1},A${22 + i})`]];
dashboard.getRange("A27:H28").merge();
dashboard.getRange("A27:H28").values = [["使用说明：先看 KPI 与 P0 动作，再到搜索词诊断和行动复盘填写执行后指标。所有结论均基于模拟数据。"]];
dashboard.getRange("A27:H28").format = { fill: amber, font: { color: "#6B4E00" }, wrapText: true, verticalAlignment: "center" };
dashboard.showGridLines = false;
dashboard.getRange("A:H").format.columnWidth = 16;
dashboard.getRange("A:A").format.columnWidth = 18;
dashboard.getRange("A1:H28").format.font = { name: "Microsoft YaHei" };

// 数据说明。
notesSheet.getRange("A1:D1").merge();
notesSheet.getRange("A1:D1").values = [["数据口径与指标定义"]];
notesSheet.getRange("A1:D1").format = titleFormat;
notesSheet.getRange("A1:D1").format.rowHeight = 34;
notesSheet.getRange("A3:D3").values = [["主题", "定义", "来源", "注意事项"]];
notesSheet.getRange("A3:D3").format = headerFormat;
notesSheet.getRange("A4:D10").values = [
  ["销售与利润", "经营利润=销售额-产品成本-广告-平台物流费-退款", "data/利润表.csv", "利润表采用导入期汇总"],
  ["ACOS", "广告花费/广告销售额", "data/搜索词表.csv", "需结合产品阶段与利润判断"],
  ["TACOS", "广告花费/全部销售额", "data/广告表.csv + 销售表.csv", "反映广告对整体经营的影响"],
  ["CTR", "点击/曝光", "data/搜索词表.csv", "低 CTR 需核查相关性和主图"],
  ["CVR", "广告订单/点击", "data/搜索词表.csv", "低 CVR 需核查搜索意图、价格和 Listing"],
  ["行动复盘", "执行前指标→动作→执行后指标→结果判断", "行动复盘工作表", "关闭动作前必须填写结果"],
  ["数据性质", "20 SKU 的模拟经营数据", "generate_data.py", "不得包装成真实店铺业绩"],
];
notesSheet.getRange("A3:D10").format.wrapText = true;
notesSheet.getRange("A:D").format.autofitColumns();
notesSheet.getRange("A:A").format.columnWidth = 18;
notesSheet.getRange("B:D").format.columnWidth = 36;
notesSheet.showGridLines = false;

await fs.mkdir(outputDir, { recursive: true });
const inspect = await workbook.inspect({ kind: "table", range: "经营周报!A1:H28", include: "values,formulas", tableMaxRows: 28, tableMaxCols: 8 });
console.log(inspect.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula errors" });
console.log(errors.ndjson);
for (const sheetName of ["经营周报", "SKU利润", "搜索词诊断", "行动复盘", "数据说明"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(outputDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(outputDir, "亚马逊经营周报.xlsx"));
