"""Does a decision layer that narrows the tool catalog save money, or cost it?

    python benchmarks/cache/run.py --dry          # token arithmetic only, no API calls
    python benchmarks/cache/run.py --turns 8      # the real thing, a few tens of cents

The package exposes a tool-selection point (`Squire.select_tools`). The arithmetic for it is
seductive: a large MCP catalog is tens of thousands of tokens of schemas in every request,
Anthropic reports 58 tools at about 55k tokens and a peak of 134k before optimization, so
dropping two thirds of it looks like dropping two thirds of a large bill.

That arithmetic is incomplete, and this benchmark measures what it leaves out. Tool
definitions sit at the very front of the prompt prefix, and the caching hierarchy is
`tools -> system -> messages`: changing the tool array invalidates all three caches. A
cached read costs a tenth of a base input token; a rebuild costs a write at 1.25x. So the
question is not how many schema tokens a selector removes, it is how often it changes its
mind. Measured here, over 8 turns on claude-sonnet-5: narrowing once is 43 % cheaper than
the full catalog, narrowing on alternate turns is 14 % *dearer* than never narrowing, and a
selector that picks a different subset every turn reads nothing from cache at all and costs
4.15x the one that decided once. Results and caveats: `results/summary.md`.

Four arms, identical in everything else:

- `static`   - the whole catalog on every turn. What a harness does by default.
- `once`     - the catalog narrowed once, before the first turn, then held fixed. The wiring
               the package documents: decide at the only moment when there is no prefix to
               invalidate.
- `reselect` - the catalog alternating between two stable subsets, rewritten into `tools`
               each turn.
- `churn`    - a different subset on every turn, which is what an unstable selector actually
               produces.

**The first run of this benchmark was wrong, and the fix is worth reading.** All four arms
shared one catalog, so the later arms read caches the earlier ones had written, and
`reselect` came out the cheapest of the three. The prefix cache is keyed by the bytes of the
prefix, not by the conversation: alternating between two stable tool sets writes two cache
entries and then reads them, which is cheap. Every arm now tags its tool descriptions with
its own name, so no arm can inherit another's cache, and `churn` exists because instability,
not narrowing, is what costs money.

What is measured per arm: cached reads, cache writes, uncached input, output, dollars. The
selection itself is fixed and deterministic (the same subset in `reselect` and `once`), so
the only thing that differs between those two arms is *when* it is applied. That is the
whole point: same decision, same tools, different moment, different bill.

Cost control: a turn cap, a printed running total, and `--max-usd` aborts.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

import anthropic  # noqa: E402

# Precios de lista de la API de Anthropic, $/Mtok, a 2026-06-24. Lectura de cache 0,1x de la
# entrada base; escritura de 5 min 1,25x; de 1 h 2x.
PRECIOS = {
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
MODELO = "claude-sonnet-5"
LECTURA_CACHE = 0.10
ESCRITURA_CACHE = 1.25

# Un catalogo sintetico con la forma de uno real: grupos de herramientas de varios dominios,
# con esquemas del tamano que tienen los de un servidor MCP de verdad. Sintetico a proposito:
# lo que se mide es el mecanismo de la cache, no la calidad de unos esquemas concretos.
GRUPOS = {
    "registros": ("consulta de registros mercantiles y de la propiedad", 9),
    "judicial": ("consulta de sentencias, expedientes y agendas judiciales", 8),
    "prensa": ("hemerotecas y agregadores de noticias", 6),
    "geo": ("catalogos sismicos, cartografia y datos de proteccion civil", 7),
    "finanzas": ("mercados, cotizaciones y estados financieros", 8),
    "salud": ("fichas de medicamentos, ensayos clinicos y farmacovigilancia", 8),
    "logistica": ("seguimiento de envios, aduanas y flotas", 7),
    "interno": ("ficheros del trabajo, notas y volumen conservado", 5),
}
# La seleccion que tomaria el decisor para una tarea de investigacion societaria. Fija aqui
# para que los dos brazos que seleccionan apliquen exactamente la misma, y la unica variable
# sea el momento en que se aplica.
SELECCION = ("registros", "judicial", "prensa", "interno")

CAMPOS = [
    ("identificador", "string", "Identificador unico del registro que se consulta"),
    ("jurisdiccion", "string", "Codigo ISO del pais o de la subdivision administrativa"),
    ("desde", "string", "Fecha inicial del intervalo, en formato ISO 8601"),
    ("hasta", "string", "Fecha final del intervalo, en formato ISO 8601"),
    ("incluir_historico", "boolean", "Si se incluyen las versiones anteriores del registro"),
    ("pagina", "integer", "Numero de pagina de resultados, empezando en 1"),
    ("por_pagina", "integer", "Resultados por pagina, entre 1 y 100"),
    ("formato", "string", "Formato de la respuesta: json, csv o texto plano"),
]

SISTEMA = (
    "You are a research assistant working on corporate and judicial investigations. "
    "Use the tools available to you to answer. State figures exactly as the sources give "
    "them, and name the source of every figure you report. Do not speculate: if the tools "
    "cannot answer, say so plainly. Keep answers to a few sentences."
)

PREGUNTAS = [
    "In one sentence, what would you check first to establish who owns a company?",
    "And what would you check second, if the first came back empty?",
    "How would you tell two people with the same surname apart in a registry?",
    "What makes a court ruling hard to match to the right company?",
    "Which is more reliable for a date: the registry or the press?",
    "How would you record that two sources disagree on a figure?",
    "What would make you stop looking and write up what you have?",
    "Summarise, in two sentences, the method you have described.",
    "What is the single most common mistake in this kind of work?",
    "How would you check that a quotation really appears in a ruling?",
]


def herramientas(grupo: str, descripcion: str, cuantas: int, marca: str = "") -> list[dict]:
    """Esquemas con la forma y el tamano de los de un servidor MCP real.

    `marca` es el nombre del brazo, incrustado en la descripcion. Sin el, los brazos
    comparten los bytes del prefijo y por tanto la cache: el primer brazo paga la escritura
    y los demas leen gratis lo que el escribio, que fue exactamente el error de la primera
    ejecucion de este banco.
    """
    salida = []
    for i in range(cuantas):
        salida.append(
            {
                "name": f"{grupo}_operacion_{i:02d}",
                "description": (
                    f"{marca}Herramienta del grupo {grupo} ({descripcion}). Operacion {i}: "
                    f"consulta la fuente correspondiente y devuelve los registros que "
                    f"coinciden con los criterios indicados, paginados y con sus metadatos "
                    f"de procedencia, fecha de actualizacion y nivel de confianza."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        nombre: {"type": tipo, "description": desc} for nombre, tipo, desc in CAMPOS
                    },
                    "required": ["identificador"],
                    "additionalProperties": False,
                },
            }
        )
    return salida


def catalogo(grupos: tuple[str, ...] | None = None, marca: str = "") -> list[dict]:
    elegidos = grupos or tuple(GRUPOS)
    salida: list[dict] = []
    for nombre in elegidos:
        descripcion, cuantas = GRUPOS[nombre]
        salida.extend(herramientas(nombre, descripcion, cuantas, marca))
    return salida


def subconjunto(turno: int) -> tuple[str, ...]:
    """Un subconjunto distinto en cada turno: lo que produce un selector inestable."""
    nombres = tuple(GRUPOS)
    inicio = turno % len(nombres)
    return tuple(nombres[(inicio + k) % len(nombres)] for k in range(4))


@dataclass
class Brazo:
    nombre: str
    turnos: int = 0
    entrada_sin_cache: int = 0
    lectura_cache: int = 0
    escritura_cache: int = 0
    salida: int = 0
    segundos: float = 0.0
    herramientas_por_turno: list[int] = field(default_factory=list)

    @property
    def coste(self) -> float:
        entrada, salida = PRECIOS[MODELO]
        return (
            self.entrada_sin_cache * entrada
            + self.lectura_cache * entrada * LECTURA_CACHE
            + self.escritura_cache * entrada * ESCRITURA_CACHE
            + self.salida * salida
        ) / 1_000_000


def ejecutar(cliente, nombre: str, turnos: int, modo: str) -> Brazo:
    """Un brazo: `turnos` peticiones sobre la misma conversacion, con la misma pregunta."""
    brazo = Brazo(nombre)
    mensajes: list[dict] = []
    marca = f"[{nombre}] "
    completo = catalogo(None, marca)
    estrecho = catalogo(SELECCION, marca)
    for i in range(turnos):
        if modo == "static":
            tools = completo
        elif modo == "once":
            tools = estrecho
        elif modo == "reselect":  # dos subconjuntos estables que se alternan
            tools = estrecho if i % 2 == 0 else completo
        else:  # churn: un subconjunto distinto cada turno
            tools = catalogo(subconjunto(i), marca)
        mensajes.append({"role": "user", "content": PREGUNTAS[i % len(PREGUNTAS)]})
        inicio = time.time()
        respuesta = cliente.messages.create(
            model=MODELO,
            max_tokens=300,
            system=[{"type": "text", "text": SISTEMA, "cache_control": {"type": "ephemeral"}}],
            tools=[
                {**t, **({"cache_control": {"type": "ephemeral"}} if t is tools[-1] else {})}
                for t in tools
            ],
            messages=mensajes,
        )
        brazo.segundos += time.time() - inicio
        uso = respuesta.usage
        brazo.turnos += 1
        brazo.entrada_sin_cache += uso.input_tokens
        brazo.lectura_cache += uso.cache_read_input_tokens or 0
        brazo.escritura_cache += uso.cache_creation_input_tokens or 0
        brazo.salida += uso.output_tokens
        brazo.herramientas_por_turno.append(len(tools))
        texto = next((b.text for b in respuesta.content if b.type == "text"), "")
        mensajes.append({"role": "assistant", "content": texto or "."})
        print(
            f"  {nombre} t{i + 1}: {len(tools)} tools, "
            f"lectura {uso.cache_read_input_tokens or 0}, "
            f"escritura {uso.cache_creation_input_tokens or 0}, "
            f"sin cache {uso.input_tokens}"
        )
    return brazo


def tokens_aproximados(tools: list[dict]) -> int:
    return len(json.dumps(tools, ensure_ascii=False)) // 4


def seco(turnos: int) -> None:
    completo, estrecho = catalogo(), catalogo(SELECCION)
    tc, te = tokens_aproximados(completo), tokens_aproximados(estrecho)
    entrada = PRECIOS[MODELO][0]
    print(f"catalogo completo: {len(completo)} herramientas, ~{tc} tokens")
    print(f"catalogo estrecho: {len(estrecho)} herramientas, ~{te} tokens")
    print(f"\nprevision para {turnos} turnos a precios de {MODELO} (solo los esquemas):")
    est = tc * ESCRITURA_CACHE + tc * LECTURA_CACHE * (turnos - 1)
    once = te * ESCRITURA_CACHE + te * LECTURA_CACHE * (turnos - 1)
    res = tc * ESCRITURA_CACHE * turnos  # cada turno reescribe el prefijo entero
    for nombre, valor in (("static", est), ("once", once), ("reselect", res)):
        print(f"  {nombre:9s} {valor:9.0f} tokens equivalentes  {valor * entrada / 1e6:.5f} USD")
    print("\nLa prevision solo cuenta los esquemas. En la medicion real el brazo `reselect`")
    print("paga ademas la reescritura de la conversacion entera, que crece con cada turno.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--turns", type=int, default=8)
    p.add_argument("--dry", action="store_true", help="solo la aritmetica, sin llamadas")
    p.add_argument("--max-usd", type=float, default=3.0)
    p.add_argument("--out", default="benchmarks/cache/results")
    args = p.parse_args()

    if args.dry:
        seco(args.turns)
        return

    cliente = anthropic.Anthropic()
    brazos = []
    arms = (("static", "static"), ("once", "once"), ("reselect", "reselect"), ("churn", "churn"))
    for nombre, modo in arms:
        print(f"\n{nombre}:")
        brazo = ejecutar(cliente, nombre, args.turns, modo)
        brazos.append(brazo)
        total = sum(b.coste for b in brazos)
        print(f"  {nombre}: {brazo.coste:.5f} USD (acumulado {total:.5f})")
        if total > args.max_usd:
            print("tope de gasto alcanzado, se corta aqui")
            break

    salida = Path(args.out)
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "runs.json").write_text(
        json.dumps([asdict(b) | {"coste_usd": b.coste} for b in brazos], indent=1),
        encoding="utf-8",
    )
    print("\n| Arm | Turns | Cached reads | Cache writes | Uncached in | Out | Cost |")
    print("|---|---|---|---|---|---|---|")
    for b in brazos:
        print(
            f"| {b.nombre} | {b.turnos} | {b.lectura_cache:,} | {b.escritura_cache:,} | "
            f"{b.entrada_sin_cache:,} | {b.salida:,} | {b.coste:.5f} USD |"
        )


if __name__ == "__main__":
    main()
