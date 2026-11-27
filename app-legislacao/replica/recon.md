# Recon: busca de legislação (referência funcional)

Referência indicada: `https://abmes.org.br/legislacoes?categoria=21&ano=`

Lida em 27/11/2026 (lista e uma página de detalhe, leitura manual, sem robô). Registro apenas
de funcionalidades; nada do conteúdo, da curadoria, dos textos ou do visual foi copiado.

## O que a referência oferece (funcional)
- Busca por termo, com frase exata entre aspas.
- Filtros: categoria (na prática, o **tipo** do ato: Lei, Decreto, Resolução, Portaria do MEC…),
  subcategoria (o **órgão** emissor), ano, mês e dia; cada opção com contagem.
- Cartão do resultado: tipo, título curto (tipo + sigla do órgão + número), data do D.O.U., ementa resumida,
  botão de baixar o arquivo.
- Mais resultados por "carregar mais" (lotes de 9).
- Detalhe: tipo, título, data do ato, data do D.O.U., órgão, baixar arquivo, ementa,
  atos relacionados (ex.: "Revoga:") e um chamado para tirar dúvidas com a equipe jurídica.

## Equivalência no clone
| referência | clone |
| --- | --- |
| categoria (tipo) | filtro "Tipo de ato" |
| subcategoria (órgão) | filtro "Órgão" |
| ano, mês, dia | filtros ano, mês e dia (pela data do D.O.U.) |
| "carregar mais" | paginação (melhor para links e para embutir) |
| relacionados ("Revoga") | Revoga / Altera, com o sentido inverso automático |
| contato da consultoria | caixa "Ficou com dúvida?" com o e-mail da marca |
| (não tem) | categorias por tema, situação (vigente/alterado/revogado), texto integral pesquisável, PDF e Word no timbrado |

## Fluxo central
1. A pessoa abre a lista de atos (mais recentes primeiro).
2. Filtra por categoria (tema) e/ou ano; opcionalmente busca por palavra.
3. Abre um ato, lê a ementa e o texto, e baixa o arquivo.

## Telas
| ID | tela | estados |
| --- | --- | --- |
| S01 | Lista com filtros (categoria, ano, tipo, órgão, situação) e busca | vazio, com resultados, paginação, mobile |
| S02 | Detalhe do ato (ficha, ementa, texto, downloads, fonte oficial) | sem texto integral, revogado/alterado |
| S03 | Download PDF/Word no timbrado da marca | sem logo, com logo |
| S04 | Administração: lista, cadastro/edição, importação CSV | erro de validação, sucesso |

## Modelo de dados inferido
Ato normativo: tipo, número, data, órgão, categoria, ementa, texto integral, situação, link da fonte oficial.
