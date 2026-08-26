"""
事实校验 (FactChecker) 量化评测
==============================
把"85% 不是真概率正确"变成可量化指标。

方法：构造正/负样本对，跑 FactChecker，统计：
  - TPR (召回)：在负样本（人为植入错事实）上，FactChecker 是否抓到 high-severity issue
  - FPR (误报)：在正样本（真实回答）上，是否误报 high-severity issue
  - Confidence calibration：reported confidence vs 实际正确率

负样本构造：从真实回答中注入一个明确错误的史实（"刘伯承出生于1900年"等
可判定为"档案未记载/错误"的事实），使 ground truth = "该被标记"。
正样本 = 真实回答不变。

运行：
    python scripts/eval_factcheck.py
    python scripts/eval_factcheck.py --n 15
"""
from __future__ import annotations
import argparse, json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EVAL = ROOT / "data" / "eval" / "eval_set.json"
OUT_JSON = ROOT / "data" / "eval" / "factcheck_eval.json"
OUT_MD = ROOT / "data" / "eval" / "factcheck_eval.md"

# Plausible-but-wrong claims to inject (we pick the first one for each negative case).
# These are all NOT in the project's archival ground truth.
PLANTED_CLAIMS = [
    "（提示：据某来源记载，刘伯承出生于1900年。）",
    "（补充：红军在皎平渡动用了大型机动渡轮。）",
    "（注：扎西会议于1936年2月在云南威信召开。）",
    "（据传，中央红军长征总路程约为4万里。）",
    "（记录：红二、六军团于1935年与中央红军在云南会师。）",
    "（考证：巧渡金沙江发生于1935年6月3日至9日。）",
    "（载：石鼓渡江时使用的船只达三十余条。）",
    "（言：万急渡江令由毛泽东在丹桂村亲笔起草。）",
    "（提：柯渡红军总部驻扎时间约一个月。）",
    "（述：寻甸战役歼敌约两万余人。）",
    "（云：红军长征过云南历时整整一年。）",
    "（说：宣威战斗由贺龙元帅亲自指挥。）",
    "（记：楚雄红军曾占领当地机场。）",
    "（闻：丽江古城在长征期间被红军完整保护。）",
    "（述：曲靖是中央红军与红二方面军的会师地点。）",
]


def has_high_issue(verification: dict) -> bool:
    issues = verification.get("issues") or []
    return any(isinstance(i, dict) and i.get("severity") == "high" for i in issues)


def extract_confidence(verification: dict):
    c = verification.get("confidence")
    try:
        return float(c) if c is not None else None
    except Exception:
        return None


