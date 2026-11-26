"""Configuração da marca (timbrado) e da integração com o site, lida de marca.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_PADRAO = RAIZ / "marca.toml"


@dataclass
class Marca:
    nome: str = "Biblioteca de Legislação"
    subtitulo: str = ""
    logo: str = ""
    endereco: str = ""
    contato: str = ""
    site: str = ""
    cor_primaria: str = "#1F3A5F"
    rodape: str = ""
    cors_origens: list[str] = field(default_factory=list)
    frame_ancestors: list[str] = field(default_factory=lambda: ["'self'"])

    @property
    def caminho_logo(self) -> Path | None:
        if not self.logo:
            return None
        p = Path(self.logo)
        if not p.is_absolute():
            p = RAIZ / p
        return p if p.is_file() else None

    @property
    def linha_contato(self) -> str:
        return "  |  ".join(x for x in (self.endereco, self.contato, self.site) if x)


def carregar(caminho: Path | str | None = None) -> Marca:
    caminho = Path(caminho or os.environ.get("LEGISLACAO_MARCA", CAMINHO_PADRAO))
    if not caminho.is_file():
        return Marca()
    with open(caminho, "rb") as arq:
        dados = tomllib.load(arq)
    m = dados.get("marca", {})
    i = dados.get("integracao", {})
    padrao = Marca()
    return Marca(
        nome=m.get("nome", padrao.nome),
        subtitulo=m.get("subtitulo", ""),
        logo=m.get("logo", ""),
        endereco=m.get("endereco", ""),
        contato=m.get("contato", ""),
        site=m.get("site", ""),
        cor_primaria=m.get("cor_primaria", padrao.cor_primaria),
        rodape=m.get("rodape", ""),
        cors_origens=list(i.get("cors_origens", [])),
        frame_ancestors=list(i.get("frame_ancestors", padrao.frame_ancestors)),
    )
