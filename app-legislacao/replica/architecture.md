# Arquitetura

- **Stack:** Python 3.11+, FastAPI + Jinja2 (HTML no servidor, sem build de front-end), SQLite com FTS5.
  Motivo: a dona do projeto programa em Python; um arquivo de banco só; busca textual pronta.
- **Busca:** tabela virtual `atos_fts` (tokenizer `unicode61 remove_diacritics 2`) sincronizada por triggers;
  ranking `bm25` com pesos maiores para ementa e número.
- **Timbrado:** `marca.toml` (nome, subtítulo, logo, contato, cor, rodapé) usado no site, no PDF (ReportLab)
  e no Word (python-docx). Trocar a marca = editar um arquivo, sem mexer em código.
- **Integração:** `embed.js` (iframe com altura automática), API JSON com CORS por lista de origens,
  `frame-ancestors` configurável, e publicação em subcaminho via `--root-path`.
- **Admin:** desligado se `ADMIN_SENHA` não estiver definida; HTTP Basic; checagem de origem nos POST.

## Rotas
| método | caminho | o que faz |
| --- | --- | --- |
| GET | `/` | lista, busca e filtros (`q, categoria, ano, tipo, orgao, situacao, ordem, pagina, embed`) |
| GET | `/atos/{id}` | detalhe |
| GET | `/atos/{id}/pdf`, `/atos/{id}/docx` | download no timbrado |
| GET | `/api/atos`, `/api/atos/{id}`, `/api/facetas` | API JSON (docs em `/api/docs`) |
| GET | `/static/embed.js` | script de integração |
| GET/POST | `/admin`, `/admin/novo`, `/admin/atos/{id}`, `/admin/importar` | administração |

## Pontos de atenção
- SQLite atende bem dezenas de milhares de atos e muitos leitores; com várias pessoas editando ao mesmo tempo, migrar para Postgres.
- O texto integral é cadastrado por quem administra; conferir sempre com a publicação oficial.
