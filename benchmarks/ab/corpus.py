"""The corpus the A/B agent searches over. Built from files in this repository, so the run
is offline, deterministic and reproducible by anyone who clones it.

Two document families on purpose:

- **Long, English**: this repository's own documents, with the paper split by section. They
  run from a few hundred to a couple of thousand tokens each, which is the size of a real
  fetched page after boilerplate removal.
- **Short, Spanish**: the page texts of the triage bench, 87 to 293 tokens, real excerpts
  from two investigations. They are the distractor family that a search engine would return
  alongside the right answer.

Nothing here is written for the benchmark. Using documents that already existed is what
stops the corpus from being tuned to make the squire look good.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DOCS = ("architecture.md", "adapters.md", "providers.md", "benches.md", "savings.md")
MIN_SECTION_CHARS = 400


@dataclass(frozen=True, slots=True)
class Document:
    id: str
    title: str
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)


def _split_by_heading(
    markdown: str, source: str, min_chars: int = MIN_SECTION_CHARS
) -> list[tuple[str, str]]:
    """Split a markdown file on its `## ` headings. Sections under `min_chars` fold into the
    previous one, so `min_chars` is what sets document size: 400 gives page-sized documents,
    6000 gives the long documents a real fetch of an official PDF looks like."""
    partes: list[tuple[str, str]] = []
    titulo, buffer = f"{source}: intro", []
    for linea in markdown.splitlines():
        if linea.startswith("## "):
            cuerpo = "\n".join(buffer).strip()
            if cuerpo:
                partes.append((titulo, cuerpo))
            titulo, buffer = f"{source}: {linea[3:].strip()}", []
        else:
            buffer.append(linea)
    cuerpo = "\n".join(buffer).strip()
    if cuerpo:
        partes.append((titulo, cuerpo))

    fundidas: list[tuple[str, str]] = []
    for titulo, cuerpo in partes:
        if fundidas and len(cuerpo) < min_chars:
            anterior_t, anterior_c = fundidas[-1]
            fundidas[-1] = (anterior_t, f"{anterior_c}\n\n{cuerpo}")
        else:
            fundidas.append((titulo, cuerpo))
    return fundidas


def build(min_chars: int = MIN_SECTION_CHARS) -> list[Document]:
    documentos: list[Document] = []

    paper = (RAIZ / "docs" / "paper.md").read_text(encoding="utf-8")
    for i, (titulo, cuerpo) in enumerate(_split_by_heading(paper, "paper", min_chars)):
        documentos.append(Document(f"paper-{i:02d}", titulo, cuerpo))

    for nombre in DOCS:
        ruta = RAIZ / "docs" / nombre
        base = nombre.removesuffix(".md")
        for i, (titulo, cuerpo) in enumerate(
            _split_by_heading(ruta.read_text("utf-8"), base, min_chars)
        ):
            documentos.append(Document(f"{base}-{i:02d}", titulo, cuerpo))

    casos = [
        json.loads(linea)
        for linea in (RAIZ / "benches" / "core.jsonl").read_text("utf-8").splitlines()
        if linea.strip() and not linea.lstrip().startswith("#")
    ]
    for caso in (c for c in casos if c["point"] == "triage"):
        entrada = caso["input"]
        documentos.append(
            Document(
                f"page-{caso['id']}",
                entrada.get("title") or entrada["purpose"][:70],
                entrada["text"],
            )
        )
    return documentos


def search(
    documentos: list[Document],
    consulta: str,
    limite: int = 8,
    *,
    realce_titulo: int = 3,
) -> list[Document]:
    """Deterministic keyword search: no embeddings, no network, no hidden ranking.

    Scores a document by how many of the query's words appear in its title and body.
    `realce_titulo` is how much a title hit is worth: 3 makes retrieval good, 0 makes it
    body-frequency only, which is what a mediocre retriever looks like and is the condition
    triage exists for. The benchmark runs both.
    """
    palabras = [p for p in re.findall(r"[\wÀ-ɏ]+", consulta.lower()) if len(p) > 3]
    if not palabras:
        return []
    puntuados: list[tuple[int, Document]] = []
    for d in documentos:
        cuerpo = d.text.lower()
        titulo = d.title.lower()
        puntos = sum(realce_titulo * titulo.count(p) + cuerpo.count(p) for p in palabras)
        if puntos:
            puntuados.append((puntos, d))
    puntuados.sort(key=lambda par: (-par[0], par[1].id))
    return [d for _, d in puntuados[:limite]]


if __name__ == "__main__":
    docs = build()
    print(f"{len(docs)} documentos, {sum(d.chars for d in docs):,} caracteres")
    for d in docs:
        print(f"  {d.id:22} {d.chars:>7,}  {d.title[:60]}")
