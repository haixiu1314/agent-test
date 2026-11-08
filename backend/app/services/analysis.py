"""从实际持久化结果计算评分、回归与覆盖；缺失维度保持空值。"""

from collections import Counter
from sqlalchemy import select
from fastapi import HTTPException
from app.models.platform import (
    TestResult,
    EvaluationDetail,
    TraceEvent,
    SecurityFinding,
)

TERMINAL = {"completed", "cancelled", "error", "interrupted"}


def results_for(db, app, task):
    rows = db.scalars(
        select(TestResult)
        .where(TestResult.task_id == task.id)
        .order_by(TestResult.created_at, TestResult.id)
    ).all()
    output = []
    for row in rows:
        payload = app.state.vault.decrypt(row.payload)
        evaluations = db.scalars(
            select(EvaluationDetail).where(EvaluationDetail.result_id == row.id)
        ).all()
        events = db.scalars(
            select(TraceEvent)
            .where(TraceEvent.result_id == row.id)
            .order_by(TraceEvent.created_at, TraceEvent.id)
        ).all()
        output.append(
            {
                "id": row.id,
                "case_key": row.case_key,
                "name": row.case_name,
                "test_type": row.test_type,
                "status": row.status,
                "duration_ms": row.duration_ms,
                "usage": row.usage,
                "error_code": row.error_code,
                **payload,
                "evaluations": [
                    {
                        "evaluator": d.evaluator,
                        "status": d.status,
                        "score": d.score,
                        "detail": d.detail,
                    }
                    for d in evaluations
                ],
                "events": [
                    {
                        "id": e.id,
                        "parent_event_id": e.parent_event_id,
                        "event_type": e.event_type,
                        "event_name": e.event_name,
                        "status": e.status,
                        "duration_ms": e.duration_ms,
                        "timestamp": e.created_at.isoformat(),
                        "data": app.state.vault.decrypt(e.payload),
                    }
                    for e in events
                ],
            }
        )
    return output


def mean(values):
    return round(sum(values) / len(values), 4) if values else None


def diagnostics(row):
    """只给有依据的归因；最终语义错误需评估器证据，不能靠关键词猜测。"""
    if row.get("error_code"):
        return {
            "category": "execution",
            "reason": row["error_code"],
            "recommendation": "检查目标连接、超时和模型配置后复测",
        }
    failed = [
        d
        for d in row["evaluations"]
        if d["status"] in ["failed", "error", "unavailable"]
    ]
    if not failed:
        return None
    tools = [e["data"] for e in row["events"] if e["event_type"] == "tool_result"]
    if any(t.get("success") is False for t in tools):
        return {
            "category": "tool_execution",
            "reason": "真实工具结果包含失败",
            "recommendation": "检查工具参数、服务及异常处理",
        }
    if any(d["evaluator"] == "tool_trace" and d["status"] == "failed" for d in failed):
        return {
            "category": "tool_selection_or_arguments",
            "reason": "工具名称或参数未匹配用例要求",
            "recommendation": "对照来源事件核查工具选择与参数提取",
        }
    if any(d["status"] == "unavailable" for d in failed):
        return {
            "category": "missing_evidence",
            "reason": "配置或可观测证据不足",
            "recommendation": "补齐模型/事件映射，不将未知当通过",
        }
    return {
        "category": "evaluation",
        "reason": "; ".join(d["detail"].get("reason", "") for d in failed)[:2000],
        "recommendation": "对照实际回答、参考答案及判定依据人工复核",
    }


