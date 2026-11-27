"""Geração dos arquivos para download (PDF e Word) no timbrado da marca."""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from . import db
from .marca import Marca

# ------------------------------------------------------------------- utilidades


def paragrafos(texto: str) -> list[str]:
    """Quebra o texto integral em parágrafos (uma linha por parágrafo)."""
    return [p.strip() for p in re.split(r"\n+", texto or "") if p.strip()]


def nome_arquivo(ato: dict, extensao: str) -> str:
    base = f"{ato['tipo']}-{ato.get('numero') or 'sn'}-{ato['data'][:4]}"
    base = re.sub(r"[^\w.-]+", "-", base, flags=re.ASCII).strip("-").lower()
    return f"{base}.{extensao}"


def _cor(hexa: str) -> tuple[int, int, int]:
    h = hexa.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = "1F3A5F"
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


_LOGO_CACHE: dict[str, tuple[bytes, int, int]] = {}


def logo_aparado(caminho: Path) -> tuple[bytes, int, int]:
    """Remove margens transparentes ou brancas do logo (mesma regra do Monitor).

    Devolve (PNG em bytes, largura, altura) para manter a largura visual exata.
    """
    chave = f"{caminho}:{caminho.stat().st_mtime}"
    if chave not in _LOGO_CACHE:
        from PIL import Image, ImageChops

        with Image.open(caminho) as fonte:
            img = fonte.convert("RGBA")
        caixa = img.getchannel("A").getbbox()
        if caixa:
            img = img.crop(caixa)
        fundo = Image.new("RGBA", img.size, (255, 255, 255, 255))
        caixa = ImageChops.difference(img.convert("RGB"), fundo.convert("RGB")).getbbox()
        if caixa:
            img = img.crop(caixa)
        saida = io.BytesIO()
        img.save(saida, format="PNG", optimize=True)
        _LOGO_CACHE[chave] = (saida.getvalue(), img.width, img.height)
    return _LOGO_CACHE[chave]


def _linha_fonte(ato: dict) -> str:
    partes = []
    if ato.get("fonte_url"):
        partes.append(f"Fonte oficial: {ato['fonte_url']}")
    partes.append(f"Situação: {db.SITUACOES.get(ato['situacao'], ato['situacao'])}")
    partes.append(f"Gerado em {date.today().strftime('%d/%m/%Y')}")
    return "  |  ".join(partes)


# ------------------------------------------------------------------- PDF

_FONTES_DEJAVU = {
    "Corpo": "DejaVuSerif.ttf",
    "Corpo-Negrito": "DejaVuSerif-Bold.ttf",
    "Corpo-Italico": "DejaVuSerif-Italic.ttf",
    "Titulo": "DejaVuSans-Bold.ttf",
    "Apoio": "DejaVuSans.ttf",
}
_PASTAS_FONTES = (Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/dejavu"))


def _fontes_pdf() -> dict[str, str]:
    """Usa DejaVu (cobre todos os acentos) quando instalada; senão, fontes padrão do PDF."""
    for pasta in _PASTAS_FONTES:
        if all((pasta / arq).is_file() for arq in _FONTES_DEJAVU.values()):
            for nome, arq in _FONTES_DEJAVU.items():
                if nome not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(nome, str(pasta / arq)))
            return {n: n for n in _FONTES_DEJAVU}
    return {
        "Corpo": "Times-Roman",
        "Corpo-Negrito": "Times-Bold",
        "Corpo-Italico": "Times-Italic",
        "Titulo": "Helvetica-Bold",
        "Apoio": "Helvetica",
    }


