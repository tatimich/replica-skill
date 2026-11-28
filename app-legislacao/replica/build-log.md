# Build log
- S01 lista e filtros: feito. Testado a 390px e 1280px, sem erros de console.
- S02 detalhe: feito.
- S03 downloads PDF/DOCX com timbrado: feito.
- S04 administração: feito (cadastro, edição, exclusão, importação CSV).
- Pendente: revisar recon com a página de referência quando o acesso de rede for liberado; importador de fontes oficiais (F15).
- Marca Esmeraldo Malheiros Advocacia aplicada (logo, cores #07384a/#c79a50, rodapé), copiada do Monitor da Educação. Timbrado do PDF reproduz o do Monitor; no Word, a faixa azul do rodapé é aproximada por um parágrafo sombreado.
- Recon revisado com a página de referência (27/11/2026). Acrescentados: data do D.O.U., filtros mês/dia, atos relacionados (revoga/altera), caixa de contato.
- Coletor automático do D.O.U. (legislacao/coletar.py + coletor.toml), mesmo método do Monitor. Testado com portal simulado; o portal real recusa acesso deste ambiente (fora do Brasil), então a primeira coleta real precisa ser feita na máquina da usuária ou no servidor.
