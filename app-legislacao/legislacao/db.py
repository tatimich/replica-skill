"""Banco de dados (SQLite + FTS5) e consultas da biblioteca de legislação."""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "dados" / "legislacao.db"

SITUACOES = {
    "vigente": "Vigente",
    "alterado": "Alterado",
    "revogado": "Revogado",
    "sem_informacao": "Sem informação",
}

CAMPOS = ("tipo", "numero", "data", "orgao", "categoria", "ementa", "texto", "situacao", "fonte_url")

SCHEMA = """
create table if not exists atos (
    id integer primary key,
    tipo text not null,
    numero text not null default '',
    data text not null check (data glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    ano integer generated always as (cast(substr(data, 1, 4) as integer)) stored,
    orgao text not null default '',
    categoria text not null default '',
    ementa text not null,
    texto text not null default '',
    situacao text not null default 'sem_informacao'
        check (situacao in ('vigente', 'alterado', 'revogado', 'sem_informacao')),
    fonte_url text not null default '',
    criado_em text not null default (datetime('now')),
    atualizado_em text not null default (datetime('now'))
);
create unique index if not exists atos_identidade on atos (tipo, numero, orgao, data);
create index if not exists atos_data on atos (data desc);
create index if not exists atos_ano on atos (ano);
create index if not exists atos_categoria on atos (categoria);
create index if not exists atos_tipo on atos (tipo);

create virtual table if not exists atos_fts using fts5(
    tipo, numero, ementa, texto, orgao, categoria,
    content='atos', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

create trigger if not exists atos_ai after insert on atos begin
    insert into atos_fts (rowid, tipo, numero, ementa, texto, orgao, categoria)
    values (new.id, new.tipo, new.numero, new.ementa, new.texto, new.orgao, new.categoria);
end;
create trigger if not exists atos_ad after delete on atos begin
    insert into atos_fts (atos_fts, rowid, tipo, numero, ementa, texto, orgao, categoria)
    values ('delete', old.id, old.tipo, old.numero, old.ementa, old.texto, old.orgao, old.categoria);
end;
create trigger if not exists atos_au after update on atos begin
    insert into atos_fts (atos_fts, rowid, tipo, numero, ementa, texto, orgao, categoria)
    values ('delete', old.id, old.tipo, old.numero, old.ementa, old.texto, old.orgao, old.categoria);
    insert into atos_fts (rowid, tipo, numero, ementa, texto, orgao, categoria)
    values (new.id, new.tipo, new.numero, new.ementa, new.texto, new.orgao, new.categoria);
end;
"""


def caminho_banco() -> Path:
    return Path(os.environ.get("LEGISLACAO_DB", CAMINHO_PADRAO))


def conectar(caminho: Path | str | None = None) -> sqlite3.Connection:
    caminho = Path(caminho) if caminho else caminho_banco()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys = on")
    con.executescript(SCHEMA)
    return con


# --------------------------------------------------------------------------- validação


class ErroValidacao(ValueError):
    pass


def normalizar_data(valor: str) -> str:
    """Aceita AAAA-MM-DD ou DD/MM/AAAA e devolve AAAA-MM-DD."""
    valor = (valor or "").strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(valor, formato).date().isoformat()
        except ValueError:
            continue
    raise ErroValidacao(f"Data inválida: {valor!r} (use AAAA-MM-DD ou DD/MM/AAAA)")


def validar(dados: dict) -> dict:
    ato = {campo: (dados.get(campo) or "").strip() for campo in CAMPOS}
    if not ato["tipo"]:
        raise ErroValidacao("Informe o tipo do ato (ex.: Lei, Decreto, Portaria).")
    if not ato["ementa"]:
        raise ErroValidacao("Informe a ementa.")
    ato["data"] = normalizar_data(ato["data"])
    ato["situacao"] = ato["situacao"] or "sem_informacao"
    if ato["situacao"] not in SITUACOES:
        raise ErroValidacao(f"Situação inválida: {ato['situacao']!r}. Use: {', '.join(SITUACOES)}.")
    if ato["fonte_url"] and not re.match(r"^https?://", ato["fonte_url"]):
        raise ErroValidacao("O link da fonte oficial deve começar com http:// ou https://.")
    return ato


# --------------------------------------------------------------------------- escrita


def salvar(con: sqlite3.Connection, dados: dict) -> int:
    """Insere ou atualiza (pela identidade tipo + número + órgão + data). Devolve o id."""
    ato = validar(dados)
    cur = con.execute(
        """
        insert into atos (tipo, numero, data, orgao, categoria, ementa, texto, situacao, fonte_url)
        values (:tipo, :numero, :data, :orgao, :categoria, :ementa, :texto, :situacao, :fonte_url)
        on conflict (tipo, numero, orgao, data) do update set
            categoria = excluded.categoria, ementa = excluded.ementa, texto = excluded.texto,
            situacao = excluded.situacao, fonte_url = excluded.fonte_url,
            atualizado_em = datetime('now')
        returning id
        """,
        ato,
    )
    novo_id = cur.fetchone()[0]
    con.commit()
    return novo_id