def gerar_pdf(ato: dict, marca: Marca) -> bytes:
    fontes = _fontes_pdf()
    cor = HexColor(marca.cor_primaria if re.fullmatch(r"#[0-9a-fA-F]{6}", marca.cor_primaria) else "#1F3A5F")
    largura, altura = A4
    margem = 18 * mm
    logo = marca.caminho_logo
    logo_img, logo_w, logo_h = None, 0.0, 0.0
    if logo:
        dados_logo, px_w, px_h = logo_aparado(logo)
        logo_img = ImageReader(io.BytesIO(dados_logo))
        logo_w = marca.logo_largura_mm * mm
        logo_h = logo_w * px_h / px_w
    topo_texto = max(32 * mm, marca.logo_margem_topo_mm * mm + logo_h + 8 * mm)

    def timbre(canvas, doc):
        canvas.saveState()
        # Cabeçalho: logo à direita e linha fina da borda esquerda até o logo.
        canvas.setStrokeColor(cor)
        if logo_img:
            logo_x = largura - margem - logo_w
            logo_y = altura - marca.logo_margem_topo_mm * mm - logo_h
            canvas.drawImage(logo_img, logo_x, logo_y, width=logo_w, height=logo_h,
                             preserveAspectRatio=True, mask="auto")
            canvas.setLineWidth(0.6)
            canvas.line(0, altura - 18.5 * mm, logo_x - 8 * mm, altura - 18.5 * mm)
        else:
            canvas.setFillColor(cor)
            canvas.setFont(fontes["Titulo"], 13)
            canvas.drawString(margem, altura - 14 * mm, marca.nome)
            canvas.setLineWidth(0.6)
            canvas.line(0, altura - 18.5 * mm, largura, altura - 18.5 * mm)
        # Rodapé: linha, "site | e-mail | Página N" e faixa na cor da marca.
        canvas.setLineWidth(0.5)
        canvas.line(margem, 14 * mm, largura - margem, 14 * mm)
        canvas.setFillColor(HexColor("#000000"))
        canvas.setFont("Helvetica", 8)
        partes = [x for x in (marca.linha_contato, f"Página {doc.page}") if x]
        canvas.drawCentredString(largura / 2, 9 * mm, " | ".join(partes))
        canvas.setFillColor(cor)
        canvas.rect(0, 0, largura, 7 * mm, stroke=0, fill=1)
        canvas.restoreState()

    estilos = {
        "titulo": ParagraphStyle(
            "titulo", fontName=fontes["Corpo-Negrito"], fontSize=12.5, leading=16,
            alignment=1, spaceAfter=4, textColor=cor,
        ),
        "orgao": ParagraphStyle(
            "orgao", fontName=fontes["Apoio"], fontSize=9, leading=12, alignment=1,
            textColor=HexColor("#444444"), spaceAfter=14,
        ),
        "ementa": ParagraphStyle(
            "ementa", fontName=fontes["Corpo-Italico"], fontSize=10.5, leading=14,
            leftIndent=(largura - 2 * margem) * 0.45, alignment=TA_JUSTIFY, spaceAfter=18,
        ),
        "corpo": ParagraphStyle(
            "corpo", fontName=fontes["Corpo"], fontSize=10.5, leading=15,
            alignment=TA_JUSTIFY, firstLineIndent=1.25 * cm, spaceAfter=6,
        ),
        "aviso": ParagraphStyle(
            "aviso", fontName=fontes["Apoio"], fontSize=9, leading=12,
            textColor=HexColor("#444444"),
        ),
    }

    historia = [
        Paragraph(escape(db.titulo(ato)).upper(), estilos["titulo"]),
        Paragraph(escape(ato.get("orgao") or ""), estilos["orgao"]),
        Paragraph(escape(ato["ementa"]), estilos["ementa"]),
    ]
    corpo = paragrafos(ato.get("texto", ""))
    if corpo:
        historia += [Paragraph(escape(p), estilos["corpo"]) for p in corpo]
    else:
        historia.append(
            Paragraph(
                "O texto integral deste ato não está cadastrado. Consulte a fonte oficial indicada abaixo.",
                estilos["aviso"],
            )
        )
    historia += [Spacer(1, 16), Paragraph(escape(_linha_fonte(ato)), estilos["aviso"])]
    if marca.rodape:
        historia.append(Paragraph(escape(marca.rodape), estilos["aviso"]))

    saida = io.BytesIO()
    doc = SimpleDocTemplate(
        saida, pagesize=A4, leftMargin=margem, rightMargin=margem,
        topMargin=topo_texto, bottomMargin=22 * mm,
        title=db.titulo(ato), author=marca.nome, subject=ato["ementa"][:200],
    )
    doc.build(historia, onFirstPage=timbre, onLaterPages=timbre)
    return saida.getvalue()


# ------------------------------------------------------------------- Word (DOCX)


def _borda_inferior(paragrafo, cor_hex: str, espessura: int = 8) -> None:
    pPr = paragrafo._p.get_or_add_pPr()
    bordas = OxmlElement("w:pBdr")
    linha = OxmlElement("w:bottom")
    linha.set(qn("w:val"), "single")
    linha.set(qn("w:sz"), str(espessura))
    linha.set(qn("w:space"), "4")
    linha.set(qn("w:color"), cor_hex.lstrip("#"))
    bordas.append(linha)
    pPr.append(bordas)


def _borda_superior(paragrafo, cor_hex: str, espessura: int = 4) -> None:
    pPr = paragrafo._p.get_or_add_pPr()
    bordas = OxmlElement("w:pBdr")
    linha = OxmlElement("w:top")
    linha.set(qn("w:val"), "single")
    linha.set(qn("w:sz"), str(espessura))
    linha.set(qn("w:space"), "4")
    linha.set(qn("w:color"), cor_hex.lstrip("#"))
    bordas.append(linha)
    pPr.append(bordas)