def summarize(rows, weights, findings):
    import numpy as np

    counts = Counter(r["status"] for r in rows)
    n = len(rows)
    by_type = {
        kind: {
            "total": len(group := [r for r in rows if r["test_type"] == kind]),
            "passed": sum(r["status"] == "passed" for r in group),
            "pass_rate": mean([float(r["status"] == "passed") for r in group]),
        }
        for kind in sorted({r["test_type"] for r in rows})
    }

    def scores(types, evaluators=None):
        return [
            float(d["score"]) * 100
            for r in rows
            if r["test_type"] in types
            for d in r["evaluations"]
            if d["status"] in ["passed", "failed"]
            and d["score"] is not None
            and (evaluators is None or d["evaluator"] in evaluators)
        ]

    dimensions = {
        "functional": mean(scores({"functional", "boundary"})),
        "behavior": mean(scores({"planning", "memory", "tool"})),
        "rag": mean(scores({"rag"}, {"ragas"})),
        "security": mean(scores({"security"}, {"security_policy", "llm_judge"})),
        "stability": 100 * (1 - counts["error"] / executed)
        if (
            executed := sum(
                counts[s] for s in ["passed", "failed", "error", "inconclusive"]
            )
        )
        else None,
    }
    if rows and any(r["status"] in ["pending", "running"] for r in rows):
        dimensions["stability"] = None
    applicable = {
        k: w for k, w in weights.items() if dimensions[k] is not None and w > 0
    }
    total_weight = sum(applicable.values())
    effective = (
        {k: round(w / total_weight, 8) for k, w in applicable.items()}
        if total_weight
        else {}
    )
    score = (
        round(sum(dimensions[k] * w for k, w in effective.items()), 2)
        if effective
        else None
    )
    times = [r["duration_ms"] for r in rows if r["duration_ms"] is not None]
    known_tokens = [
        r["usage"].get("total_tokens")
        for r in rows
        if isinstance(r.get("usage", {}).get("total_tokens"), int)
    ]
    expected_tools = {r["case"]["rules"].get("expected_tool") for r in rows} - {
        None,
        "",
    }
    observed_tools = {
        e["event_name"]
        for r in rows
        for e in r["events"]
        if e["event_type"] in ["tool_call", "tool_result"]
    }
    observed_types = sorted({e["event_type"] for r in rows for e in r["events"]})
    coverage_dimensions = []
    for label, types, kinds in [
        ("planning", {"planning"}, {"plan", "planning"}),
        (
            "memory",
            {"memory"},
            {"memory_read", "memory_write", "memory_update", "memory_forget"},
        ),
        ("rag", {"rag"}, {"retrieval", "rag_retrieval", "knowledge_search"}),
        ("exception", {"exception"}, {"exception", "retry"}),
        ("security", {"security"}, {"evaluation"}),
    ]:
        planned = [r for r in rows if r["test_type"] in types]
        observed = [
            r
            for r in planned
            if any(
                e["event_type"] in kinds or e["event_name"] in kinds
                for e in r["events"]
            )
        ]
        coverage_dimensions.append(
            {
                "dimension": label,
                "planned_cases": len(planned),
                "observed_cases": len(observed),
                "rate": len(observed) / len(planned) if planned else None,
            }
        )
    parameter_cases = [
        r
        for r in rows
        if r["case"]["rules"].get("expected_tool")
        and r["case"]["rules"].get("expected_arguments")
    ]
    matching_parameters = [
        r
        for r in parameter_cases
        if any(
            e["event_type"] in ["tool_call", "tool_result"]
            and e["event_name"] == r["case"]["rules"]["expected_tool"]
            and all(
                e["data"].get("arguments", {}).get(k) == v
                for k, v in r["case"]["rules"]["expected_arguments"].items()
            )
            for e in r["events"]
        )
    ]
    coverage_dimensions.extend(
        [
            {
                "dimension": "tool",
                "planned_tools": len(expected_tools),
                "observed_tools": len(expected_tools & observed_tools),
                "rate": len(expected_tools & observed_tools) / len(expected_tools)
                if expected_tools
                else None,
            },
            {
                "dimension": "parameters",
                "planned_cases": len(parameter_cases),
                "observed_cases": len(matching_parameters),
                "rate": len(matching_parameters) / len(parameter_cases)
                if parameter_cases
                else None,
            },
        ]
    )
    return {
        "total": n,
        "counts": dict(counts),
        "pass_rate": counts["passed"] / n if n else None,
        "by_type": by_type,
        "dimensions": dimensions,
        "weights": weights,
        "effective_weights": effective,
        "score": score,
        "missing_dimensions": [k for k, v in dimensions.items() if v is None],
        "evaluation_coverage": {
            "judged_results": sum(r["status"] in ["passed", "failed"] for r in rows),
            "unknown_results": counts["inconclusive"],
            "cancelled_results": counts["cancelled"],
            "note": "仅对已观测指标评分；少量可评估样本的高分不代表全部能力通过",
        },
        "score_rule": "有效评估器分数按维度平均；缺失维度剔除并归一化。稳定性=1-执行异常率；未知与取消不算通过。",
        "performance": {
            "average_ms": mean(times),
            "p95_ms": float(np.percentile(times, 95)) if times else None,
            "maximum_ms": max(times) if times else None,
            "error_rate": counts["error"] / n if n else None,
            "total_tokens": sum(known_tokens) if known_tokens else None,
            "token_samples": len(known_tokens),
        },
        "risk_warning": any(
            f["risk"] in ["high", "critical"] and f["violated"] == "yes"
            for f in findings
        ),
        "findings": findings,
        "defects": [
            {"result_id": r["id"], "case_key": r["case_key"], **cause}
            for r in rows
            if (cause := diagnostics(r))
        ],
        "coverage": {
            "dimensions": coverage_dimensions,
            "expected_tools": sorted(expected_tools),
            "observed_tools": sorted(observed_tools),
            "tool_coverage": len(expected_tools & observed_tools) / len(expected_tools)
            if expected_tools
            else None,
            "event_types": observed_types,
            "note": "分母为任务声明的用例/工具，安全维度仅表示执行评估事件被采集，不表示安全通过。平台定义的可观测行为覆盖，未观测不能证明未执行，不代表模型内部路径覆盖",
        },
    }


