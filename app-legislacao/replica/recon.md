# Recon: busca de legislação (referência funcional)

Referência indicada: `https://abmes.org.br/legislacoes?categoria=21&ano=`

**Limitação:** a página não pôde ser lida neste ambiente (o host está bloqueado na rede da sessão).
Este mapa descreve apenas o que se deduz da própria URL (filtros por `categoria` e `ano`)
e o padrão comum de bibliotecas de atos normativos. Nada do conteúdo, da curadoria, dos textos
ou do visual da ABMES foi copiado. Quando o acesso estiver liberado, revisar este mapa com
`/replica-recon` lendo a página como usuária.

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
