from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bench import Result, load_questions, metrics_from_response, summarize, write_blind_sheet  # noqa: E402

ROOT = Path(__file__).parent.parent


def test_metrics_conversion():
    m = metrics_from_response(
        {
            "eval_count": 100,
            "eval_duration": 4_000_000_000,
            "prompt_eval_count": 50,
            "prompt_eval_duration": 500_000_000,
            "load_duration": 100_000_000,
            "total_duration": 4_700_000_000,
        }
    )
    assert m == {"gen_tok_s": 25.0, "prefill_tok_s": 100.0, "ttft_s": 0.6, "total_s": 4.7, "output_tokens": 100}


def test_metrics_with_missing_fields():
    assert metrics_from_response({})["gen_tok_s"] == 0.0


def test_question_sets_are_complete_and_unique():
    qs = load_questions([str(ROOT / "eval/questions_pl.jsonl"), str(ROOT / "eval/questions_en.jsonl")])
    ids = [q["id"] for q in qs]
    assert len(ids) == len(set(ids)) == 100
    assert sum(q["lang"] == "pl" for q in qs) == 50
    assert all(q["prompt"].strip() and q["category"] for q in qs)


def _r(model, qid, tok):
    return Result(model, qid, "pl", "fakty", tok, 100.0, 0.5, 2.0, 50, f"odp {model}")


def test_summary_and_blind_sheet_hide_model_names(tmp_path):
    results = [_r("qwen", "pl-01", 20.0), _r("bielik", "pl-01", 25.0)]
    assert "| bielik | pl | 25.0 |" in summarize(results)
    key = write_blind_sheet(results, tmp_path / "blind.csv", random.Random(1))
    rows = list(csv.DictReader((tmp_path / "blind.csv").open()))
    assert {r["label"] for r in rows} == set(key.values())
    assert all("qwen" not in r["label"] and "bielik" not in r["label"] for r in rows)
