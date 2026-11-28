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

COLUNAS = (
    "tipo", "numero", "data", "data_publicacao", "orgao", "categoria",
    "ementa", "texto", "situacao", "fonte_url",
)
RELACOES = {"revoga": ("Revoga", "Revogado por"), "altera": ("Altera", "Alterado por")}
CAMPOS = COLUNAS + tuple(RELACOES)  # campos aceitos no formulário e no CSV

# Data de referência para filtros de ano/mês/dia: publicação no D.O.U. quando houver; senão, a do ato.
DATA_REF = "coalesce(nullif(atos.data_publicacao, ''), atos.data)"

SCHEMA = """
create table if not exists atos (
    id integer primary key,
    tipo text not null,
    numero text not null default '',
    data text not null check (data glob '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    data_publicacao text not null default '',
    ano integer generated always as (cast(substr(data, 1, 4) as integer)) stored,
    orgao text not null default '',
    categoria text not null default '',
    ementa text not null,
    texto text not null default '',
    situacao text not null default 'sem_informacao'
        check (situacao in ('vigente', 'alterado', 'revogado', 'sem_informacao')),
    fonte_url text not null default '',
    origem_id text,
    criado_em text not null default (datetime('now')),
    atualizado_em text not null default (datetime('now'))
);
create table if not exists relacoes (
    id integer primary key,
    origem_id integer not null references atos (id) on delete cascade,
    tipo text not null check (tipo in ('revoga', 'altera')),
    referencia text not null,
    destino_id integer references atos (id) on delete set null
);
create index if not exists relacoes_origem on relacoes (origem_id);
create index if not exists relacoes_destino on relacoes (destino_id);

create unique index if not exists atos_identidade on atos (tipo, numero, orgao, data) where numero != '';
create unique index if not exists atos_origem on atos (origem_id) where origem_id is not null;

create table if not exists coletas (
    data text not null,
    secao text not null,
    total integer not null default 0,
    incluidos integer not null default 0,
    erro text not null default '',
    em text not null default (datetime('now')),
    primary key (data, secao)
);
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
    _migrar(con)
    con.executescript(SCHEMA)
    return con


def _migrar(con: sqlite3.Connection) -> None:
    """Atualiza bancos criados por versões anteriores."""
    colunas = {l[1] for l in con.execute("pragma table_info(atos)")}
    if not colunas:
        return
    if "data_publicacao" not in colunas:
        con.execute("alter table atos add column data_publicacao text not null default ''")
    if "origem_id" not in colunas:
        con.execute("alter table atos add column origem_id text")
    # Identidade antiga (sem filtro) impedia vários atos sem número no mesmo dia e órgão.
    sql = con.execute("select sql from sqlite_master where name = 'atos_identidade'").fetchone()
    if sql and "where" not in (sql[0] or "").lower():
        con.execute("drop index atos_identidade")
    con.commit()


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
    ato = {campo: (dados.get(campo) or "").strip() for campo in COLUNAS}
    if not ato["tipo"]:
        raise ErroValidacao("Informe o tipo do ato (ex.: Lei, Decreto, Portaria).")
    if not ato["ementa"]:
        raise ErroValidacao("Informe a ementa.")
    ato["data"] = normalizar_data(ato["data"])
    if ato["data_publicacao"]:
        ato["data_publicacao"] = normalizar_data(ato["data_publicacao"])
    ato["situacao"] = ato["situacao"] or "sem_informacao"
    if ato["situacao"] not in SITUACOES:
        raise ErroValidacao(f"Situação inválida: {ato['situacao']!r}. Use: {', '.join(SITUACOES)}.")
    if ato["fonte_url"] and not re.match(r"^https?://", ato["fonte_url"]):
        raise ErroValidacao("O link da fonte oficial deve começar com http:// ou https://.")
    return ato


# --------------------------------------------------------------------------- escrita


def salvar(con: sqlite3.Connection, dados: dict, origem_id: str | None = None) -> int:
    """Insere ou atualiza. Devolve o id.

    Atualiza o ato existente quando encontra o mesmo `origem_id` (identificador na fonte oficial)
    ou, para atos numerados, a mesma identidade (tipo + número + órgão + data).
    """
    ato = validar(dados)
    existente = None
    if origem_id:
        existente = con.execute("select id from atos where origem_id = ?", (origem_id,)).fetchone()
    if not existente and ato["numero"]:
        existente = con.execute(
            "select id from atos where tipo = :tipo and numero = :numero and orgao = :orgao and data = :data", ato
        ).fetchone()
    ato["origem_id"] = origem_id
    if existente:
        ato["id"] = existente[0]
        con.execute(
            """
            update atos set tipo = :tipo, numero = :numero, data = :data, data_publicacao = :data_publicacao,
                orgao = :orgao, categoria = :categoria, ementa = :ementa, texto = :texto, situacao = :situacao,
                fonte_url = :fonte_url, origem_id = coalesce(:origem_id, origem_id), atualizado_em = datetime('now')
            where id = :id
            """,
            ato,
        )
        novo_id = existente[0]
    else:
        novo_id = con.execute(
            """
            insert into atos (tipo, numero, data, data_publicacao, orgao, categoria, ementa, texto,
                              situacao, fonte_url, origem_id)
            values (:tipo, :numero, :data, :data_publicacao, :orgao, :categoria, :ementa, :texto,
                    :situacao, :fonte_url, :origem_id)
            """,
            ato,
        ).lastrowid
    _gravar_relacoes(con, novo_id, dados)
    con.commit()
    return novo_id


def atualizar(con: sqlite3.Connection, ato_id: int, dados: dict) -> None:
    ato = validar(dados)
    ato["id"] = ato_id
    con.execute(
        """
        update atos set tipo = :tipo, numero = :numero, data = :data,
            data_publicacao = :data_publicacao, orgao = :orgao,
            categoria = :categoria, ementa = :ementa, texto = :texto, situacao = :situacao,
            fonte_url = :fonte_url, atualizado_em = datetime('now')
        where id = :id
        """,
        ato,
    )
    _gravar_relacoes(con, ato_id, dados)
    con.commit()


def excluir(con: sqlite3.Connection, ato_id: int) -> None:
    con.execute("delete from atos where id = ?", (ato_id,))
    con.commit()


# --------------------------------------------------------------------------- relações entre atos


def _referencias(valor: str) -> list[str]:
    """Uma referência por linha (ou separadas por ponto e vírgula)."""
    return [r.strip() for r in re.split(r"[\n;]+", valor or "") if r.strip()]


def _normalizar(texto: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


_REF = re.compile(r"^(?P<tipo>.+?)\s+n\s*[ºo°.]?\s*(?P<numero>[\d.\-]+[a-z]?)(?:\s*/\s*(?P<ano>\d{4})|.*?(?P<ano2>\d{4})\s*$)?", re.I)


def resolver(con: sqlite3.Connection, referencia: str, exceto: int | None = None) -> int | None:
    """Encontra o ato citado. Formatos: "Portaria nº 23/2017" ou "Portaria nº 23, de 21 de dezembro de 2017".

    Só liga quando há exatamente um ato compatível; senão a referência fica como texto.
    """
    m = _REF.match(re.sub(r"\bn\s*[o°.]?\s+(?=\d)", "n ", _normalizar(referencia)))
    if not m:
        return None
    tipo, numero = m.group("tipo").strip(), m.group("numero").replace(".", "")
    ano = m.group("ano") or m.group("ano2")
    candidatos = [
        l["id"]
        for l in con.execute("select id, tipo, numero, data from atos")
        if l["id"] != exceto
        and _normalizar(l["tipo"]) == tipo
        and l["numero"].replace(".", "").lower() == numero
        and (not ano or l["data"][:4] == ano)
    ]
    return candidatos[0] if len(candidatos) == 1 else None


def _gravar_relacoes(con: sqlite3.Connection, ato_id: int, dados: dict) -> None:
    if not any(k in dados for k in RELACOES):
        return  # formulário/CSV sem as colunas de relação: mantém as existentes
    con.execute("delete from relacoes where origem_id = ?", (ato_id,))
    for tipo in RELACOES:
        for ref in _referencias(dados.get(tipo, "")):
            con.execute(
                "insert into relacoes (origem_id, tipo, referencia, destino_id) values (?, ?, ?, ?)",
                (ato_id, tipo, ref, resolver(con, ref, exceto=ato_id)),
            )
    # Referências antigas que apontavam para um ato ainda não cadastrado podem ter sido resolvidas agora.
    for rel in con.execute("select id, origem_id, referencia from relacoes where destino_id is null").fetchall():
        destino = resolver(con, rel["referencia"], exceto=rel["origem_id"])
        if destino:
            con.execute("update relacoes set destino_id = ? where id = ?", (destino, rel["id"]))


def relacoes(con: sqlite3.Connection, ato_id: int) -> list[dict]:
    """Relações do ato nos dois sentidos, prontas para exibir."""
    saida = []
    for l in con.execute(
        """select r.tipo, r.referencia, r.destino_id, a.tipo as d_tipo, a.numero as d_numero, a.data as d_data
           from relacoes r left join atos a on a.id = r.destino_id where r.origem_id = ? order by r.id""",
        (ato_id,),
    ):
        destino = {"tipo": l["d_tipo"], "numero": l["d_numero"], "data": l["d_data"]} if l["destino_id"] else None
        saida.append({
            "rotulo": RELACOES[l["tipo"]][0], "tipo": l["tipo"], "id": l["destino_id"],
            "titulo": titulo(destino) if destino else l["referencia"],
        })
    for l in con.execute(
        """select r.tipo, a.id, a.tipo as o_tipo, a.numero as o_numero, a.data as o_data
           from relacoes r join atos a on a.id = r.origem_id where r.destino_id = ? order by a.data""",
        (ato_id,),
    ):
        saida.append({
            "rotulo": RELACOES[l["tipo"]][1], "tipo": l["tipo"] + "_por", "id": l["id"],
            "titulo": titulo({"tipo": l["o_tipo"], "numero": l["o_numero"], "data": l["o_data"]}),
        })
    return saida


def referencias_texto(con: sqlite3.Connection, ato_id: int) -> dict[str, str]:
    """Relações de saída como texto, para preencher o formulário de edição."""
    out = {k: [] for k in RELACOES}
    for l in con.execute("select tipo, referencia from relacoes where origem_id = ? order by id", (ato_id,)):
        out[l["tipo"]].append(l["referencia"])
    return {k: "\n".join(v) for k, v in out.items()}


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
    mes: int | None = None
    dia: int | None = None
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
    for parte, ini, tam in (("ano", 1, 4), ("mes", 6, 2), ("dia", 9, 2)):
        valor = getattr(f, parte)
        if valor:
            where.append(f"cast(substr({DATA_REF}, {ini}, {tam}) as integer) = :{parte}")
            params[parte] = valor
    clausula = ("where " + " and ".join(where)) if where else ""

    ordem = f.ordem or ("relevancia" if consulta else "recentes")
    if ordem == "relevancia" and consulta:
        order_by = f"bm25(atos_fts, 2.0, 3.0, 4.0, 1.0, 1.0, 1.0), {DATA_REF} desc"
    elif ordem == "antigos":
        order_by = f"{DATA_REF} asc, atos.id asc"
    else:
        order_by = f"{DATA_REF} desc, atos.id desc"

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
        select atos.id, atos.tipo, atos.numero, atos.data, atos.data_publicacao, atos.ano, atos.orgao,
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

    anos = [
        {"valor": l[0], "total": l[1]}
        for l in con.execute(
            f"select cast(substr({DATA_REF}, 1, 4) as integer) as a, count(*) from atos group by a order by a desc"
        )
    ]
    return {
        "categorias": contar("categoria", "categoria collate nocase"),
        "anos": anos,
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