def build_report(db, app, task, weights):
    if task.status not in TERMINAL:
        raise HTTPException(409, "请等待任务结束后生成报告")
    rows = results_for(db, app, task)
    findings = [
        {
            k: getattr(f, k)
            for k in ["id", "result_id", "category", "risk", "violated", "detail"]
        }
        for f in db.scalars(
            select(SecurityFinding).where(SecurityFinding.task_id == task.id)
        )
    ]
    return {
        "task": {
            "id": task.id,
            "name": task.name,
            "status": task.status,
            "kind": task.kind,
            "snapshot": task.snapshot,
            "config": task.config,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
        },
        "summary": summarize(rows, weights, findings),
        "results": rows,
    }


def compare_tasks(db, app, baseline, candidate):
    if (
        baseline.id == candidate.id
        or baseline.agent_id != candidate.agent_id
        or baseline.suite_id != candidate.suite_id
        or baseline.project_id != candidate.project_id
        or baseline.kind != candidate.kind
    ):
        raise HTTPException(422, "需选择同项目、同 Agent、同套件、同类型的两个不同任务")
    if baseline.status not in TERMINAL or candidate.status not in TERMINAL:
        raise HTTPException(409, "对比任务必须结束")
    left = {r["case_key"]: r for r in results_for(db, app, baseline)}
    right = {r["case_key"]: r for r in results_for(db, app, candidate)}
    shared = left.keys() & right.keys()
    if not shared:
        raise HTTPException(422, "没有同源用例可比较")
    pairs = []
    for key in sorted(shared):
        a, b = left[key], right[key]
        changed = a["case"] != b["case"]
        transition = (
            "modified"
            if changed
            else "regressed"
            if a["status"] == "passed" and b["status"] != "passed"
            else "fixed"
            if a["status"] != "passed" and b["status"] == "passed"
            else "unchanged"
        )
        pairs.append(
            {
                "case_key": key,
                "name": b["name"],
                "baseline_result_id": a["id"],
                "candidate_result_id": b["id"],
                "transition": transition,
                "case_modified": changed,
                "baseline_status": a["status"],
                "candidate_status": b["status"],
                "baseline_output": a.get("output"),
                "candidate_output": b.get("output"),
                "latency_delta_ms": b["duration_ms"] - a["duration_ms"]
                if a["duration_ms"] is not None and b["duration_ms"] is not None
                else None,
                "baseline_evaluations": a["evaluations"],
                "candidate_evaluations": b["evaluations"],
            }
        )
    comparable = [p for p in pairs if not p["case_modified"]]
    weights = {
        "functional": 25,
        "behavior": 20,
        "rag": 20,
        "security": 20,
        "stability": 15,
    }
    metrics = {
        side: summarize([source[p["case_key"]] for p in comparable], weights, [])
        for side, source in [("baseline", left), ("candidate", right)]
    }
    return {
        "baseline_metrics": metrics["baseline"],
        "candidate_metrics": metrics["candidate"],
        "baseline_id": baseline.id,
        "candidate_id": candidate.id,
        "agent_versions": [
            baseline.snapshot["agent"]["version"],
            candidate.snapshot["agent"]["version"],
        ],
        "suite_revisions": [
            baseline.snapshot["suite_revision"],
            candidate.snapshot["suite_revision"],
        ],
        "pairs": pairs,
        "added_cases": sorted(right.keys() - left.keys()),
        "removed_cases": sorted(left.keys() - right.keys()),
        "comparable_count": len(comparable),
        "new_failures": [
            p["case_key"] for p in comparable if p["transition"] == "regressed"
        ],
        "fixed_cases": [
            p["case_key"] for p in comparable if p["transition"] == "fixed"
        ],
        "baseline_pass_rate": mean(
            [float(p["baseline_status"] == "passed") for p in comparable]
        ),
        "candidate_pass_rate": mean(
            [float(p["candidate_status"] == "passed") for p in comparable]
        ),
        "note": "修改过的用例单列，不算作同条件退化；延迟单次变化不构成统计显著性；安全风险详见各任务报告",
    }