def _sombreamento(paragrafo, cor_hex: str) -> None:
    pPr = paragrafo._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), cor_hex.lstrip("#"))
    pPr.append(shd)


def _campo(paragrafo, instrucao: str) -> None:
    """Insere um campo do Word (ex.: PAGE) que se atualiza sozinho."""
    run = paragrafo.add_run()
    for tipo, texto in (("begin", None), (None, instrucao), ("separate", None), (None, "1"), ("end", None)):
        if tipo:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tipo)
        elif texto == instrucao:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = f" {instrucao} "
        else:
            el = OxmlElement("w:t")
            el.text = texto
        run._r.append(el)


def gerar_docx(ato: dict, marca: Marca) -> bytes:
    r, g, b = _cor(marca.cor_primaria)
    cor = RGBColor(r, g, b)
    doc = Document()
    secao = doc.sections[0]
    secao.page_height, secao.page_width = Cm(29.7), Cm(21.0)
    secao.left_margin = secao.right_margin = Cm(2.2)
    secao.top_margin, secao.bottom_margin = Cm(3.6), Cm(2.4)
    secao.header_distance, secao.footer_distance = Cm(marca.logo_margem_topo_mm / 10), Cm(0.6)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)

    # Cabeçalho: linha fina à esquerda e logo à direita (como no PDF).
    largura_util = secao.page_width - secao.left_margin - secao.right_margin
    logo = marca.caminho_logo
    cab = secao.header
    if logo:
        dados_logo, _, _ = logo_aparado(logo)
        tabela = cab.add_table(rows=1, cols=2, width=largura_util)
        tabela.autofit = False
        larg_logo = Cm(marca.logo_largura_mm / 10)
        esq, dir_ = tabela.rows[0].cells
        esq.width, dir_.width = largura_util - larg_logo, larg_logo
        esq.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        _borda_inferior(esq.paragraphs[0], marca.cor_primaria, 5)
        p_logo = dir_.paragraphs[0]
        p_logo.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p_logo.add_run().add_picture(io.BytesIO(dados_logo), width=larg_logo)
        cab.paragraphs[0].paragraph_format.space_after = Pt(0)
    else:
        p = cab.paragraphs[0]
        run = p.add_run(marca.nome)
        run.bold, run.font.size, run.font.color.rgb, run.font.name = True, Pt(13), cor, "Arial"
        _borda_inferior(p, marca.cor_primaria, 5)

    # Rodapé: linha, "site | e-mail | Página N" e faixa na cor da marca.
    rod = secao.footer.paragraphs[0]
    rod.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _borda_superior(rod, marca.cor_primaria, 4)
    if marca.linha_contato:
        run = rod.add_run(marca.linha_contato + " | ")
        run.font.size, run.font.name = Pt(8), "Arial"
    run = rod.add_run("Página ")
    run.font.size, run.font.name = Pt(8), "Arial"
    _campo(rod, "PAGE")
    faixa = secao.footer.add_paragraph()
    faixa.paragraph_format.space_before = Pt(6)
    _sombreamento(faixa, marca.cor_primaria)
    faixa.add_run(" ").font.size = Pt(9)

    # Corpo
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = t.add_run(db.titulo(ato).upper())
    run.bold, run.font.size, run.font.color.rgb = True, Pt(12.5), cor
    if ato.get("orgao"):
        o = doc.add_paragraph()
        o.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = o.add_run(ato["orgao"])
        run.font.size, run.font.name = Pt(9), "Arial"
    e = doc.add_paragraph()
    e.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    e.paragraph_format.left_indent = Cm(7.5)
    e.paragraph_format.space_before, e.paragraph_format.space_after = Pt(12), Pt(18)
    e.add_run(ato["ementa"]).italic = True

    corpo = paragrafos(ato.get("texto", ""))
    if corpo:
        for texto in corpo:
            p = doc.add_paragraph(texto)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.first_line_indent = Cm(1.25)
            p.paragraph_format.space_after = Pt(6)
    else:
        doc.add_paragraph(
            "O texto integral deste ato não está cadastrado. Consulte a fonte oficial indicada abaixo."
        )
    f = doc.add_paragraph()
    f.paragraph_format.space_before = Pt(16)
    run = f.add_run(_linha_fonte(ato))
    run.font.size, run.font.name = Pt(9), "Arial"
    if marca.rodape:
        run = doc.add_paragraph().add_run(marca.rodape)
        run.font.size, run.font.name = Pt(9), "Arial"

    doc.core_properties.title = db.titulo(ato)
    doc.core_properties.author = marca.nome
    saida = io.BytesIO()
    doc.save(saida)
    return saida.getvalue()