def calibrate_bucket(confidences: list, labels: list, n_bins: int = 5):
    """分桶计算 calibration: 每个 bin 内的 mean(confidence) vs accuracy."""
    bins = [[] for _ in range(n_bins)]
    for c, lab in zip(confidences, labels):
        if c is None:
            continue
        b = min(int(c * n_bins), n_bins - 1)
        bins[b].append((c, lab))
    out = []
    for i, b in enumerate(bins):
        if not b:
            continue
        mc = sum(x[0] for x in b) / len(b)
        acc = sum(x[1] for x in b) / len(b)
        out.append({"bin": f"[{i/n_bins:.1f},{(i+1)/n_bins:.1f})", "n": len(b),
                    "mean_conf": round(mc, 3), "accuracy": round(acc, 3),
                    "gap": round(mc - acc, 3)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="正/负样本对数")
    ap.add_argument("--limit-eval", type=int, default=0)
    args = ap.parse_args()

    from agent.rag import VillageAgent
    agent = VillageAgent()

    qs = json.loads(EVAL.read_text(encoding="utf-8"))["questions"]
    if args.limit_eval:
        qs = qs[: args.limit_eval]
    qs = qs[: args.n]
    print(f"[*] evaluating FactChecker on {len(qs)} positive + {len(qs)} negative = {2*len(qs)} cases")

    pos_records, neg_records = [], []
    t0 = time.time()
    for i, q in enumerate(qs, 1):
        question = q["question"]
        village = q.get("village") or "皎平渡"
        print(f"  [{i}/{len(qs)}] {question[:30]}… ", end="", flush=True)
        # RAG to get a real answer + evidence
        try:
            ans = agent.ask(question, village=village, remember=False)
            evidence_text = ""
            if agent.last_evidence:
                evidence_text = "\n".join((e.get("text", "") if isinstance(e, dict) else str(e))[:600]
                                          for e in agent.last_evidence[:5])
        except Exception as e:
            print(f"RAG fail: {e}")
            continue

        # positive
        try:
            v_pos = agent.fact_checker.verify(question, ans, evidence_text)
            pos_records.append({
                "qid": q.get("id"), "question": question,
                "answer": ans, "verification": v_pos,
                "gt_has_high_issue": False,
            })
        except Exception as e:
            pos_records.append({"qid": q.get("id"), "error": str(e), "gt_has_high_issue": False})

        # negative: inject a planted (wrong) claim
        planted = PLANTED_CLAIMS[(i - 1) % len(PLANTED_CLAIMS)]
        ans_neg = ans + " " + planted
        try:
            v_neg = agent.fact_checker.verify(question, ans_neg, evidence_text)
            neg_records.append({
                "qid": q.get("id"), "question": question,
                "answer": ans_neg, "planted": planted,
                "verification": v_neg,
                "gt_has_high_issue": True,
            })
        except Exception as e:
            neg_records.append({"qid": q.get("id"), "error": str(e), "gt_has_high_issue": True})
        print(f"ok ({time.time()-t0:.0f}s elapsed)")

    # Metrics
    def metrics(records, gt_key="gt_has_high_issue"):
        n = len(records)
        pred_high = [has_high_issue(r.get("verification", {})) for r in records]
        gt = [r.get(gt_key, False) for r in records]
        tp = sum(p and g for p, g in zip(pred_high, gt))
        fp = sum(p and not g for p, g in zip(pred_high, gt))
        fn = sum(not p and g for p, g in zip(pred_high, gt))
        tn = sum(not p and not g for p, g in zip(pred_high, gt))
        prec = tp / (tp + fp) if tp + fp else 0
        rec = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        acc = (tp + tn) / n if n else 0
        confs = [extract_confidence(r.get("verification", {})) for r in records]
        return {
            "n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(f1, 3), "accuracy": round(acc, 3),
            "confs": [c for c in confs if c is not None],
        }

    pos_m = metrics(pos_records)
    neg_m = metrics(neg_records)

    # combined: positive label=0 (no issue), negative label=1 (should flag)
    all_confs, all_labels = [], []
    for r in pos_records:
        c = extract_confidence(r.get("verification", {}))
        if c is not None:
            all_confs.append(c); all_labels.append(1 if has_high_issue(r.get("verification", {})) else 0)
    for r in neg_records:
        c = extract_confidence(r.get("verification", {}))
        if c is not None:
            all_confs.append(c); all_labels.append(1 if has_high_issue(r.get("verification", {})) else 0)
    cal = calibrate_bucket(all_confs, all_labels, n_bins=5)

    # Report
    print("\n=== FactChecker Evaluation ===")
    print(f"positive (clean) : n={pos_m['n']}  FPR={pos_m['fp']}/{pos_m['n']}={pos_m['fp']/max(pos_m['n'],1):.0%}")
    print(f"negative (planted): n={neg_m['n']}  TPR={neg_m['tp']}/{neg_m['n']}={neg_m['tp']/max(neg_m['n'],1):.0%}")
    print(f"overall: precision={pos_m['precision'] if False else (pos_m['tp']+neg_m['tp'])/max(pos_m['tp']+neg_m['tp']+pos_m['fp']+neg_m['fp'],1):.2f} "
          f"recall={neg_m['recall']:.2f}  acc={(pos_m['tp']+pos_m['tn']+neg_m['tp']+neg_m['tn'])/max(2*pos_m['n'],1):.2f}")

    md = ["# 事实校验量化评测\n",
          f"> {len(qs)} 正/负样本对（共 {2*len(qs)} 次 FactChecker 调用）\n",
          "| 类别 | n | TP/FP/FN/TN | Precision | Recall | F1 | Accuracy |",
          "|---|---:|---|---:|---:|---:|---:|",
          f"| 正样本 (clean) | {pos_m['n']} | {pos_m['tp']}/{pos_m['fp']}/{pos_m['fn']}/{pos_m['tn']} | — | — | — | {(pos_m['tn']+pos_m['fp']==0) and 0 or (pos_m['tn']/(pos_m['tn']+pos_m['fp'])):.2f} |",
          f"| 负样本 (planted) | {neg_m['n']} | {neg_m['tp']}/{neg_m['fp']}/{neg_m['fn']}/{neg_m['tn']} | — | {neg_m['recall']} | {neg_m['f1']} | — |",
          "",
          "**核心指标**：",
          f"- **TPR（负样本召回率）= {neg_m['tp']}/{neg_m['n']} = {neg_m['tp']/max(neg_m['n'],1):.0%}** — 植入错事实后 FactChecker 抓到的比例",
          f"- **FPR（正样本误报率）= {pos_m['fp']}/{pos_m['n']} = {pos_m['fp']/max(pos_m['n'],1):.0%}** — 真实回答被误报为有 high-severity issue 的比例",
          "",
          "**置信度校准 (Calibration)**：",
          "| bin | n | mean_conf | accuracy | gap |",
          "|---|---:|---:|---:|---:|"]
    for c in cal:
        md.append(f"| {c['bin']} | {c['n']} | {c['mean_conf']} | {c['accuracy']} | {c['gap']:+} |")
    md += ["",
           "gap > 0 表示 FactChecker 高估了正确率（自信但其实有问题），"
           "gap < 0 表示低估（保守）。理想是 |gap| 接近 0。",
           "",
           "*可写入项目文档 3.2 / 2.2 支撑「事实校验」从软指标变为可量化。*"]

    OUT_JSON.write_text(json.dumps({
        "positive": pos_m, "negative": neg_m,
        "calibration": cal,
        "positive_records": pos_records,
        "negative_records": neg_records,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\n[+] {OUT_JSON}\n[+] {OUT_MD}")


if __name__ == "__main__":
    main()
