"""LLM cache + cost tests (offline).

Covers the stable session id, the x-session-id header on the AGNO model, usage
extraction with cached tokens and the cost estimate with cache discount.

    python tests/test_llm_costing.py
"""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp = tempfile.mkdtemp(prefix="wb_costing_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"

from agent.costing import estimate_cost  # noqa: E402
from db.connection import init_db  # noqa: E402

passed = 0
failed = 0

def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK {name}")
    else:
        failed += 1
        print(f"  FAIL {name}" + (f" -> {detail}" if detail else ""))

def section(title: str) -> None:
    print("\n" + "-" * 60)
    print(f"  {title}")
    print("-" * 60)

def close(a: float, b: float) -> bool:
    return abs(a - b) < 1e-9

init_db()

# ── estimate_cost ──────────────────────────────────────────────────────
section("estimate_cost")
P = {"prompt": "0.0000003", "completion": "0.0000012", "input_cache_read": "0.000000006"}

cost, saved = estimate_cost(P, 24021, 20, 23936)
check("com cache: ~US$0,00019", abs(cost - 0.000193) < 1e-5, str(cost))
check("economia ~US$0,00704", abs(saved - 0.00704) < 1e-5, str(saved))

cost, saved = estimate_cost(P, 24021, 20, 0)
check("sem cache: preço cheio (~0,00723)", abs(cost - 0.007230) < 1e-5, str(cost))
check("sem cache: economia zero", close(saved, 0.0))

cost, saved = estimate_cost(P, 1000, 0, 1000)
check("100% cache: só preço de cache", close(cost, 1000 * 0.000000006), str(cost))

cost, saved = estimate_cost({"prompt": "0.0000003", "completion": "0.0000012"}, 1000, 10, 900)
check("sem preço de cache: sem desconto", close(cost, 1000 * 0.0000003 + 10 * 0.0000012) and close(saved, 0.0))

cost, _ = estimate_cost(P, 100, 0, 5000)
check("cached > prompt é limitado ao prompt", close(cost, 100 * 0.000000006), str(cost))

check("sem preço: zero", estimate_cost({}, 100, 10, 50) == (0.0, 0.0))
check("None nos tokens não quebra", estimate_cost(P, None, None, None) == (0.0, 0.0))

PW = {**P, "overrides": [{"utc_start": 0, "utc_end": 600, "prompt": "0.0000001"}]}
c_in, _ = estimate_cost(PW, 1000, 0, 0, now=datetime(2026, 9, 16, 2, 0, tzinfo=timezone.utc))
c_out, _ = estimate_cost(PW, 1000, 0, 0, now=datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc))
check("janela de horário aplica o preço do override", close(c_in, 1000 * 0.0000001) and close(c_out, 1000 * 0.0000003))

# ── session id ─────────────────────────────────────────────────────────
section("session id estável")
import config.settings as cs  # noqa: E402

sid1 = cs.get_llm_session_id()
sid2 = cs.get_llm_session_id()
check("formato wb-<hex>", sid1.startswith("wb-") and len(sid1) == 35, sid1)
check("igual em chamadas seguidas", sid1 == sid2)
cs._llm_session_id_cache = ""  # simula reinício do app
check("igual após reinício (vem do banco)", cs.get_llm_session_id() == sid1)
check("não está em allowed_keys do PUT /api/config",
      "llm_session_id" not in open(Path(__file__).resolve().parent.parent / "server/routes/config.py").read().split("allowed_keys")[1][:1500])

# ── header no modelo ───────────────────────────────────────────────────
section("build_model envia x-session-id")
from agent import agno_engine  # noqa: E402

handler = SimpleNamespace(api_key="sk-test", model="deepseek/deepseek-v4.1-flash")
model = agno_engine.build_model(handler)
check("extra_headers com o id", (model.extra_headers or {}).get("x-session-id") == sid1, str(model.extra_headers))
check("mesmo id em dois modelos", agno_engine.build_model(handler).extra_headers == model.extra_headers)
check("o header chega nos parâmetros da requisição",
      (model.get_request_params() or {}).get("extra_headers", {}).get("x-session-id") == sid1)

# ── _extract_usage ─────────────────────────────────────────────────────
section("_extract_usage")
out = SimpleNamespace(metrics=SimpleNamespace(input_tokens=24021, output_tokens=20,
                                              total_tokens=24041, cache_read_tokens=23936))
u = agno_engine._extract_usage(out)
check("inclui cached_tokens", u and u["cached_tokens"] == 23936, str(u))
out2 = SimpleNamespace(metrics=SimpleNamespace(input_tokens=10, output_tokens=2, total_tokens=12))
check("sem campo de cache vira 0", agno_engine._extract_usage(out2)["cached_tokens"] == 0)
check("sem métricas: None", agno_engine._extract_usage(SimpleNamespace(metrics=None)) is None)

# ── repositório ────────────────────────────────────────────────────────
section("usage_repo")
from db.repositories import contact_repo, usage_repo  # noqa: E402

c = contact_repo.get_or_create("5511999990099", "Teste")
usage_repo.add(c["id"], "text", "m", 100, 10, 110, 0.001)  # antigo: não medido
usage_repo.add(c["id"], "text", "m", 1000, 10, 1010, 0.002, cached_tokens=800, saved_usd=0.0005)
usage_repo.add(c["id"], "text", "m", 1000, 10, 1010, 0.003, cached_tokens=0, saved_usd=0.0)
g = usage_repo.global_summary()
check("soma de cache só das linhas medidas", g["cached_tokens"] == 800, str(g))
check("denominador ignora linhas antigas", g["cache_measured_prompt_tokens"] == 2000, str(g))
check("saved_usd somado", close(g["saved_usd"], 0.0005))
check("by_type traz os campos de cache", g["by_type"]["text"]["cached_tokens"] == 800)
bc = usage_repo.by_contact()
check("by_contact traz os campos de cache", bc and bc[0]["cached_tokens"] == 800 and bc[0]["call_count"] == 3)
d = usage_repo.detail(c["id"])
check("detail: NULL nas antigas, valor nas novas",
      d[0]["cached_tokens"] is None and d[1]["cached_tokens"] == 800 and d[2]["cached_tokens"] == 0, str(d))

print("\n" + "=" * 60)
print(f"  {passed} passaram, {failed} falharam")
print("=" * 60)
sys.exit(1 if failed else 0)