def atualizar(con: sqlite3.Connection, ato_id: int, dados: dict) -> None:
    ato = validar(dados)
    ato["id"] = ato_id
    con.execute(
        """
        update atos set tipo = :tipo, numero = :numero, data = :data, orgao = :orgao,
            categoria = :categoria, ementa = :ementa, texto = :texto, situacao = :situacao,
            fonte_url = :fonte_url, atualizado_em = datetime('now')
        where id = :id
        """,
        ato,
    )
    con.commit()


def excluir(con: sqlite3.Connection, ato_id: int) -> None:
    con.execute("delete from atos where id = ?", (ato_id,))
    con.commit()


# --------------------------------------------------------------------------- leitura


def obter(con: sqlite3.Connection, ato_id: int) -> dict | None:
    linha = con.execute("select * from atos where id = ?", (ato_id,)).fetchone()
    return dict(linha) if linha else None


def consulta_fts(texto: str) -> str:
    """Transforma o que a pessoa digitou numa consulta FTS5 segura.

    Palavras viram prefixos ("regula" acha "regulação"); trechos entre aspas
    viram frase exata. Operadores do FTS5 digitados pela pessoa são ignorados.
    """
    partes = []
    for frase, palavra in re.findall(r'"([^"]+)"|(\S+)', texto or ""):
        if frase:
            termos = re.findall(r"\w+", frase)
            if termos:
                partes.append('"' + " ".join(termos) + '"')
        else:
            for termo in re.findall(r"\w+", palavra):
                partes.append(f'"{termo}"*')
    return " ".join(partes)


@dataclass
class Filtros:
    q: str = ""
    categoria: str = ""
    ano: int | None = None
    tipo: str = ""
    orgao: str = ""
    situacao: str = ""
    ordem: str = ""  # "recentes", "antigos", "relevancia"
    pagina: int = 1
    por_pagina: int = 20


def buscar(con: sqlite3.Connection, f: Filtros) -> tuple[list[dict], int]:
    where, params = [], {}
    juncao = ""
    consulta = consulta_fts(f.q)
    if consulta:
        juncao = "join atos_fts on atos_fts.rowid = atos.id"
        where.append("atos_fts match :q")
        params["q"] = consulta
    for campo in ("categoria", "tipo", "orgao", "situacao"):
        valor = getattr(f, campo)
        if valor:
            where.append(f"atos.{campo} = :{campo}")
            params[campo] = valor
    if f.ano:
        where.append("atos.ano = :ano")
        params["ano"] = f.ano
    clausula = ("where " + " and ".join(where)) if where else ""

    ordem = f.ordem or ("relevancia" if consulta else "recentes")
    if ordem == "relevancia" and consulta:
        order_by = "bm25(atos_fts, 2.0, 3.0, 4.0, 1.0, 1.0, 1.0), atos.data desc"
    elif ordem == "antigos":
        order_by = "atos.data asc, atos.id asc"
    else:
        order_by = "atos.data desc, atos.id desc"

    trecho = (
        "snippet(atos_fts, 3, '[[', ']]', ' … ', 24) as trecho"
        if consulta
        else "'' as trecho"
    )
    total = con.execute(f"select count(*) from atos {juncao} {clausula}", params).fetchone()[0]
    por_pagina = max(1, min(f.por_pagina, 100))
    pagina = max(1, f.pagina)
    params.update(limite=por_pagina, deslocamento=(pagina - 1) * por_pagina)
    linhas = con.execute(
        f"""
        select atos.id, atos.tipo, atos.numero, atos.data, atos.ano, atos.orgao,
               atos.categoria, atos.ementa, atos.situacao, atos.fonte_url,
               length(atos.texto) > 0 as tem_texto, {trecho}
        from atos {juncao} {clausula}
        order by {order_by}
        limit :limite offset :deslocamento
        """,
        params,
    ).fetchall()
    return [dict(l) for l in linhas], total


def facetas(con: sqlite3.Connection) -> dict:
    def contar(coluna: str, ordem: str) -> list[dict]:
        return [
            {"valor": l[0], "total": l[1]}
            for l in con.execute(
                f"select {coluna}, count(*) from atos where {coluna} != '' "
                f"group by {coluna} order by {ordem}"
            )
        ]

    return {
        "categorias": contar("categoria", "categoria collate nocase"),
        "anos": contar("ano", "ano desc"),
        "tipos": contar("tipo", "tipo collate nocase"),
        "orgaos": contar("orgao", "orgao collate nocase"),
    }


# --------------------------------------------------------------------------- apresentação

MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)


def data_extenso(iso: str) -> str:
    d = date.fromisoformat(iso)
    dia = "1º" if d.day == 1 else str(d.day)
    return f"{dia} de {MESES[d.month - 1]} de {d.year}"


def data_curta(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def titulo(ato: dict) -> str:
    """Ex.: 'Lei nº 1.234, de 5 de março de 2020'."""
    numero = f" nº {ato['numero']}" if ato.get("numero") else ""
    return f"{ato['tipo']}{numero}, de {data_extenso(ato['data'])}"
