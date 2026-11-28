"""Coleta automática de atos no Diário Oficial da União (portal in.gov.br).

Usa o mesmo caminho de leitura do Monitor da Educação: a página de leitura da edição do dia
(/leiturajornal) traz a lista de matérias em JSON; cada matéria é aberta na página oficial
(/web/dou/-/<urlTitle>) para extrair título, ementa e texto integral.

Uso:
    python -m legislacao.coletar                         # ontem e hoje (rotina diária)
    python -m legislacao.coletar --data 2026-11-26       # um dia
    python -m legislacao.coletar --de 2025-01-01 --ate 2026-11-27   # carga histórica (retoma de onde parou)
    python -m legislacao.coletar --de 2025-01-01 --refazer          # recoleta dias já feitos

Precisa rodar numa máquina com acesso ao portal do D.O.U. (o portal recusa acessos de alguns
servidores fora do Brasil).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import tomllib
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

from . import db

RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PADRAO = RAIZ / "coletor.toml"
MESES = {m: i for i, m in enumerate(
    ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
     "setembro", "outubro", "novembro", "dezembro"], start=1)}


# ------------------------------------------------------------------- configuração


@dataclass
class Config:
    base: str = "https://www.in.gov.br"
    secoes: list[str] = field(default_factory=lambda: ["do1"])
    pausa: float = 1.5
    tentativas: int = 4
    tempo_limite: int = 120
    orgaos: list[str] = field(default_factory=list)
    orgaos_condicionais: list[str] = field(default_factory=list)
    termos_condicionais: list[str] = field(default_factory=list)
    tipos_ignorados: list[str] = field(default_factory=list)
    categorias: list[tuple[str, list[str]]] = field(default_factory=list)


def carregar_config(caminho: Path | str | None = None) -> Config:
    with open(caminho or CONFIG_PADRAO, "rb") as arq:
        d = tomllib.load(arq)
    f, fl = d.get("fonte", {}), d.get("filtro", {})
    return Config(
        base=f.get("base", "https://www.in.gov.br").rstrip("/"),
        secoes=list(f.get("secoes", ["do1"])),
        pausa=float(f.get("pausa_segundos", 1.5)),
        tentativas=int(f.get("tentativas", 4)),
        tempo_limite=int(f.get("tempo_limite_segundos", 120)),
        orgaos=[dobrar(x) for x in fl.get("orgaos", [])],
        orgaos_condicionais=[dobrar(x) for x in fl.get("orgaos_condicionais", [])],
        termos_condicionais=[dobrar(x) for x in fl.get("termos_condicionais", [])],
        tipos_ignorados=[dobrar(x) for x in fl.get("tipos_ignorados", [])],
        categorias=[(c["nome"], [dobrar(t) for t in c.get("termos", [])]) for c in d.get("categorias", [])],
    )


# ------------------------------------------------------------------- texto


def dobrar(valor: str) -> str:
    """Minúsculas, sem acento, sem tags e com espaços normalizados (para comparar)."""
    valor = re.sub(r"<[^>]+>", " ", valor or "")
    valor = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"\s+", " ", valor).strip()


def limpar(valor: str) -> str:
    valor = html.unescape(valor or "").replace("\xa0", " ")
    valor = re.sub(r"[ \t\r\f\v]+", " ", valor)
    return re.sub(r"\n\s*", "\n", valor).strip()


def sem_tags(valor: str) -> str:
    return limpar(re.sub(r"<[^>]+>", "", valor or ""))


def trecho_entre(texto: str, inicio: str, fim: str) -> str:
    m = re.search(inicio, texto, flags=re.I | re.S)
    if not m:
        return ""
    resto = texto[m.end():]
    f = re.search(fim, resto, flags=re.I | re.S)
    return resto[: f.start()] if f else resto


# ------------------------------------------------------------------- acesso ao portal


class ErroColeta(RuntimeError):
    pass


def baixar(url: str, cfg: Config) -> str:
    ultimo = ""
    for tentativa in range(1, cfg.tentativas + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BibliotecaLegislacao/1.0)",
            "Accept-Language": "pt-BR,pt;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=cfg.tempo_limite) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            ultimo = f"HTTP {e.code}"
            if e.code == 404:
                break  # página inexistente: não adianta repetir
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            ultimo = str(e)
        time.sleep(cfg.pausa * tentativa)
    raise ErroColeta(f"{url}: {ultimo}")


def url_edicao(cfg: Config, dia: date, secao: str) -> str:
    return f"{cfg.base}/leiturajornal?data={dia.strftime('%d-%m-%Y')}&secao={secao}"


def url_materia(cfg: Config, item: dict) -> str:
    return f"{cfg.base}/web/dou/-/{item.get('urlTitle')}"


def materias_da_edicao(pagina: str) -> list[dict]:
    """Lista de matérias que o portal embute na página de leitura da edição."""
    m = re.search(r'<script id="params" type="application/json">\s*(.*?)\s*</script>', pagina, flags=re.S)
    if not m:
        return []
    try:
        return [x for x in (json.loads(m.group(1)).get("jsonArray") or []) if isinstance(x, dict)]
    except json.JSONDecodeError:
        return []


def id_origem(item: dict) -> str:
    if item.get("classPK"):
        return f"dou:{item['classPK']}"
    m = re.search(r"-(\d+)$", str(item.get("urlTitle") or ""))
    return f"dou:{m.group(1) if m else item.get('urlTitle')}"


# ------------------------------------------------------------------- filtro e classificação


def acompanhado(item: dict, cfg: Config, texto: str = "") -> bool | None:
    """True/False quando já dá para decidir; None quando depende do texto (órgão condicional)."""
    hierarquia = dobrar(item.get("hierarchyStr") or "")
    if dobrar(item.get("artType") or "") in cfg.tipos_ignorados:
        return False
    if any(o in hierarquia for o in cfg.orgaos):
        return True
    if any(o in hierarquia for o in cfg.orgaos_condicionais):
        if not texto:
            return None
        alvo = dobrar(texto)
        return any(t in alvo for t in cfg.termos_condicionais)
    return False


def categorizar(cfg: Config, *textos: str) -> str:
    alvo = " ".join(dobrar(t) for t in textos)
    for nome, termos in cfg.categorias:
        if any(re.search(rf"\b{re.escape(t)}\b", alvo) for t in termos):
            return nome
    return "Outros"


# ------------------------------------------------------------------- página da matéria


class _Texto(HTMLParser):
    """Separa título (identifica), ementa, parágrafos, assinatura e tabelas do texto do D.O.U."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes: list[tuple[str, str]] = []
        self._p: dict | None = None
        self._tabela: list[list[str]] | None = None
        self._linha: list[str] | None = None
        self._celula: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        classe = dict(attrs).get("class") or ""
        if tag == "table":
            self._tabela = []
        elif tag == "tr" and self._tabela is not None:
            self._linha = []
        elif tag in ("td", "th") and self._linha is not None:
            self._celula = []
        elif tag == "p":
            self._p = {"classe": classe, "texto": []}
        elif tag == "br" and self._p is not None:
            self._p["texto"].append("\n")

    def handle_endtag(self, tag):
        if tag == "p" and self._p is not None:
            texto = limpar("".join(self._p["texto"]))
            if texto:
                if self._celula is not None:
                    self._celula.append(texto)
                else:
                    c = self._p["classe"]
                    tipo = ("titulo" if "identifica" in c else "ementa" if "ementa" in c
                            else "assinatura" if "assina" in c else "paragrafo")
                    self.partes.append((tipo, texto))
            self._p = None
        elif tag in ("td", "th") and self._celula is not None:
            self._linha.append(limpar(" ".join(self._celula)))
            self._celula = None
        elif tag == "tr" and self._linha is not None:
            if any(self._linha):
                self._tabela.append(self._linha)
            self._linha = None
        elif tag == "table" and self._tabela is not None:
            for linha in self._tabela:
                self.partes.append(("paragrafo", " | ".join(linha)))
            self._tabela = None

    def handle_data(self, data):
        if self._p is not None:
            self._p["texto"].append(data)
        elif self._celula is not None:
            self._celula.append(data)


