# Lab 05: Medição e Experimentação em software real

Estudo do efeito dos índices compostos da migração V2 sobre o tempo de execução das listagens do **Sentinela**, um sistema de gestão operacional de segurança em produção.

- Proposta da Sprint 1: [PROPOSTA.md](PROPOSTA.md)
- Disciplina: Laboratório de Experimentação de Software, Engenharia de Software (PUC Minas)

## Estrutura

```
.
├── PROPOSTA.md           # Lab05S01
├── docker-compose.yml    # PostgreSQL do laboratório
├── requirements.txt
├── scripts/
│   ├── sql/schema.sql        # esquema simplificado (sem índices)
│   ├── sql/indices_v2.sql    # índices da V2 (mesma definição do Sentinela)
│   ├── sql/indice_vistoria_visitas.sql  # intervenção do estudo de vistorias
│   ├── sql/metricas_producao.sql        # consultas de leitura para coletar métricas de produção
│   ├── comum.py              # conexão e constantes
│   ├── consultas.py          # catálogo das consultas medidas
│   ├── gerar_dados.py        # dados sintéticos (COPY, com semente)
│   ├── benchmark.py          # sem_indice x com_indice, custom x generic, com EXPLAIN ANALYZE
│   └── validar.py            # sanidade do CSV antes da análise
├── dados/                # CSVs de medições e metadados (versionados)
├── analise/              # Sprint 2
└── docs/                 # documento final e apresentação
```

## Como rodar a coleta piloto

Pré-requisitos: Python 3.11 ou superior e Docker.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Suba o PostgreSQL com a **mesma versão da produção do Sentinela** (confira no painel do Railway). Se a porta 5433 estiver ocupada na sua máquina, escolha outra e use a mesma nas variáveis `LAB5_PG*` abaixo.

```powershell
$env:PG_VERSION = "17-alpine"
$env:LAB5_PGPORT = "5433"
docker compose up -d
```

Gere os dados sintéticos, rode o benchmark e valide (piloto: 10 mil linhas, 10 repetições):

```powershell
.\.venv\Scripts\python scripts/gerar_dados.py --tamanho 2000 --empresas 3 --semente 42
.\.venv\Scripts\python scripts/benchmark.py --repeticoes 10 --aquecimento 3 --semente 42
.\.venv\Scripts\python scripts/validar.py dados/<arquivo gerado>.csv
```

`--tamanho` é por empresa e por tabela principal. O exemplo acima gera 6.000 linhas por tabela (3 empresas × 2.000).

### Análise

```powershell
.\.venv\Scripts\python -m pip install -r requirements-analise.txt
.\.venv\Scripts\python analise/analisar.py dados/piloto_ausente.csv dados/piloto_atualizada.csv
```

O script gera tabelas em `analise/resultados/` (descritiva, efeito da estatística, índice contra `sem_indice`, escala por empresas e planos escolhidos). O teste é Mann-Whitney, porque as condições comparadas são amostras independentes (ver PROPOSTA.md, seção 9).

### Equivalência da reescrita

Antes da Matriz B, confira que a consulta reescrita devolve o mesmo resultado da original (banco do laboratório já populado):

```powershell
.\.venv\Scripts\python scripts/verificar_equivalencia.py
```

### Coleta completa (Sprint 2)

São duas matrizes (ver PROPOSTA.md, seção 6). Sempre com `--repeticoes 30`.

**Matriz A (estatísticas e escala por empresas): 10 execuções.** Para cada número de empresas (1, 2, 5, 10 e 50) e cada estado de estatística (`atualizada` e `ausente`):

```powershell
.\.venv\Scripts\python scripts/gerar_dados.py --tamanho 8000 --empresas 5
.\.venv\Scripts\python scripts/benchmark.py --estudo v2 --repeticoes 30 --estatistica-tenant ausente
```

**Matriz B (consulta de vistorias): 4 execuções.** Tamanhos 350 (1 empresa), 1000 (1 empresa), 8000 (1 empresa) e 8000 (5 empresas):

```powershell
.\.venv\Scripts\python scripts/gerar_dados.py --tamanho 8000 --empresas 5
.\.venv\Scripts\python scripts/benchmark.py --estudo vistorias --repeticoes 30 --timeout-s 60
```

Sem índice, a consulta de vistorias cresce de forma quase quadrática. As medições que estouram o tempo limite ficam registradas como censuradas (`estourou_timeout`). O CSV traz também o erro de estimativa do planejador (`linhas_estimadas` e `linhas_reais_no_scan`).

Variáveis de conexão (todas opcionais): `LAB5_PGHOST`, `LAB5_PGPORT`, `LAB5_PGDATABASE`, `LAB5_PGUSER`, `LAB5_PGPASSWORD`. Os padrões apontam para o contêiner do `docker-compose.yml`. O gerador recusa bancos que não se chamem `lab5`, pois ele apaga e recria as tabelas.

Cada execução do benchmark grava um CSV e um `.meta.json` (versão do Postgres, configuração, semente, argumentos, ordem das condições).

## O que o piloto mede (e o que não mede)

- **Dois estudos:** `v2` (índices da migração V2 em `ocorrencias` e `fichas`, com uma consulta de controle que ordena por nome) e `vistorias` (índice em `vistoria_visitas` para a consulta de alertas, que consome 73% do tempo do banco de produção).
- **Consultas:** catálogo em `scripts/consultas.py`, com o formato das consultas reais vistas em produção (padrão `($1 IS NULL OR unidade_id = $2)`, páginas de 20 linhas na ordenação por nome). `ocorrencias_unidade_data` é de formato **assumido**, a confirmar.
- **Fatores:** configuração de índices (condição, definida em `scripts/comum.py`: no estudo `v2` há `sem_indice`, `v2`, `producao`, `tenant_unidade_data` e `tenant_data`; no estudo `vistorias`, `sem_indice` e `com_indice`), modo de plano (`custom`, `generic`, via `plan_cache_mode`) e **número de empresas** no banco (`gerar_dados.py --empresas N`).
- **Estatísticas de `tenant_id`:** `benchmark.py --estatistica-tenant ausente` remove as estatísticas da coluna depois de cada `ANALYZE`, como em produção hoje (ver PROPOSTA.md, seção 1.3). Exige superusuário (o do contêiner do `docker-compose.yml` é). Rode as duas versões (`atualizada` e `ausente`).
- **Multi-tenant:** todas as consultas levam `tenant_id = $1`, como o Hibernate faz depois da Fase 2 do Sentinela. As medições são da empresa 1; as demais só aumentam o volume do banco.
- **Distribuições sintéticas assumidas** (status das vistorias, visitas por vistoria): ficam em `gerar_dados.py` e devem ser calibradas com dados agregados de produção.
- O piloto serve para validar scripts e formato do CSV. Os números dele **não** respondem à pergunta de pesquisa.

## Ética

Nenhum dado real do sistema entra neste repositório. Os dados são sintéticos, calibrados por contagens agregadas. Segredos nunca são versionados.
