# Biblioteca de Legislação

Sistema de busca de atos normativos (leis, decretos, portarias, resoluções…), com filtros por
categoria e ano, busca no texto, página de cada ato e download em **PDF** e **Word no timbrado da marca**.
Feito para ser integrado ao site da marca.

Marca aplicada: **Esmeraldo Malheiros Advocacia**, com o mesmo logo, cores e rodapé do Monitor da Educação
(repositório `Monitor-da-Educacao_DOU_EM-Advocacia`: `config/monitor_dou.json` e `assets/logo_esmeraldo_malheiros_timbrado.png`).
Os atos em `dados/exemplo.csv` são **fictícios**, só para testar.

## Rodar

```bash
pip install -r requirements.txt
```

```bash
python -m legislacao.importar dados/exemplo.csv
```

```bash
ADMIN_SENHA=troque-esta-senha uvicorn legislacao.app:app --reload
```

Abra http://localhost:8000. Administração em `/admin` (usuário `admin`, senha da variável `ADMIN_SENHA`;
sem a variável, a administração fica desligada).

## Coleta automática (D.O.U.)

O sistema busca os atos sozinho no Diário Oficial da União (portal oficial in.gov.br), pelo mesmo
caminho do Monitor da Educação: abre a edição de cada dia, filtra pelos órgãos da educação e guarda
cada ato com **texto integral, data do ato, data de publicação e link oficial**. Os órgãos, as seções
e as regras de categoria ficam em `coletor.toml`.

```bash
python -m legislacao.coletar
```

Sem argumentos, coleta ontem e hoje (inclui edições extras). Para montar o acervo histórico:

```bash
python -m legislacao.coletar --de 2020-01-01
```

A carga histórica pode levar horas (uma pausa entre as páginas evita sobrecarregar o portal).
Se for interrompida, rode o mesmo comando: ela continua de onde parou. O resultado de cada dia
aparece em `/admin`.

**Importante:** rode a coleta numa máquina com acesso ao portal do D.O.U. O portal recusa acessos
de alguns servidores fora do Brasil (o mesmo motivo pelo qual o Monitor roda no seu computador).

### Agendar todo dia

Linux (cron), às 8h10 e às 20h10:

```bash
crontab -e
```

```
10 8,20 * * * cd /caminho/app-legislacao && /usr/bin/python3 -m legislacao.coletar >> coleta.log 2>&1
```

Windows (Agendador de Tarefas), no Prompt de Comando:

```bash
schtasks /Create /TN "Coleta Legislacao" /SC DAILY /ST 08:10 /TR "cmd /c cd /d C:\caminho\app-legislacao && python -m legislacao.coletar >> coleta.log 2>&1"
```

### O que a coleta não faz

- Não define a situação (vigente/alterada/revogada) nem as relações entre atos: o D.O.U. não traz
  essa informação de forma estruturada. Ajuste em `/admin` quando necessário.
- Quando a matéria não tem ementa destacada (comum em portarias e despachos), a ementa exibida é o
  início do próprio texto oficial, nunca um resumo escrito pelo sistema.

## Cadastrar ou corrigir atos manualmente

- Pela web: `/admin/novo` ou `/admin/importar` (CSV).
- Pela linha de comando: `python -m legislacao.importar meu-arquivo.csv`

Colunas do CSV (modelo em `dados/modelo.csv`):
`tipo, numero, data, data_publicacao, orgao, categoria, ementa, situacao, fonte_url, revoga, altera, texto`.
Obrigatórias: `tipo`, `data` (AAAA-MM-DD ou DD/MM/AAAA) e `ementa`. `situacao`: `vigente`, `alterado`, `revogado` ou `sem_informacao`.
`data_publicacao` é a data no D.O.U.; quando existe, os filtros de ano, mês e dia usam essa data.
`revoga` e `altera`: atos citados, separados por ponto e vírgula, no formato `Portaria nº 23/2017` ou
`Decreto nº 9.235, de 15 de dezembro de 2017`. Se o ato citado estiver cadastrado (ou for cadastrado depois),
vira link nos dois sentidos ("Revoga" / "Revogado por"); senão, aparece como texto.
Reimportar o mesmo ato (mesmo tipo, número, órgão e data) atualiza o cadastro.

## Aplicar a marca (timbrado)

Edite `marca.toml`: nome, subtítulo, `logo`, largura e margem do logo, contato, site, cores e aviso.
Isso muda o cabeçalho do site e o timbrado dos PDFs e arquivos Word baixados. Reinicie o servidor depois de editar.

O timbrado segue o desenho do Monitor: logo no canto superior direito (58 mm de largura, 6 mm do topo,
margens transparentes ou brancas removidas automaticamente), linha fina azul no cabeçalho, rodapé com
`site | e-mail | Página N` e faixa azul na base da página.

## Integrar ao site da marca

Três formas, da mais simples à mais flexível:

1. **Bloco embutido (iframe com altura automática).** Cole na página do site:

   ```html
   <div id="busca-legislacao"></div>
   <script src="https://ENDERECO-DO-SISTEMA/static/embed.js" data-alvo="busca-legislacao" defer></script>
   ```

   Use `data-categoria="Regulação"` para abrir já filtrado. Em `marca.toml`, inclua o domínio do site em
   `frame_ancestors`, por exemplo `["'self'", "https://www.suamarca.com.br"]`.

2. **Subcaminho do próprio site** (ex.: `suamarca.com.br/legislacao`). No servidor web do site, encaminhe
   `/legislacao/` para o sistema e rode com `uvicorn legislacao.app:app --root-path /legislacao`.
   Exemplo para Nginx:

   ```nginx
   location /legislacao/ {
       proxy_pass http://127.0.0.1:8000/;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-Proto $scheme;
   }
   ```

3. **API JSON**, para o site montar a própria lista: `GET /api/atos?q=&categoria=&ano=&pagina=`,
   `GET /api/atos/{id}`, `GET /api/facetas`. Documentação interativa em `/api/docs`.
   Libere o domínio do site em `cors_origens` no `marca.toml`.

## Testes

```bash
python -m pytest -q tests
```

## Sobre os textos

Textos de leis, decretos, regulamentos e demais atos oficiais não são protegidos por direito autoral
(Lei nº 9.610/1998, art. 8º, IV). Já a seleção, os resumos e a organização feitos por terceiros podem ser;
por isso o sistema não copia o conteúdo de outros sites: cadastre os atos a partir da publicação oficial
e informe o link da fonte.
