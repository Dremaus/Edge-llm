#!/usr/bin/env python3
"""Benchmark modeli na urządzeniu — tydzień testów (Ryzen AI: Qwen vs Bielik vs Gemma).

Mierzy z natywnych liczników Ollamy (/api/chat):
- prędkość generowania (tok/s) = eval_count / eval_duration,
- czas do pierwszego tokenu (TTFT) ≈ load_duration + prompt_eval_duration,
- prędkość przetwarzania promptu (prefill tok/s),
- zajętość pamięci systemu przed/po.

Wyniki: CSV z pomiarami + arkusz do ślepej oceny jakości (modele pod losowymi literami)
+ podsumowanie w Markdown. Tylko biblioteka standardowa — działa na czystym urządzeniu.

Użycie:
    python3 tools/bench.py --models qwen3.5:4b,hf.co/speakleash/Bielik-4.5B-v3.0-Instruct-GGUF:Q8_0 \
        --questions eval/questions_pl.jsonl eval/questions_en.jsonl --out results/ryzen-ai
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import random
import statistics
import string
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434"


@dataclass
class Result:
    model: str
    question_id: str
    lang: str
    category: str
    gen_tok_s: float
    prefill_tok_s: float
    ttft_s: float
    total_s: float
    output_tokens: int
    answer: str


def metrics_from_response(resp: dict) -> dict[str, float]:
    """Przelicza nanosekundowe liczniki Ollamy na tok/s i sekundy."""
    ns = 1e9
    eval_count = resp.get("eval_count", 0) or 0
    eval_dur = resp.get("eval_duration", 0) or 0
    prompt_count = resp.get("prompt_eval_count", 0) or 0
    prompt_dur = resp.get("prompt_eval_duration", 0) or 0
    load_dur = resp.get("load_duration", 0) or 0
    return {
        "gen_tok_s": round(eval_count / (eval_dur / ns), 2) if eval_dur else 0.0,
        "prefill_tok_s": round(prompt_count / (prompt_dur / ns), 2) if prompt_dur else 0.0,
        "ttft_s": round((load_dur + prompt_dur) / ns, 3),
        "total_s": round((resp.get("total_duration", 0) or 0) / ns, 3),
        "output_tokens": int(eval_count),
    }


def load_questions(paths: list[str]) -> list[dict]:
    questions = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                questions.append(json.loads(line))
    return questions


def read_mem_available_mb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def chat(model: str, prompt: str, max_tokens: int, timeout: float) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.2, "seed": 42},
    }
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (localhost)
        return json.loads(resp.read())


def summarize(results: list[Result]) -> str:
    lines = [
        "| Model | Język | Prędkość (tok/s, mediana) | TTFT (s, mediana) | Prefill (tok/s) | Pytań |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    keys = sorted({(r.model, r.lang) for r in results})
    for model, lang in keys:
        rows = [r for r in results if r.model == model and r.lang == lang and r.gen_tok_s > 0]
        if not rows:
            continue
        lines.append(
            f"| {model} | {lang} | {statistics.median(r.gen_tok_s for r in rows):.1f} | "
            f"{statistics.median(r.ttft_s for r in rows):.2f} | "
            f"{statistics.median(r.prefill_tok_s for r in rows):.0f} | {len(rows)} |"
        )
    return "\n".join(lines)


def write_blind_sheet(results: list[Result], path: Path, rng: random.Random) -> dict[str, str]:
    """Arkusz do ślepej oceny: modele ukryte pod literami, kolejność odpowiedzi losowa."""
    models = sorted({r.model for r in results})
    letters = list(string.ascii_uppercase[: len(models)])
    rng.shuffle(letters)
    key = dict(zip(models, letters, strict=True))
    rows = [
        {"question_id": r.question_id, "lang": r.lang, "label": key[r.model], "answer": r.answer, "score_1_5": ""}
        for r in results
    ]
    rng.shuffle(rows)
    rows.sort(key=lambda row: row["question_id"])
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return key


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", required=True, help="lista modeli rozdzielona przecinkami")
    ap.add_argument("--questions", nargs="+", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--limit", type=int, default=0, help="tylko N pierwszych pytań (szybki test)")
    ap.add_argument("--timeout", type=float, default=300)
    args = ap.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    questions = load_questions(args.questions)
    if args.limit:
        questions = questions[: args.limit]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    results: list[Result] = []
    mem_log = []
    for model in models:
        before = read_mem_available_mb()
        print(f"== {model}: rozgrzewka", flush=True)
        chat(model, "OK", 4, args.timeout)  # ładowanie modelu poza pomiarem
        after = read_mem_available_mb()
        mem_log.append({"model": model, "mem_available_before_mb": before, "mem_available_loaded_mb": after})
        for i, q in enumerate(questions, 1):
            try:
                resp = chat(model, q["prompt"], args.max_tokens, args.timeout)
            except Exception as exc:  # pomiar ma iść dalej mimo pojedynczych błędów
                print(f"  [{i}/{len(questions)}] {q['id']}: błąd {type(exc).__name__}", flush=True)
                continue
            m = metrics_from_response(resp)
            answer = resp.get("message", {}).get("content", "")
            results.append(Result(model, q["id"], q["lang"], q.get("category", ""), answer=answer, **m))
            print(f"  [{i}/{len(questions)}] {q['id']}: {m['gen_tok_s']} tok/s, TTFT {m['ttft_s']} s", flush=True)

    if not results:
        print("Brak wyników.", file=sys.stderr)
        return 1

    with (out / "measurements.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(results[0])))
        writer.writeheader()
        writer.writerows(asdict(r) for r in results)
    key = write_blind_sheet(results, out / "blind_rating.csv", random.Random(int(time.time())))
    (out / "blind_key.json").write_text(json.dumps(key, indent=2))  # nie pokazywać oceniającym
    summary = (
        f"# Wyniki benchmarku\n\nPlatforma: {platform.machine()} · {platform.platform()}\n"
        f"Data: {time.strftime('%Y-%m-%d %H:%M')}\n\n{summarize(results)}\n\n"
        f"## Pamięć\n\n```json\n{json.dumps(mem_log, indent=2)}\n```\n"
    )
    (out / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)
    print(f"Zapisano: {out}/measurements.csv, blind_rating.csv (do oceny), blind_key.json (klucz)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
