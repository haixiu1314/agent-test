"""报告导出均来自冻结业务快照；HTML 转义、CSV 防公式注入。"""

import csv
import io
import json
import textwrap
from html import escape


def export_report(data, format):
    if format == "json":
        return json.dumps(
            data, ensure_ascii=False, indent=2
        ).encode(), "application/json"
    if format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(
            ["case_id", "name", "type", "status", "duration_ms", "output", "error_code"]
        )

        def safe(value):
            value = str(value if value is not None else "")
            return (
                "'" + value
                if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                else value
            )

        for row in data["results"]:
            writer.writerow(
                [
                    safe(row.get(k))
                    for k in [
                        "case_key",
                        "name",
                        "test_type",
                        "status",
                        "duration_ms",
                        "output",
                        "error_code",
                    ]
                ]
            )
        return ("\ufeff" + stream.getvalue()).encode("utf-8"), "text/csv; charset=utf-8"
    if format == "html":
        parts = [
            '<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width"><title>AgentTestLab 测试报告</title><style>body{font:16px/1.7 system-ui;max-width:1080px;margin:32px auto;padding:20px;color:#17243a}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f4f8;padding:16px}article{border-top:1px solid #d6dfeb;padding:20px 0}h1{font-size:26px}h2{font-size:20px}</style><h1>AgentTestLab 测试报告</h1>',
            "<h2>" + escape(data["task"]["name"]) + "</h2>",
            "<h2>统计与评分（缺失维度不代表满分）</h2><pre>"
            + escape(json.dumps(data["summary"], ensure_ascii=False, indent=2))
            + "</pre>",
        ]
        for row in data["results"]:
            parts.append(
                "<article><h2>"
                + escape(row["name"])
                + "</h2><pre>"
                + escape(json.dumps(row, ensure_ascii=False, indent=2))
                + "</pre></article>"
            )
        parts.append("</html>")
        return "".join(parts).encode("utf-8"), "text/html; charset=utf-8"
    import pymupdf

    from pathlib import Path

    doc = pymupdf.open()
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font_name = "reportfont" if font_path.exists() else "china-s"
    summary = data["summary"]
    performance = summary["performance"]
    show = lambda value: (
        "未提供"
        if value is None
        else str(round(value, 3) if isinstance(value, float) else value)
    )
    names = {
        "functional": "功能正确性",
        "behavior": "规划、记忆与工具行为",
        "rag": "RAG 质量",
        "security": "安全性",
        "stability": "执行稳定性",
    }
    lines = [
        ("AgentTestLab 测试报告", 20),
        (data["task"]["name"], 14),
        ("任务 ID: " + data["task"]["id"], 9),
        ("测试概况", 14),
        (
            f"总数 {summary['total']}；通过率 {show(summary['pass_rate'] * 100 if summary['pass_rate'] is not None else None)}%；状态计数 {json.dumps(summary['counts'], ensure_ascii=False)}",
            10,
        ),
        (
            "已观测维度加权分："
            + show(summary["score"])
            + " / 100。缺失维度不代表满分。",
            12,
        ),
        (
            "严重安全风险："
            + (
                "有，必须独立处理"
                if summary["risk_warning"]
                else "未记录高危违规，不等于安全认证"
            ),
            10,
        ),
        ("评分维度与有效权重", 14),
    ]
    for key, value in summary["dimensions"].items():
        weight = summary["effective_weights"].get(key)
        lines.append(
            (
                names[key]
                + "："
                + show(value)
                + "；有效权重 "
                + (show(weight * 100) + "%" if weight is not None else "未计入"),
                10,
            )
        )
    lines.extend(
        [
            (summary["score_rule"], 9),
            ("性能与证据覆盖", 14),
            (
                "平均 "
                + show(performance["average_ms"])
                + " ms；P95 "
                + show(performance["p95_ms"])
                + " ms；最大 "
                + show(performance["maximum_ms"])
                + " ms",
                10,
            ),
            (
                "Token 总数："
                + show(performance["total_tokens"])
                + "；提供 Token 的样本："
                + str(performance["token_samples"]),
                10,
            ),
            (summary["coverage"]["note"], 9),
            ("缺陷与修复建议", 14),
        ]
    )
    for defect in summary["defects"]:
        lines.extend(
            [
                (defect["category"] + "：" + defect["reason"], 10),
                (defect["recommendation"], 10),
            ]
        )
    if not summary["defects"]:
        lines.append(("本任务没有记录可归因缺陷。", 10))
    lines.extend(
        [
            ("逐题明细", 14),
            (
                "PDF 每题输入与回答最多展示 2000 字；完整快照、配置、事件和原始明细请导出 JSON。",
                9,
            ),
        ]
    )
    for row in data["results"]:
        lines.extend(
            [
                (row["name"] + " / " + row["status"], 12),
                ("输入: " + row["case"]["user_input"][:2000], 10),
                ("输出: " + row.get("output", "")[:2000], 10),
                ("错误: " + show(row.get("error_code")), 10),
            ]
        )
        for evaluation in row["evaluations"]:
            lines.append(
                (
                    evaluation["evaluator"]
                    + " / "
                    + evaluation["status"]
                    + " / "
                    + show(evaluation["score"])
                    + "："
                    + evaluation["detail"].get("reason", "")[:1000],
                    10,
                )
            )
    page = None
    y = 800
    for paragraph, size in lines:
        for line in paragraph.splitlines() or [""]:
            for segment in textwrap.wrap(line, width=48, replace_whitespace=False) or [
                ""
            ]:
                if y + size > 785:
                    page = doc.new_page(width=595, height=842)
                    if font_path.exists():
                        page.insert_font(fontname=font_name, fontfile=str(font_path))
                    y = 45
                page.insert_text((40, y), segment, fontname=font_name, fontsize=size)
                y += size + 7
    for number, page in enumerate(doc):
        page.insert_text(
            (40, 815),
            f"AgentTestLab  /  {number + 1} / {len(doc)}",
            fontname="helv",
            fontsize=8,
            color=(0.4, 0.4, 0.4),
        )
    if font_path.exists():
        doc.subset_fonts()
    raw = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return raw, "application/pdf"
