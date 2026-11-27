import io
import zipfile

import pytest
from fastapi.testclient import TestClient

AMOSTRA = """tipo,numero,data,orgao,categoria,ementa,situacao,fonte_url,texto
Lei,1.000,2020-03-05,Órgão A,Regulação,Dispõe sobre regulação de cursos.,vigente,https://exemplo.gov.br/l1000,"Art. 1º A regulação dos cursos superiores segue este texto.
Art. 2º Revogam-se as disposições em contrário."
Portaria,25,2021-07-01,Órgão B,Avaliação,Estabelece indicadores de avaliação.,revogado,,
Decreto,7,05/01/2019,Órgão A,Regulação,Trata de credenciamento.,alterado,,Texto sobre credenciamento institucional.
"""


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGISLACAO_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("ADMIN_SENHA", "segredo")
    from legislacao import db
    from legislacao.importar import importar_texto
    from legislacao.app import app

    con = db.conectar()
    ok, erros = importar_texto(con, AMOSTRA)
    assert (ok, erros) == (3, [])
    con.close()
    return TestClient(app)


def test_lista_e_facetas(cliente):
    r = cliente.get("/")
    assert r.status_code == 200
    assert "3</strong> atos encontrados" in r.text
    f = cliente.get("/api/facetas").json()
    assert {c["valor"]: c["total"] for c in f["categorias"]} == {"Avaliação": 1, "Regulação": 2}
    assert [a["valor"] for a in f["anos"]] == [2021, 2020, 2019]


def test_filtro_categoria_e_ano(cliente):
    j = cliente.get("/api/atos", params={"categoria": "Regulação", "ano": "2019"}).json()
    assert j["total"] == 1 and j["itens"][0]["tipo"] == "Decreto"
    assert j["itens"][0]["data"] == "2019-01-05"  # data DD/MM/AAAA normalizada


def test_busca_sem_acento_e_prefixo(cliente):
    # "regulacao" (sem acento) acha a Lei pela ementa/texto e o Decreto pela categoria
    j = cliente.get("/api/atos", params={"q": "regulacao"}).json()
    assert j["total"] == 2 and j["itens"][0]["numero"] == "1.000"  # mais relevante primeiro
    j = cliente.get("/api/atos", params={"q": "credencia"}).json()
    assert j["total"] == 1
    # operadores e aspas soltas não quebram a busca
    assert cliente.get("/api/atos", params={"q": 'AND OR "( *'}).status_code == 200


def test_trecho_destacado_e_escapado(cliente):
    r = cliente.get("/", params={"q": "regulação"})
    assert "<mark>" in r.text


def test_ordem(cliente):
    j = cliente.get("/api/atos", params={"ordem": "antigos"}).json()
    assert [i["data"][:4] for i in j["itens"]] == ["2019", "2020", "2021"]


def test_detalhe_e_404(cliente):
    r = cliente.get("/atos/1")
    assert r.status_code == 200 and "Lei nº 1.000, de 5 de março de 2020" in r.text
    assert cliente.get("/atos/999").status_code == 404
    assert cliente.get("/api/atos/999").status_code == 404


