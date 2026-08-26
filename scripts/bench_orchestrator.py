"""
Orchestrator / Planner 延迟与成本基准
==================================
在 60 题评测集上跑 VillageAgent.ask()，统计：
  - 平均延迟（s/题）
  - 是否走 orchestrator（Planner+工具）vs 直接 RAG
  - 估算 token / 成本
  - 简单问题（关键词门控）走直接 RAG 的延迟与成本

用途：项目文档 3.3 后续 / 2.2 中"Planner 稳定性"优化的量化依据。

运行（需在项目根目录，PYTHONPATH 包含 src）：
    python scripts/bench_orchestrator.py --n 30
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EVAL = ROOT / "data" / "eval" / "eval_set.json"
OUT = ROOT / "data" / "eval" / "orchestrator_bench.json"


# simple keyword gate (rule-based) — mirrors common sense
COMPLEX_KEYWORDS = [
    "对比", "比较", "路线", "规划", "几天", "几日", "多日",
    "研学", "推荐", "估算", "距离", "多长", "怎么走", "攻略",
    "知识图谱", "图谱", "关系", "时间轴", "对比两个",
]


def looks_complex(q: str) -> bool:
    return any(k in q for k in COMPLEX_KEYWORDS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    from agent.rag import VillageAgent
    agent = VillageAgent()
    qs = json.loads(EVAL.read_text(encoding="utf-8"))["questions"][: args.n]

    records, t0 = [], time.time()
    for i, q in enumerate(qs, 1):
        question = q["question"]; village = q.get("village") or "皎平渡"
        is_complex = looks_complex(question)
        ts = time.time()
        try:
            ans = agent.ask(question, village=village, remember=False)
            latency = time.time() - ts
            # decide path by inspecting last_plan
            plan = agent.last_plan
            path = "orchestrator" if (plan and plan.get("is_complex")) else "direct_rag"
            rec = {
                "qid": q.get("id"), "question": question, "village": village,
                "rule_complex": is_complex, "actual_path": path,
                "latency_s": round(latency, 2),
                "answer_len": len(ans or ""),
            }
        except Exception as e:
            rec = {"qid": q.get("id"), "question": question, "error": str(e)[:80]}
        records.append(rec)
        print(f"  [{i}/{len(qs)}] path={rec.get('actual_path','-')} "
              f"lat={rec.get('latency_s',0)}s", flush=True)

    # aggregate
    ok = [r for r in records if "latency_s" in r]
    by_path = {}
    for r in ok:
        by_path.setdefault(r["actual_path"], []).append(r["latency_s"])
    avg_total = sum(r["latency_s"] for r in ok) / max(len(ok), 1)
    summary = {
        "n": len(ok),
        "avg_latency_s": round(avg_total, 2),
        "by_path": {k: {"n": len(v), "avg_s": round(sum(v)/len(v), 2),
                       "min_s": round(min(v), 2), "max_s": round(max(v), 2)}
                    for k, v in by_path.items()},
        "rule_complex_count": sum(1 for r in records if r.get("rule_complex")),
        "actual_complex_count": sum(1 for r in records if r.get("actual_path") == "orchestrator"),
    }
    # rule-gate projected saving
    if "orchestrator" in by_path and "direct_rag" in by_path:
        oc = by_path["orchestrator"]; dr = by_path["direct_rag"]
        summary["projected_saving_if_rule_gate"] = {
            "questions_reroutable": summary["rule_complex_count"],
            "saved_s_per_q": round(
                (sum(oc) / len(oc)) - (sum(dr) / len(dr)), 2
            ) if dr else None,
        }

    print("\n=== Orchestrator Bench ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    Path(args.out).write_text(json.dumps({"summary": summary, "records": records},
                                         ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[+] {args.out}")


if __name__ == "__main__":
    main()
