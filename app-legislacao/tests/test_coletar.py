"""Testes do coletor com um portal simulado (mesmo formato de página que o Monitor lê)."""

import json
from datetime import date

import pytest

from legislacao import coletar, db

EDICAO = [
    {"classPK": "101", "urlTitle": "portaria-n-1.234-de-20-de-novembro-de-2026-101", "artType": "Portaria",
     "title": "PORTARIA Nº 1.234, DE 20 DE NOVEMBRO DE 2026", "pubDate": "21/11/2026", "pubName": "DO1",
     "hierarchyStr": "Ministério da Educação/Secretaria de Regulação e Supervisão da Educação Superior"},
    {"classPK": "102", "urlTitle": "decreto-n-12.000-102", "artType": "Decreto",
     "title": "DECRETO Nº 12.000", "pubDate": "21/11/2026", "pubName": "DO1",
     "hierarchyStr": "Presidência da República"},
    {"classPK": "103", "urlTitle": "decreto-n-12.001-103", "artType": "Decreto",
     "title": "DECRETO Nº 12.001", "pubDate": "21/11/2026", "pubName": "DO1",
     "hierarchyStr": "Presidência da República"},
    {"classPK": "104", "urlTitle": "portaria-saude-104", "artType": "Portaria",
     "title": "PORTARIA Nº 9", "pubDate": "21/11/2026", "pubName": "DO1",
     "hierarchyStr": "Ministério da Saúde/Gabinete do Ministro"},
    {"classPK": "105", "urlTitle": "despacho-105", "artType": "Despacho",
     "title": "DESPACHO", "pubDate": "21/11/2026", "pubName": "DO1",
     "hierarchyStr": "Ministério da Educação/Conselho Nacional de Educação/Câmara de Educação Superior"},
    {"classPK": "106", "urlTitle": "despacho-106", "artType": "Despacho",
     "title": "DESPACHO", "pubDate": "21/11/2026", "pubName": "DO1",
     "hierarchyStr": "Ministério da Educação/Conselho Nacional de Educação/Câmara de Educação Superior"},
]


def pagina_edicao(itens):
    return ('<html><script id="params" type="application/json">'
            + json.dumps({"jsonArray": itens}) + "</script></html>")


def pagina_materia(titulo, ementa, paragrafos, publicado="21/11/2026"):
    ps = "".join(f'<p class="dou-paragraph">{p}</p>' for p in paragrafos)
    em = f'<p class="ementa">{ementa}</p>' if ementa else ""
    return (f'<span class="publicado-dou-data">{publicado}</span>'
            f'<article><div class="texto-dou"><p class="identifica">{titulo}</p>{em}{ps}'
            '<table><tr><td><p>Curso</p></td><td><p>Vagas</p></td></tr><tr><td><p>Direito</p></td><td><p>100</p></td></tr></table>'
            '<p class="assina">FULANO DE TAL</p></div></article>')


MATERIAS = {
    "portaria-n-1.234-de-20-de-novembro-de-2026-101": pagina_materia(
        "PORTARIA Nº 1.234, DE 20 DE NOVEMBRO DE 2026", "Dispõe sobre o credenciamento de instituições.",
        ["Art. 1º Fica estabelecido o procedimento.", "Art. 2º Esta Portaria entra em vigor na data de sua publicação."]),
    "decreto-n-12.000-102": pagina_materia(
        "DECRETO Nº 12.000, DE 19 DE NOVEMBRO DE 2026", "Altera regras do ensino superior.",
        ["Art. 1º As instituições de ensino superior observarão este Decreto."]),
    "decreto-n-12.001-103": pagina_materia(
        "DECRETO Nº 12.001, DE 19 DE NOVEMBRO DE 2026", "Dispõe sobre rodovias federais.", ["Art. 1º Rodovias."]),
    "despacho-105": pagina_materia("DESPACHO", "", ["Homologo o Parecer CNE/CES nº 10/2026, que trata das diretrizes curriculares do curso de Direito, conforme os autos."]),
    "despacho-106": pagina_materia("DESPACHO", "", ["Homologo o Parecer CNE/CES nº 11/2026, sobre outro assunto de interesse das instituições."]),
}


