"""Importação de atos a partir de CSV.

Uso:
    python -m legislacao.importar dados/meus-atos.csv

Colunas (cabeçalho obrigatório; separador vírgula ou ponto e vírgula, UTF-8):
    tipo, numero, data, orgao, categoria, ementa, situacao, fonte_url, texto

Linhas com a mesma identidade (tipo + número + órgão + data) são atualizadas.
"""

from __future__ import annotations

import csv
import io
import sys

from . import db


def importar_texto(con, conteudo: str) -> tuple[int, list[str]]:
    """Importa um CSV já lido. Devolve (quantidade importada, lista de erros por linha)."""
    conteudo = conteudo.lstrip("﻿")
    try:
        dialeto = csv.Sniffer().sniff(conteudo.split("\n", 1)[0], delimiters=",;")
    except csv.Error:
        dialeto = csv.excel
    leitor = csv.DictReader(io.StringIO(conteudo), dialect=dialeto)
    faltando = {"tipo", "data", "ementa"} - set(leitor.fieldnames or [])
    if faltando:
        return 0, [f"Cabeçalho sem as colunas obrigatórias: {', '.join(sorted(faltando))}"]
    ok, erros = 0, []
    for n, linha in enumerate(leitor, start=2):
        try:
            db.salvar(con, {k.strip(): v for k, v in linha.items() if k})
            ok += 1
        except db.ErroValidacao as e:
            erros.append(f"Linha {n}: {e}")
    return ok, erros


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    with open(argv[0], encoding="utf-8-sig", newline="") as arq:
        conteudo = arq.read()
    con = db.conectar()
    ok, erros = importar_texto(con, conteudo)
    print(f"{ok} ato(s) importado(s) para {db.caminho_banco()}")
    for e in erros:
        print("  ", e)
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
