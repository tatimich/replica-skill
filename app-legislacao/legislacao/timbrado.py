"""Geração dos arquivos para download (PDF e Word) no timbrado da marca."""

from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
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
    margem = 2.2 * cm
    logo = marca.caminho_logo

    def timbre(canvas, doc):
        canvas.saveState()
        # Cabeçalho
        topo = altura - 1.2 * cm
        x_texto = margem
        if logo:
            alt_logo = 1.6 * cm
            canvas.drawImage(
                str(logo), margem, topo - alt_logo, height=alt_logo, width=4 * cm,
                preserveAspectRatio=True, anchor="w", mask="auto",
            )
            x_texto = margem + 4.4 * cm
        canvas.setFillColor(cor)
        canvas.setFont(fontes["Titulo"], 13)
        canvas.drawString(x_texto, topo - 0.65 * cm, marca.nome)
        if marca.subtitulo:
            canvas.setFont(fontes["Apoio"], 9)
            canvas.drawString(x_texto, topo - 1.15 * cm, marca.subtitulo)
        canvas.setStrokeColor(cor)
        canvas.setLineWidth(1.2)
        canvas.line(margem, topo - 1.85 * cm, largura - margem, topo - 1.85 * cm)
        # Rodapé
        canvas.setLineWidth(0.5)
        canvas.line(margem, 2.0 * cm, largura - margem, 2.0 * cm)
        canvas.setFillColor(HexColor("#444444"))
        canvas.setFont(fontes["Apoio"], 7.5)
        y = 1.6 * cm
        for linha in (marca.linha_contato, marca.rodape):
            if linha:
                canvas.drawString(margem, y, linha[:140])
                y -= 0.38 * cm
        canvas.drawRightString(largura - margem, 1.6 * cm, f"Página {doc.page}")
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

    saida = io.BytesIO()
    doc = SimpleDocTemplate(
        saida, pagesize=A4, leftMargin=margem, rightMargin=margem,
        topMargin=3.6 * cm, bottomMargin=2.6 * cm,
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
    secao.top_margin, secao.bottom_margin = Cm(3.2), Cm(2.4)
    secao.header_distance, secao.footer_distance = Cm(1.0), Cm(1.0)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)

    # Cabeçalho (timbre)
    cab = secao.header.paragraphs[0]
    logo = marca.caminho_logo
    if logo:
        cab.add_run().add_picture(str(logo), height=Cm(1.4))
        cab.add_run("   ")
    nome = cab.add_run(marca.nome)
    nome.bold, nome.font.size, nome.font.color.rgb, nome.font.name = True, Pt(13), cor, "Arial"
    if marca.subtitulo:
        cab.add_run("\n")
        sub = cab.add_run(marca.subtitulo)
        sub.font.size, sub.font.color.rgb, sub.font.name = Pt(9), cor, "Arial"
    _borda_inferior(cab, marca.cor_primaria, 10)

    # Rodapé
    rod = secao.footer.paragraphs[0]
    _borda_inferior(rod, marca.cor_primaria, 4)  # linha acima do texto do rodapé
    rod.paragraph_format.space_after = Pt(2)
    for linha in (marca.linha_contato, marca.rodape):
        if linha:
            p = secao.footer.add_paragraph()
            run = p.add_run(linha)
            run.font.size, run.font.name = Pt(7.5), "Arial"
    p = secao.footer.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p.add_run("Página ")
    run.font.size = Pt(7.5)
    _campo(p, "PAGE")

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

    doc.core_properties.title = db.titulo(ato)
    doc.core_properties.author = marca.nome
    saida = io.BytesIO()
    doc.save(saida)
    return saida.getvalue()