@pytest.fixture()
def portal(monkeypatch, tmp_path):
    monkeypatch.setenv("LEGISLACAO_DB", str(tmp_path / "c.db"))
    chamadas = []

    def falso_baixar(url, cfg):
        chamadas.append(url)
        if "leiturajornal" in url:
            if "secao=do1&" in url + "&":
                return pagina_edicao(EDICAO)
            raise coletar.ErroColeta(f"{url}: HTTP 404")
        slug = url.rsplit("/-/", 1)[1]
        return MATERIAS[slug]

    monkeypatch.setattr(coletar, "baixar", falso_baixar)
    monkeypatch.setattr(coletar.time, "sleep", lambda s: None)
    return chamadas


def test_coleta_um_dia(portal):
    cfg = coletar.carregar_config()
    con = db.conectar()
    n = coletar.coletar_dia(con, cfg, date(2026, 11, 21), log=lambda m: None)
    assert n == 4  # portaria MEC, decreto sobre ensino superior, 2 despachos do CNE
    atos = {a["origem_id"]: a for a in map(dict, con.execute("select * from atos"))}
    assert set(atos) == {"dou:101", "dou:102", "dou:105", "dou:106"}

    p = atos["dou:101"]
    assert (p["tipo"], p["numero"], p["data"], p["data_publicacao"]) == ("Portaria", "1.234", "2026-11-20", "2026-11-21")
    assert p["orgao"] == "Secretaria de Regulação e Supervisão da Educação Superior"
    assert p["categoria"] == "Regulação e Supervisão"
    assert p["ementa"] == "Dispõe sobre o credenciamento de instituições."
    assert "Art. 2º Esta Portaria" in p["texto"] and "Direito | 100" in p["texto"] and "FULANO DE TAL" in p["texto"]
    assert p["fonte_url"] == "https://www.in.gov.br/web/dou/-/portaria-n-1.234-de-20-de-novembro-de-2026-101"

    # sem ementa destacada: usa o início do texto real
    assert atos["dou:105"]["ementa"].startswith("Homologo o Parecer CNE/CES nº 10/2026")
    assert atos["dou:105"]["categoria"] == "Diretrizes Curriculares"
    # outro órgão (Saúde) nem é aberto
    assert not any("portaria-saude-104" in u for u in portal)


def test_retoma_e_nao_duplica(portal):
    cfg = coletar.carregar_config()
    con = db.conectar()
    coletar.coletar_dia(con, cfg, date(2026, 11, 21), log=lambda m: None)
    antes = len(portal)
    assert coletar.coletar_dia(con, cfg, date(2026, 11, 21), log=lambda m: None) == 0  # já feito
    assert len(portal) == antes
    coletar.coletar_dia(con, cfg, date(2026, 11, 21), refazer=True, log=lambda m: None)
    assert con.execute("select count(*) from atos").fetchone()[0] == 4
    falhas = con.execute("select count(*) from coletas where erro != ''").fetchone()[0]
    assert falhas == 0  # 404 em edições extras não é erro


def test_numero_e_data():
    assert coletar.numero_e_data("RESOLUÇÃO CNE/CES Nº 3, DE 1º DE MARÇO DE 2026") == ("3", "2026-03-01")
    assert coletar.numero_e_data("LEI Nº 14.945, DE 31 DE JULHO DE 2024") == ("14.945", "2024-07-31")
    assert coletar.numero_e_data("DESPACHO") == ("", "")


def test_falha_na_edicao_principal_fica_registrada(monkeypatch, tmp_path):
    monkeypatch.setenv("LEGISLACAO_DB", str(tmp_path / "e.db"))
    monkeypatch.setattr(coletar, "baixar", lambda url, cfg: (_ for _ in ()).throw(coletar.ErroColeta("timeout")))
    monkeypatch.setattr(coletar.time, "sleep", lambda s: None)
    con = db.conectar()
    coletar.coletar_dia(con, coletar.carregar_config(), date(2026, 11, 21), log=lambda m: None)
    erro = con.execute("select erro from coletas where secao = 'do1'").fetchone()[0]
    assert "timeout" in erro