_TITULO = re.compile(
    r"n[º°o.]?\s*(?P<numero>[\d.\-/]+[a-z]?)\s*,?\s*de\s+(?P<dia>\d{1,2})[º°o]?\s+de\s+(?P<mes>[a-zç]+)\s+de\s+(?P<ano>\d{4})",
    re.I,
)


def numero_e_data(titulo: str) -> tuple[str, str]:
    """'PORTARIA Nº 1.234, DE 20 DE NOVEMBRO DE 2026' -> ('1.234', '2026-11-20')."""
    m = _TITULO.search(titulo or "")
    if not m:
        return "", ""
    mes = MESES.get(dobrar(m.group("mes")))
    try:
        data = date(int(m.group("ano")), mes, int(m.group("dia"))).isoformat() if mes else ""
    except ValueError:
        data = ""
    return m.group("numero").rstrip(".-/"), data


def ler_materia(pagina: str, item: dict, cfg: Config) -> dict:
    """Converte a página oficial da matéria nos campos do ato."""
    corpo = trecho_entre(pagina, r'<div class="texto-dou">', r"</article>")
    leitor = _Texto()
    leitor.feed(corpo)
    titulos = [t for k, t in leitor.partes if k == "titulo"]
    titulo = next((t for t in titulos if dobrar(t) not in {"edital", "editais"}), titulos[0] if titulos else "")
    titulo = titulo or sem_tags(item.get("title") or "")
    ementa = " ".join(t for k, t in leitor.partes if k == "ementa")
    corpo_texto = [t for k, t in leitor.partes if k in ("paragrafo", "assinatura")]
    if not ementa:
        # Muitas portarias não têm ementa destacada: usa o início do texto (trecho real, sem resumo inventado).
        primeiro = next((t for t in corpo_texto if len(t) > 40), corpo_texto[0] if corpo_texto else titulo)
        ementa = primeiro if len(primeiro) <= 400 else primeiro[:397].rsplit(" ", 1)[0] + "…"

    publicado = limpar(trecho_entre(pagina, r'<span class="publicado-dou-data">', r"</span>"))
    pub = item.get("pubDate") or publicado
    try:
        data_pub = datetime.strptime(pub.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        data_pub = ""
    numero, data_ato = numero_e_data(titulo)
    hierarquia = sem_tags(item.get("hierarchyStr") or "") or sem_tags(
        trecho_entre(pagina, r'<span class="orgao-dou-data">', r"</span>"))
    orgao = hierarquia.split("/")[-1].strip() if hierarquia else ""
    tipo = sem_tags(item.get("artType") or "") or (titulo.split(" N")[0].title() if titulo else "Ato")

    return {
        "tipo": tipo[:1].upper() + tipo[1:],
        "numero": numero,
        "data": data_ato or data_pub,
        "data_publicacao": data_pub,
        "orgao": orgao,
        "categoria": categorizar(cfg, hierarquia, titulo, ementa),
        "ementa": ementa,
        "texto": "\n".join([titulo] + corpo_texto) if titulo else "\n".join(corpo_texto),
        "situacao": "sem_informacao",
        "fonte_url": url_materia(cfg, item),
    }


# ------------------------------------------------------------------- coleta


def coletar_dia(con, cfg: Config, dia: date, refazer: bool = False, log=print) -> int:
    """Coleta todas as seções configuradas de um dia. Devolve quantos atos entraram ou foram atualizados."""
    total_incluidos = 0
    for secao in cfg.secoes:
        feito = con.execute(
            "select 1 from coletas where data = ? and secao = ? and erro = ''", (dia.isoformat(), secao)
        ).fetchone()
        if feito and not refazer:
            continue
        erro, itens, incluidos = "", [], 0
        try:
            itens = materias_da_edicao(baixar(url_edicao(cfg, dia, secao), cfg))
        except ErroColeta as e:
            # Edições extras não existem na maioria dos dias: 404 numa seção extra não é erro.
            if "HTTP 404" not in str(e) or secao == "do1":
                erro = str(e)
        for item in itens:
            decisao = acompanhado(item, cfg)
            if decisao is False:
                continue
            time.sleep(cfg.pausa)
            try:
                pagina = baixar(url_materia(cfg, item), cfg)
            except ErroColeta as e:
                erro = (erro + "; " if erro else "") + str(e)
                continue
            ato = ler_materia(pagina, item, cfg)
            if decisao is None and not acompanhado(item, cfg, ato["ementa"] + " " + ato["texto"]):
                continue
            try:
                db.salvar(con, ato, origem_id=id_origem(item))
                incluidos += 1
            except db.ErroValidacao as e:
                erro = (erro + "; " if erro else "") + f"{item.get('urlTitle')}: {e}"
        con.execute(
            """insert into coletas (data, secao, total, incluidos, erro, em) values (?, ?, ?, ?, ?, datetime('now'))
               on conflict (data, secao) do update set total = excluded.total, incluidos = excluded.incluidos,
               erro = excluded.erro, em = excluded.em""",
            (dia.isoformat(), secao, len(itens), incluidos, erro[:2000]),
        )
        con.commit()
        if itens or erro:
            log(f"{dia.isoformat()} {secao}: {len(itens)} matérias, {incluidos} incluídas" + (f" | ERRO: {erro[:200]}" if erro else ""))
        total_incluidos += incluidos
        time.sleep(cfg.pausa)
    return total_incluidos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Coleta atos do D.O.U. para a biblioteca de legislação.")
    ap.add_argument("--data", help="um dia (AAAA-MM-DD)")
    ap.add_argument("--de", help="início do período (AAAA-MM-DD)")
    ap.add_argument("--ate", help="fim do período (AAAA-MM-DD); padrão: hoje")
    ap.add_argument("--refazer", action="store_true", help="recoleta dias já coletados")
    ap.add_argument("--config", help="arquivo de configuração (padrão: coletor.toml)")
    a = ap.parse_args(argv)

    hoje = date.today()
    if a.data:
        inicio = fim = date.fromisoformat(a.data)
    elif a.de:
        inicio, fim = date.fromisoformat(a.de), date.fromisoformat(a.ate) if a.ate else hoje
    else:
        inicio, fim = hoje - timedelta(days=1), hoje  # rotina diária: ontem (extras) e hoje
    cfg = carregar_config(a.config)
    con = db.conectar()
    total, dia = 0, inicio
    # A rotina diária sempre recoleta ontem e hoje (edições extras saem depois).
    refazer = a.refazer or not (a.data or a.de)
    while dia <= fim:
        total += coletar_dia(con, cfg, dia, refazer=refazer)
        dia += timedelta(days=1)
    print(f"Concluído: {total} ato(s) incluído(s) ou atualizado(s) de {inicio} a {fim}.")
    erros = con.execute(
        "select count(*) from coletas where erro != '' and data between ? and ?", (inicio.isoformat(), fim.isoformat())
    ).fetchone()[0]
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
