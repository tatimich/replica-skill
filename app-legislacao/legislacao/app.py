"""Aplicação web: busca de legislação, detalhe do ato, downloads no timbrado e API JSON.

Rodar localmente:
    uvicorn legislacao.app:app --reload

Atrás de um proxy, publicado em um subcaminho do site da marca (ex.: /legislacao):
    uvicorn legislacao.app:app --root-path /legislacao
"""

from __future__ import annotations

import math
import os
import re
import secrets
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode, urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from . import db, timbrado
from .importar import importar_texto
from .marca import carregar

PASTA = Path(__file__).resolve().parent
marca = carregar()

app = FastAPI(title=marca.nome, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.mount("/static", StaticFiles(directory=PASTA / "static"), name="static")
templates = Jinja2Templates(directory=PASTA / "templates")

if marca.cors_origens:
    app.add_middleware(
        CORSMiddleware, allow_origins=marca.cors_origens, allow_methods=["GET"], allow_headers=["*"]
    )


@app.middleware("http")
async def cabecalhos_seguranca(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        f"frame-ancestors {' '.join(marca.frame_ancestors) or chr(39) + 'self' + chr(39)}"
    )
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resposta


@contextmanager
def conexao():
    con = db.conectar()
    try:
        yield con
    finally:
        con.close()


# ------------------------------------------------------------------- filtros de template


def destacar(trecho: str) -> Markup:
    """Converte os marcadores [[ ]] do snippet FTS em <mark>, escapando o resto."""
    seguro = str(escape(trecho or ""))
    return Markup(seguro.replace("[[", "<mark>").replace("]]", "</mark>"))


templates.env.filters.update(
    destacar=destacar, data_curta=db.data_curta, data_extenso=db.data_extenso, titulo=db.titulo
)
templates.env.globals.update(marca=marca, SITUACOES=db.SITUACOES)


def contexto(request: Request, **extra) -> dict:
    embed = request.query_params.get("embed") == "1"
    base = request.scope.get("root_path", "").rstrip("/")
    return {"request": request, "base": base, "embed": embed, **extra}


def url_lista(base: str, params: dict, **mudancas) -> str:
    p = {**params, **mudancas}
    p = {k: v for k, v in p.items() if v not in ("", None, 0) and not (k == "pagina" and v == 1)}
    return f"{base}/" + (f"?{urlencode(p)}" if p else "")


def ler_filtros(
    q: str = "", categoria: str = "", ano: str = "", tipo: str = "", orgao: str = "",
    situacao: str = "", ordem: str = "", pagina: int = Query(1, ge=1), por_pagina: int = Query(20, ge=1, le=100),
) -> db.Filtros:
    ano_int = int(ano) if re.fullmatch(r"\d{4}", ano or "") else None
    if ordem not in ("", "recentes", "antigos", "relevancia"):
        ordem = ""
    return db.Filtros(q.strip()[:200], categoria, ano_int, tipo, orgao, situacao, ordem, pagina, por_pagina)


# ------------------------------------------------------------------- páginas públicas


@app.get("/marca.css")
def marca_css():
    """Cores da marca como variáveis CSS (vêm do marca.toml)."""
    cor = marca.cor_primaria if re.fullmatch(r"#[0-9a-fA-F]{6}", marca.cor_primaria) else "#1F3A5F"
    css = f":root {{ --cor-marca: {cor}; }}\n"
    return Response(css, media_type="text/css", headers={"Cache-Control": "max-age=300"})


@app.get("/", response_class=HTMLResponse)
def lista(request: Request, f: db.Filtros = Depends(ler_filtros)):
    with conexao() as con:
        atos, total = db.buscar(con, f)
        fac = db.facetas(con)
    params = {
        "q": f.q, "categoria": f.categoria, "ano": f.ano or "", "tipo": f.tipo, "orgao": f.orgao,
        "situacao": f.situacao, "ordem": f.ordem,
    }
    if request.query_params.get("embed") == "1":
        params["embed"] = "1"
    paginas = max(1, math.ceil(total / f.por_pagina))
    ctx = contexto(request, f=f, atos=atos, total=total, facetas=fac, params=params,
                   paginas=paginas, url_lista=url_lista)
    return templates.TemplateResponse(request, "lista.html", ctx)


def _ato_ou_404(ato_id: int) -> dict:
    with conexao() as con:
        ato = db.obter(con, ato_id)
    if not ato:
        raise HTTPException(404, "Ato não encontrado")
    return ato


@app.get("/atos/{ato_id}", response_class=HTMLResponse)
def detalhe(request: Request, ato_id: int):
    ato = _ato_ou_404(ato_id)
    voltar = request.headers.get("referer", "")
    if urlparse(voltar).netloc != request.url.netloc:
        voltar = ""
    ctx = contexto(request, ato=ato, paragrafos=timbrado.paragrafos(ato["texto"]), voltar=voltar)
    return templates.TemplateResponse(request, "ato.html", ctx)


def _download(ato: dict, conteudo: bytes, extensao: str, mime: str) -> Response:
    nome = timbrado.nome_arquivo(ato, extensao)
    return Response(conteudo, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@app.get("/atos/{ato_id}/pdf")
def baixar_pdf(ato_id: int):
    ato = _ato_ou_404(ato_id)
    return _download(ato, timbrado.gerar_pdf(ato, marca), "pdf", "application/pdf")


@app.get("/atos/{ato_id}/docx")
def baixar_docx(ato_id: int):
    ato = _ato_ou_404(ato_id)
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return _download(ato, timbrado.gerar_docx(ato, marca), "docx", mime)


# ------------------------------------------------------------------- API JSON (integração)


def _publico(request: Request, ato: dict) -> dict:
    campos = ("id", "tipo", "numero", "data", "orgao", "categoria", "ementa", "situacao", "fonte_url")
    item = {k: ato[k] for k in campos}
    item["titulo"] = db.titulo(ato)
    origem = str(request.base_url).rstrip("/")  # já inclui o root_path
    item["links"] = {
        "pagina": f"{origem}/atos/{ato['id']}",
        "pdf": f"{origem}/atos/{ato['id']}/pdf",
        "docx": f"{origem}/atos/{ato['id']}/docx",
    }
    return item


@app.get("/api/atos")
def api_lista(request: Request, f: db.Filtros = Depends(ler_filtros)):
    with conexao() as con:
        atos, total = db.buscar(con, f)
    return {
        "total": total,
        "pagina": f.pagina,
        "por_pagina": f.por_pagina,
        "itens": [_publico(request, a) for a in atos],
    }


@app.get("/api/atos/{ato_id}")
def api_ato(request: Request, ato_id: int):
    ato = _ato_ou_404(ato_id)
    item = _publico(request, ato)
    item["texto"] = ato["texto"]
    return item


@app.get("/api/facetas")
def api_facetas():
    with conexao() as con:
        return db.facetas(con)


# ------------------------------------------------------------------- administração

seguranca = HTTPBasic(auto_error=False)


def admin(request: Request, cred: HTTPBasicCredentials | None = Depends(seguranca)) -> None:
    senha = os.environ.get("ADMIN_SENHA", "")
    if not senha:
        raise HTTPException(404)  # administração desligada sem senha configurada
    ok = cred is not None and secrets.compare_digest(cred.username.encode(), b"admin") and secrets.compare_digest(
        cred.password.encode(), senha.encode()
    )
    if not ok:
        raise HTTPException(401, headers={"WWW-Authenticate": 'Basic realm="admin"'})
    if request.method == "POST":
        # Proteção contra envio de formulário a partir de outro site (CSRF).
        origem = request.headers.get("origin") or request.headers.get("referer") or ""
        if origem and urlparse(origem).netloc != request.url.netloc:
            raise HTTPException(403, "Origem não permitida")


FORM_CAMPOS = db.CAMPOS


@app.get("/admin", response_class=HTMLResponse, dependencies=[Depends(admin)])
def admin_inicio(request: Request, f: db.Filtros = Depends(ler_filtros)):
    with conexao() as con:
        atos, total = db.buscar(con, f)
    return templates.TemplateResponse(request, "admin_lista.html", contexto(request, atos=atos, total=total, f=f))


@app.get("/admin/novo", response_class=HTMLResponse, dependencies=[Depends(admin)])
def admin_novo(request: Request):
    return templates.TemplateResponse(request, "admin_form.html", contexto(request, ato={}, erro=""))


@app.get("/admin/atos/{ato_id}", response_class=HTMLResponse, dependencies=[Depends(admin)])
def admin_editar(request: Request, ato_id: int):
    return templates.TemplateResponse(request, "admin_form.html", contexto(request, ato=_ato_ou_404(ato_id), erro=""))


async def _form(request: Request) -> dict:
    form = await request.form()
    return {c: str(form.get(c, "")) for c in FORM_CAMPOS}


@app.post("/admin/novo", dependencies=[Depends(admin)])
async def admin_criar(request: Request):
    dados = await _form(request)
    try:
        with conexao() as con:
            novo = db.salvar(con, dados)
    except db.ErroValidacao as e:
        return templates.TemplateResponse(request, "admin_form.html", contexto(request, ato=dados, erro=str(e)), status_code=422)
    return RedirectResponse(f"{contexto(request)['base']}/atos/{novo}", status_code=303)


@app.post("/admin/atos/{ato_id}", dependencies=[Depends(admin)])
async def admin_salvar(request: Request, ato_id: int):
    _ato_ou_404(ato_id)
    dados = await _form(request)
    try:
        with conexao() as con:
            db.atualizar(con, ato_id, dados)
    except db.ErroValidacao as e:
        dados["id"] = ato_id
        return templates.TemplateResponse(request, "admin_form.html", contexto(request, ato=dados, erro=str(e)), status_code=422)
    return RedirectResponse(f"{contexto(request)['base']}/atos/{ato_id}", status_code=303)


@app.post("/admin/atos/{ato_id}/excluir", dependencies=[Depends(admin)])
def admin_excluir(request: Request, ato_id: int):
    with conexao() as con:
        db.excluir(con, ato_id)
    return RedirectResponse(f"{contexto(request)['base']}/admin", status_code=303)


@app.get("/admin/importar", response_class=HTMLResponse, dependencies=[Depends(admin)])
def admin_importar_form(request: Request):
    return templates.TemplateResponse(request, "admin_importar.html", contexto(request, resultado=None))


@app.post("/admin/importar", response_class=HTMLResponse, dependencies=[Depends(admin)])
async def admin_importar(request: Request, arquivo: UploadFile):
    bruto = await arquivo.read(10 * 1024 * 1024 + 1)
    if len(bruto) > 10 * 1024 * 1024:
        resultado = (0, ["Arquivo maior que 10 MB."])
    else:
        try:
            texto = bruto.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = bruto.decode("latin-1")
        with conexao() as con:
            resultado = importar_texto(con, texto)
    return templates.TemplateResponse(request, "admin_importar.html", contexto(request, resultado=resultado))


# ------------------------------------------------------------------- erros


@app.exception_handler(404)
async def nao_encontrado(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Não encontrado"}, status_code=404)
    return templates.TemplateResponse(request, "erro.html", contexto(request, mensagem="Página não encontrada."), status_code=404)
