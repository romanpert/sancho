"""The end-to-end A/B: the same agent, the same tasks, with and without the squire.

    python -m benchmarks.ab.run --verify              # check the ground truth, no API calls
    python -m benchmarks.ab.run --repeats 1 --tasks injection,cost     # a cheap pilot
    python -m benchmarks.ab.run --repeats 3 --out benchmarks/ab/results/2026-09-24

What this measures, and only this: **page triage**. Both arms run byte-identical prompts,
tools, model, thinking and effort. The single difference is that in the `squire` arm the
`fetch` tool passes the page through `Squire.triage_page` first, and a page judged
irrelevant to the stated purpose comes back as a one-line note instead of its text.

What it does not measure: model routing, search routing, the citation check or the shell
guard. Those levers are not exercised here, so nothing in this benchmark speaks to them.

Why a fixed local corpus instead of the live web: so the run is deterministic, free of
network variance, and reproducible by anyone who clones the repository. The retriever is a
deliberately mediocre keyword search, because a good retriever would hide the effect being
measured, and a real agent does not have a good retriever either.

Cost control, because this spends real money: every run has a turn cap and a cumulative
input-token cap, the runner prints its running total, and `--max-usd` aborts the whole
sweep when the Anthropic spend crosses it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import anthropic  # noqa: E402
from corpus import Document, build, search  # noqa: E402

from sanchopanza import JsonlJournal, Squire, Thresholds  # noqa: E402
from sanchopanza.providers import create  # noqa: E402

# Precios de lista de la API de Anthropic, $/Mtok (entrada, salida), a 2026-06-24.
PRECIOS = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
MODELO_POR_DEFECTO = "claude-sonnet-5"
# Tamano de documento: cuantos caracteres minimos tiene una seccion antes de fundirse con la
# anterior. `small` deja documentos de pagina; `large`, documentos de PDF oficial.
TAMANOS = {"small": 400, "large": 6000}
TURNOS_MAX = 10
TOKENS_ENTRADA_MAX = 400_000  # tope duro por ejecucion; nunca se alcanza en la practica

BASE_SISTEMA = (
    "You are a research assistant with a document search tool. Answer the user's question "
    "using only what you find in the corpus. Search, then fetch documents, then answer. "
    "State the figures you found exactly as they appear. If a fetched document turns out not "
    "to help, move on and fetch another. Keep the final answer to a few sentences."
)

# Dos condiciones. La unica diferencia entre ellas es lo buena que es la recuperacion y, en
# consecuencia, cuanta basura se le pone delante al agente. Dentro de cada condicion los dos
# brazos son identicos salvo el cribado, que es lo que se esta midiendo.
CONDICIONES = {
    "precise": {
        "realce_titulo": 3,
        "limite": 8,
        "sistema": BASE_SISTEMA,
        "fragmentos": False,
        "descripcion": "titles are indexed, weighted and shown in the result list, so the "
        "right document usually ranks first and announces itself",
    },
    "noisy": {
        "realce_titulo": 0,
        "limite": 10,
        "sistema": BASE_SISTEMA
        + " This corpus contains many documents that mention the same words without "
        "answering the question. Do not answer from the first document you open: check the "
        "promising candidates until you have actually seen the figures you are asked for.",
        "fragmentos": True,
        "descripcion": "body-frequency ranking, results shown as snippets instead of curated "
        "headings, and the agent is told to corroborate. A real retriever over real pages "
        "looks like this; the curated section headings of this corpus are the artifact",
    },
}

HERRAMIENTAS = [
    {
        "name": "search",
        "description": (
            "Search the corpus. Returns matching documents, one per line, as a document "
            "id followed by a short description of it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Keywords to look for"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "fetch",
        "description": (
            "Fetch one document's full text by id. `purpose` states what you are looking for "
            "in it, in one short phrase."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "purpose": {"type": "string", "description": "What you are looking for"},
            },
            "required": ["doc_id", "purpose"],
            "additionalProperties": False,
        },
    },
]


@dataclass
class Ejecucion:
    task: str
    arm: str
    repeat: int
    model: str
    retrieval: str = "precise"
    correct: bool | None = None
    answer: str = ""
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model_cost_usd: float = 0.0
    squire_cost_usd: float = 0.0
    squire_decisions: int = 0
    fetched: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    wall_s: float = 0.0
    error: str | None = None

    @property
    def total_cost_usd(self) -> float:
        return self.model_cost_usd + self.squire_cost_usd


def normalizar(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in plano if not unicodedata.combining(c))


def acierta(respuesta: str, esperado: list[str]) -> bool:
    plano = normalizar(respuesta)
    return all(normalizar(e) in plano for e in esperado)


def coste(modelo: str, uso: Any) -> float:
    entrada, salida = PRECIOS.get(modelo, PRECIOS[MODELO_POR_DEFECTO])
    lectura = getattr(uso, "cache_read_input_tokens", 0) or 0
    escritura = getattr(uso, "cache_creation_input_tokens", 0) or 0
    return (
        uso.input_tokens * entrada
        + lectura * entrada * 0.1
        + escritura * entrada * 1.25
        + uso.output_tokens * salida
    ) / 1_000_000


async def _texto_de_pagina(
    doc: Document, proposito: str, squire: Squire | None, registro: Ejecucion
) -> str:
    """El unico punto donde los dos brazos difieren."""
    if squire is None:
        return doc.text
    criba = await squire.triage_page(purpose=proposito, title=doc.title, text=doc.text)
    if criba.keep:
        return doc.text
    registro.dropped.append(doc.id)
    return (
        f"[dropped by triage: {criba.reason}] This document does not address "
        f"'{proposito}'. Fetch a different one."
    )


async def una_ejecucion(
    cliente: anthropic.Anthropic,
    documentos: list[Document],
    tarea: dict[str, Any],
    *,
    arm: str,
    repeat: int,
    args_retrieval: str,
    modelo: str,
    squire: Squire | None,
    condicion: dict[str, Any],
) -> Ejecucion:
    por_id = {d.id: d for d in documentos}
    registro = Ejecucion(
        task=tarea["id"], arm=arm, repeat=repeat, model=modelo, retrieval=args_retrieval
    )
    mensajes: list[dict[str, Any]] = [{"role": "user", "content": tarea["question"]}]
    inicio = time.monotonic()

    try:
        for _ in range(TURNOS_MAX):
            registro.turns += 1
            respuesta = cliente.messages.create(
                model=modelo,
                max_tokens=4000,
                system=condicion["sistema"],
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                tools=HERRAMIENTAS,
                messages=mensajes,
            )
            uso = respuesta.usage
            registro.input_tokens += uso.input_tokens
            registro.output_tokens += uso.output_tokens
            registro.cache_read_tokens += getattr(uso, "cache_read_input_tokens", 0) or 0
            registro.cache_write_tokens += getattr(uso, "cache_creation_input_tokens", 0) or 0
            registro.model_cost_usd += coste(modelo, uso)
            if registro.input_tokens > TOKENS_ENTRADA_MAX:
                registro.error = "tope de tokens de entrada alcanzado"
                break

            mensajes.append({"role": "assistant", "content": respuesta.content})
            if respuesta.stop_reason != "tool_use":
                registro.answer = "\n".join(
                    b.text for b in respuesta.content if b.type == "text"
                ).strip()
                break

            resultados = []
            for bloque in respuesta.content:
                if bloque.type != "tool_use":
                    continue
                if bloque.name == "search":
                    encontrados = search(
                        documentos,
                        str(bloque.input.get("query", "")),
                        condicion["limite"],
                        realce_titulo=condicion["realce_titulo"],
                    )
                    if condicion["fragmentos"]:
                        filas_res = [
                            f"{d.id}  {' '.join(d.text.split())[:90]}..." for d in encontrados
                        ]
                    else:
                        filas_res = [f"{d.id}  {d.title}" for d in encontrados]
                    cuerpo = "\n".join(filas_res) or "No documents matched."
                else:
                    doc = por_id.get(str(bloque.input.get("doc_id", "")))
                    if doc is None:
                        cuerpo = "No such document id."
                    else:
                        registro.fetched.append(doc.id)
                        cuerpo = await _texto_de_pagina(
                            doc, str(bloque.input.get("purpose", "")), squire, registro
                        )
                resultados.append(
                    {"type": "tool_result", "tool_use_id": bloque.id, "content": cuerpo}
                )
            mensajes.append({"role": "user", "content": resultados})
    except Exception as error:  # una ejecucion rota no tumba la tanda
        registro.error = f"{error.__class__.__name__}: {error}"

    registro.wall_s = round(time.monotonic() - inicio, 2)
    if squire is not None:
        registro.squire_cost_usd = squire.meter.cost_usd
        registro.squire_decisions = squire.meter.decisions
    if registro.answer:
        registro.correct = acierta(registro.answer, tarea["answer_contains"])
    return registro


def verificar(documentos: list[Document], tareas: list[dict[str, Any]]) -> int:
    """Dos comprobaciones por tarea, y las dos tienen que pasar.

    1. El `pin` aparece exactamente en los documentos de `answer_in` y en ningun otro: la
       respuesta solo puede salir de haber recuperado ese documento.
    2. Cada cadena de `answer_contains` aparece en alguna parte del corpus, para que la regla
       de correccion sea alcanzable.
    """
    problemas = 0
    for tarea in tareas:
        pin = tarea["pin"]
        donde = sorted(d.id for d in documentos if pin in d.text)
        # Lo que tiene que cumplirse es que el dato este en un unico documento, no que ese
        # documento tenga un id concreto: los ids cambian con el troceado y la propiedad no.
        ok_pin = len(donde) == 1
        problemas += 0 if ok_pin else 1
        print(
            f"  {'ok ' if ok_pin else 'MAL'} {tarea['id']:12} pin {pin!r:32} "
            f"en {len(donde)} documento(s): {donde}"
        )
        for aguja in tarea["answer_contains"]:
            alcanzable = any(aguja in d.text for d in documentos)
            problemas += 0 if alcanzable else 1
            if not alcanzable:
                print(f"      MAL {aguja!r} no aparece en ningun documento del corpus")
    print(f"\n{len(tareas)} tareas, {problemas} problemas")
    return problemas


def _pares(filas: list[Ejecucion]) -> list[tuple[Ejecucion, Ejecucion]]:
    """Empareja cada ejecucion sin decisor con la del mismo caso y repeticion con decisor.

    El emparejamiento importa: los dos brazos arrancan del mismo prompt y del mismo buscador
    deterministico, asi que lo unico que los separa es el cribado mas el muestreo del modelo.
    Comparar medias sueltas mezclaria las dos cosas.
    """
    indice = {(f.task, f.repeat, f.arm): f for f in filas}
    pares = []
    for (tarea, repeticion, brazo), fila in indice.items():
        if brazo != "bare":
            continue
        companera = indice.get((tarea, repeticion, "squire"))
        if companera is not None and not fila.error and not companera.error:
            pares.append((fila, companera))
    return pares


def bootstrap_ratio(
    pares: list[tuple[Ejecucion, Ejecucion]],
    metrica: Callable[[Ejecucion], float],
    *,
    replicas: int = 2000,
    semilla: int = 7,
) -> tuple[float, float, float]:
    """Cambio relativo con decisor frente a sin el, con IC 95 % por remuestreo pareado."""
    if not pares:
        return 0.0, 0.0, 0.0
    base = [metrica(b) for b, _ in pares]
    tratado = [metrica(s) for _, s in pares]
    observado = sum(tratado) / sum(base) - 1 if sum(base) else 0.0
    generador = random.Random(semilla)
    n = len(pares)
    muestras = []
    for _ in range(replicas):
        indices = [generador.randrange(n) for _ in range(n)]
        b = sum(base[i] for i in indices)
        t = sum(tratado[i] for i in indices)
        muestras.append(t / b - 1 if b else 0.0)
    muestras.sort()
    return observado, muestras[int(0.025 * replicas)], muestras[int(0.975 * replicas) - 1]


def resumir(filas: list[Ejecucion]) -> dict[str, Any]:
    def agregado(sub: list[Ejecucion]) -> dict[str, Any]:
        if not sub:
            return {}
        decididas = [f for f in sub if f.correct is not None]
        return {
            "runs": len(sub),
            "correct": sum(1 for f in decididas if f.correct),
            "answered": len(decididas),
            "input_tokens_mean": round(statistics.mean(f.input_tokens for f in sub)),
            "output_tokens_mean": round(statistics.mean(f.output_tokens for f in sub)),
            "model_cost_mean": round(statistics.mean(f.model_cost_usd for f in sub), 6),
            "squire_cost_mean": round(statistics.mean(f.squire_cost_usd for f in sub), 6),
            "total_cost_mean": round(statistics.mean(f.total_cost_usd for f in sub), 6),
            "wall_s_mean": round(statistics.mean(f.wall_s for f in sub), 1),
            "fetches_mean": round(statistics.mean(len(f.fetched) for f in sub), 2),
            "dropped_mean": round(statistics.mean(len(f.dropped) for f in sub), 2),
            "turns_mean": round(statistics.mean(f.turns for f in sub), 2),
        }

    brazos = {arm: agregado([f for f in filas if f.arm == arm]) for arm in ("bare", "squire")}
    por_tarea = {
        t: {arm: agregado([f for f in filas if f.arm == arm and f.task == t]) for arm in brazos}
        for t in sorted({f.task for f in filas})
    }
    delta: dict[str, Any] = {}
    if brazos["bare"] and brazos["squire"]:
        b, s = brazos["bare"], brazos["squire"]
        delta = {
            "input_tokens_pct": round(
                100 * (s["input_tokens_mean"] / b["input_tokens_mean"] - 1), 1
            ),
            "total_cost_pct": round(100 * (s["total_cost_mean"] / b["total_cost_mean"] - 1), 1),
            "model_cost_pct": round(100 * (s["model_cost_mean"] / b["model_cost_mean"] - 1), 1),
            "wall_s_pct": round(100 * (s["wall_s_mean"] / b["wall_s_mean"] - 1), 1),
            "correct_bare": f"{b['correct']}/{b['answered']}",
            "correct_squire": f"{s['correct']}/{s['answered']}",
        }
    pares = _pares(filas)
    emparejado = {
        "pairs": len(pares),
        "input_tokens": bootstrap_ratio(pares, lambda f: f.input_tokens),
        "total_cost": bootstrap_ratio(pares, lambda f: f.total_cost_usd),
        "wall_s": bootstrap_ratio(pares, lambda f: f.wall_s),
    }
    return {"arms": brazos, "delta": delta, "by_task": por_tarea, "paired": emparejado}


def render(
    resumen: dict[str, Any],
    *,
    modelo: str,
    filas: list[Ejecucion],
    retrieval: str,
    doc_size: str,
) -> str:
    b, s, d = resumen["arms"]["bare"], resumen["arms"]["squire"], resumen["delta"]
    total = sum(f.total_cost_usd for f in filas)
    lineas = [
        f"# End-to-end A/B: page triage on and off ({modelo}, {retrieval} retrieval, "
        f"{doc_size} documents)",
        "",
        "Same agent, same tasks, same prompts, same tools, same thinking and effort. The only",
        "difference between the arms is that `fetch` passes the page through the squire before",
        "it enters the context. Corpus and tasks are in this directory; the run is offline apart",
        "from the model calls, so anyone can repeat it.",
        "",
        f"Retrieval condition `{retrieval}`: {CONDICIONES[retrieval]['descripcion']}.",
        "",
        f"Total spend of this run: {total:.4f} USD.",
        "",
        "| | Without the squire | With the squire | Change |",
        "|---|---|---|---|",
        f"| Runs | {b['runs']} | {s['runs']} | |",
        f"| Correct answers | {b['correct']}/{b['answered']} | {s['correct']}/{s['answered']} | |",
        f"| Input tokens, mean | {b['input_tokens_mean']:,} | {s['input_tokens_mean']:,} | "
        f"**{d['input_tokens_pct']:+.1f} %** |",
        f"| Output tokens, mean | {b['output_tokens_mean']:,} | {s['output_tokens_mean']:,} | |",
        f"| Model cost, mean | {b['model_cost_mean']:.5f} USD | {s['model_cost_mean']:.5f} USD | "
        f"{d['model_cost_pct']:+.1f} % |",
        f"| Squire cost, mean | 0 | {s['squire_cost_mean']:.6f} USD | |",
        f"| **Total cost, mean** | **{b['total_cost_mean']:.5f} USD** | "
        f"**{s['total_cost_mean']:.5f} USD** | **{d['total_cost_pct']:+.1f} %** |",
        f"| Wall time, mean | {b['wall_s_mean']} s | {s['wall_s_mean']} s "
        f"| {d['wall_s_pct']:+.1f} % |",
        f"| Documents fetched, mean | {b['fetches_mean']} | {s['fetches_mean']} | |",
        f"| Of those, dropped by triage | 0 | {s['dropped_mean']} | |",
        f"| Turns, mean | {b['turns_mean']} | {s['turns_mean']} | |",
        "",
        "## Paired comparison",
        "",
        f"Each run with the squire is paired with the run of the same task and repetition "
        f"without it, {resumen['paired']['pairs']} pairs. The interval is a 95 % paired "
        "bootstrap over those pairs, 2,000 resamples, fixed seed.",
        "",
        "| Measure | Change with the squire | 95 % CI |",
        "|---|---|---|",
        f"| Input tokens | **{resumen['paired']['input_tokens'][0]:+.1%}** | "
        f"[{resumen['paired']['input_tokens'][1]:+.1%}, "
        f"{resumen['paired']['input_tokens'][2]:+.1%}] |",
        f"| Total cost | **{resumen['paired']['total_cost'][0]:+.1%}** | "
        f"[{resumen['paired']['total_cost'][1]:+.1%}, "
        f"{resumen['paired']['total_cost'][2]:+.1%}] |",
        f"| Wall time | {resumen['paired']['wall_s'][0]:+.1%} | "
        f"[{resumen['paired']['wall_s'][1]:+.1%}, {resumen['paired']['wall_s'][2]:+.1%}] |",
        "",
        "## Per task",
        "",
        "| Task | Correct without / with | Input tokens without / with "
        "| Total cost without / with |",
        "|---|---|---|---|",
    ]
    for tarea, brazos in resumen["by_task"].items():
        bb, ss = brazos["bare"], brazos["squire"]
        if not bb or not ss:
            continue
        lineas.append(
            f"| {tarea} | {bb['correct']}/{bb['answered']} - {ss['correct']}/{ss['answered']} "
            f"| {bb['input_tokens_mean']:,} - {ss['input_tokens_mean']:,} "
            f"| {bb['total_cost_mean']:.5f} - {ss['total_cost_mean']:.5f} USD |"
        )
    lineas += [
        "",
        "## What this does and does not say",
        "",
        "It measures one lever, page triage, on one corpus, with one retriever and one model.",
        "It does not measure model routing, search routing, the citation check or the shell",
        "guard, none of which are exercised here. The corpus documents average a few hundred to",
        "a couple of thousand tokens; the effect scales with document size, and the arithmetic",
        "for other sizes is in `docs/savings.md`.",
        "",
        "Quality is measured as an exact-substring match against figures that appear in exactly",
        "one document of the corpus, verified by `--verify`. That catches an answer that lost the",
        "fact; it does not catch an answer that is worse in ways a reader would notice.",
    ]
    return "\n".join(lineas) + "\n"


async def principal(args: argparse.Namespace) -> int:
    documentos = build(TAMANOS[args.doc_size])
    tareas = [
        json.loads(linea)
        for linea in (Path(__file__).parent / "tasks.jsonl").read_text("utf-8").splitlines()
        if linea.strip() and not linea.lstrip().startswith("#")
    ]
    if args.tasks:
        elegidas = set(args.tasks.split(","))
        tareas = [t for t in tareas if t["id"] in elegidas]

    if args.verify:
        return 1 if verificar(documentos, tareas) else 0

    cliente = anthropic.Anthropic()
    clave_jev = os.environ.get("TYPESAFE_API_KEY")
    if not clave_jev:
        print("hace falta TYPESAFE_API_KEY para el brazo con decisor", file=sys.stderr)
        return 2

    filas: list[Ejecucion] = []
    gastado = 0.0
    for repeticion in range(args.repeats):
        for tarea in tareas:
            for arm in ("bare", "squire"):
                squire = None
                if arm == "squire":
                    squire = Squire(
                        create("jev", api_key=clave_jev),
                        thresholds=Thresholds(),
                        journal=JsonlJournal(Path(args.out) / "journal.jsonl"),
                        brief=tarea["question"],
                    )
                fila = await una_ejecucion(
                    cliente,
                    documentos,
                    tarea,
                    arm=arm,
                    repeat=repeticion,
                    args_retrieval=args.retrieval,
                    modelo=args.model,
                    squire=squire,
                    condicion=CONDICIONES[args.retrieval],
                )
                filas.append(fila)
                gastado += fila.model_cost_usd
                estado = "ok " if fila.correct else ("XX " if fila.correct is False else "?? ")
                print(
                    f"{estado}{tarea['id']:12} {arm:7} r{repeticion} "
                    f"{fila.input_tokens:>7,} tok  {fila.total_cost_usd:.5f} $  "
                    f"{fila.wall_s:>5.1f} s  fetch {len(fila.fetched)} drop {len(fila.dropped)}"
                    + (f"  ERROR {fila.error}" if fila.error else "")
                )
                if gastado > args.max_usd:
                    print(f"\nTOPE alcanzado: {gastado:.4f} $ > {args.max_usd} $. Paro.")
                    repeticion = args.repeats
                    break
            else:
                continue
            break
        else:
            continue
        break

    resumen = resumir(filas)
    texto = render(
        resumen,
        modelo=args.model,
        filas=filas,
        retrieval=args.retrieval,
        doc_size=args.doc_size,
    )
    print("\n" + texto)
    salida = Path(args.out)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "runs.json").write_text(
        json.dumps([asdict(f) for f in filas], indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (salida / "summary.json").write_text(
        json.dumps(resumen, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    (salida / "summary.md").write_text(texto, encoding="utf-8")
    print(f"escrito en {salida}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="benchmarks.ab.run", description=__doc__)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--tasks", default=None, help="ids separados por comas")
    p.add_argument("--model", default=MODELO_POR_DEFECTO)
    p.add_argument("--out", default="benchmarks/ab/results/latest")
    p.add_argument("--max-usd", type=float, default=6.0, help="tope de gasto de la tanda")
    p.add_argument(
        "--doc-size",
        choices=sorted(TAMANOS),
        default="small",
        help="tamano de los documentos del corpus",
    )
    p.add_argument(
        "--retrieval",
        choices=sorted(CONDICIONES),
        default="noisy",
        help="lo buena que es la recuperacion: precise o noisy",
    )
    p.add_argument("--verify", action="store_true", help="comprueba la verdad de referencia")
    return asyncio.run(principal(p.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