def test_download_pdf_timbrado(cliente):
    r = cliente.get("/atos/1/pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert 'filename="lei-1.000-2020.pdf"' in r.headers["content-disposition"]


def test_download_docx_timbrado(cliente):
    from legislacao.marca import carregar

    r = cliente.get("/atos/1/docx")
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        cabecalhos = "".join(z.read(n).decode() for n in z.namelist() if n.startswith("word/header"))
        rodapes = "".join(z.read(n).decode() for n in z.namelist() if n.startswith("word/footer"))
        corpo = z.read("word/document.xml").decode()
        imagens = [n for n in z.namelist() if n.startswith("word/media/")]
    marca = carregar()
    if marca.caminho_logo:
        assert "<pic:pic" in cabecalhos and imagens  # logo no timbrado
    else:
        assert marca.nome in cabecalhos
    assert marca.site in rodapes and "PAGE" in rodapes
    assert "A regulação dos cursos superiores" in corpo


def test_logo_da_marca(cliente):
    r = cliente.get("/marca/logo.png")
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")


def test_embed_e_cabecalhos(cliente):
    r = cliente.get("/", params={"embed": "1"})
    assert 'class="topo"' not in r.text and "altura.js" in r.text
    assert "frame-ancestors" in r.headers["content-security-policy"]
    assert cliente.get("/static/embed.js").status_code == 200


def test_admin_protegido(cliente):
    assert cliente.get("/admin").status_code == 401
    assert cliente.get("/admin", auth=("admin", "errada")).status_code == 401
    assert cliente.get("/admin", auth=("admin", "segredo")).status_code == 200


def test_admin_cria_edita_exclui(cliente):
    auth = ("admin", "segredo")
    dados = {"tipo": "Resolução", "numero": "9", "data": "2024-02-02", "ementa": "Nova regra.", "situacao": "vigente"}
    r = cliente.post("/admin/novo", data=dados, auth=auth, follow_redirects=False)
    assert r.status_code == 303
    novo = r.headers["location"].rsplit("/", 1)[1]
    dados["ementa"] = "Regra alterada."
    assert cliente.post(f"/admin/atos/{novo}", data=dados, auth=auth, follow_redirects=False).status_code == 303
    assert cliente.get(f"/api/atos/{novo}").json()["ementa"] == "Regra alterada."
    r = cliente.post("/admin/novo", data={**dados, "data": "ontem"}, auth=auth)
    assert r.status_code == 422 and "Data inválida" in r.text
    r = cliente.post("/admin/novo", data=dados, auth=auth, headers={"origin": "https://outro.site"})
    assert r.status_code == 403
    assert cliente.post(f"/admin/atos/{novo}/excluir", auth=auth, follow_redirects=False).status_code == 303
    assert cliente.get(f"/api/atos/{novo}").status_code == 404


def test_admin_desligado_sem_senha(cliente, monkeypatch):
    monkeypatch.delenv("ADMIN_SENHA")
    assert cliente.get("/admin", auth=("admin", "segredo")).status_code == 404


def test_importar_csv_ponto_e_virgula_com_erro(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGISLACAO_DB", str(tmp_path / "x.db"))
    from legislacao import db
    from legislacao.importar import importar_texto

    con = db.conectar()
    ok, erros = importar_texto(con, "tipo;data;ementa\nLei;2020-01-01;Ok\nLei;xx;Ruim\n")
    assert ok == 1 and erros and "Linha 3" in erros[0]


def test_data_publicacao_e_filtros_mes_dia(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGISLACAO_DB", str(tmp_path / "m.db"))
    from legislacao import db
    from legislacao.importar import importar_texto

    con = db.conectar()
    csv = (
        "tipo,numero,data,data_publicacao,ementa\n"
        "Portaria,1,2023-12-28,2024-01-03,Publicada em janeiro.\n"
        "Portaria,2,2024-02-10,,Sem data de publicação.\n"
    )
    assert importar_texto(con, csv) == (2, [])
    # ano/mês/dia usam a data do D.O.U. quando existe
    _, total = db.buscar(con, db.Filtros(ano=2024, mes=1, dia=3))
    assert total == 1
    itens, total = db.buscar(con, db.Filtros(ano=2024))
    assert total == 2 and [i["numero"] for i in itens] == ["2", "1"]
    assert [a["valor"] for a in db.facetas(con)["anos"]] == [2024]


def test_relacoes_resolvidas_nos_dois_sentidos(tmp_path, monkeypatch):
    monkeypatch.setenv("LEGISLACAO_DB", str(tmp_path / "r.db"))
    from legislacao import db
    from legislacao.importar import importar_texto

    con = db.conectar()
    # o ato que revoga vem antes do revogado: a ligação é feita quando o revogado chega
    csv = (
        "tipo,numero,data,ementa,revoga,altera\n"
        "Portaria,40,2018-01-01,Nova.,Portaria nº 23/2017; Portaria nº 999/2001,\"Decreto nº 9.235, de 15 de dezembro de 2017\"\n"
        "Portaria,23,2017-12-21,Antiga.,,\n"
        "Decreto,9.235,2017-12-15,Decreto.,,\n"
    )
    assert importar_texto(con, csv) == (3, [])
    nova, antiga, decreto = 1, 2, 3
    rel = db.relacoes(con, nova)
    assert [(r["rotulo"], r["id"]) for r in rel] == [("Revoga", antiga), ("Revoga", None), ("Altera", decreto)]
    assert rel[1]["titulo"] == "Portaria nº 999/2001"  # não cadastrada: fica como texto
    assert [(r["rotulo"], r["id"]) for r in db.relacoes(con, antiga)] == [("Revogado por", nova)]
    assert db.referencias_texto(con, nova)["revoga"] == "Portaria nº 23/2017\nPortaria nº 999/2001"


def test_migra_banco_antigo(tmp_path):
    import sqlite3

    from legislacao import db

    caminho = tmp_path / "antigo.db"
    velho = sqlite3.connect(caminho)
    velho.execute("create table atos (id integer primary key, tipo text not null, numero text not null default '', "
                  "data text not null, ano integer generated always as (cast(substr(data,1,4) as integer)) stored, "
                  "orgao text not null default '', categoria text not null default '', ementa text not null, "
                  "texto text not null default '', situacao text not null default 'sem_informacao', "
                  "fonte_url text not null default '', criado_em text, atualizado_em text)")
    velho.commit()
    velho.close()
    con = db.conectar(caminho)
    assert "data_publicacao" in {l[1] for l in con.execute("pragma table_info(atos)")}


def test_detalhe_mostra_relacoes_e_contato(cliente):
    from legislacao.marca import carregar

    auth = ("admin", "segredo")
    dados = {"tipo": "Portaria", "numero": "50", "data": "2022-01-01", "data_publicacao": "2022-01-04",
             "ementa": "Revoga a lei de teste.", "revoga": "Lei nº 1.000/2020", "altera": ""}
    r = cliente.post("/admin/novo", data=dados, auth=auth, follow_redirects=False)
    novo = r.headers["location"].rsplit("/", 1)[1]
    pagina = cliente.get(f"/atos/{novo}").text
    assert "Revoga" in pagina and 'href="/atos/1"' in pagina and "4 de janeiro de 2022" in pagina
    assert "Revogado por" in cliente.get("/atos/1").text
    if carregar().contato:
        assert "mailto:" + carregar().contato in pagina
    api = cliente.get(f"/api/atos/{novo}").json()
    assert api["data_publicacao"] == "2022-01-04" and api["relacoes"][0]["id"] == 1
    assert cliente.get(f"/atos/{novo}/pdf").status_code == 200
    assert cliente.get(f"/atos/{novo}/docx").status_code == 200
