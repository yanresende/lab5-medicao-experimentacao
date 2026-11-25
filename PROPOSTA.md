# Lab05S01: Proposta de experimento

**Disciplina:** Laboratório de Experimentação de Software (Engenharia de Software, 6º período, noite)
**Professor:** Danilo Maia
**Grupo:** <preencher: nomes do trio>
**Software estudado:** Sentinela (sistema de gestão operacional de segurança)
**Status:** rascunho da Sprint 1. Itens marcados com `<coletar>` dependem de medidas do próprio sistema.

> Aprovação: o professor aprovou o uso do Sentinela como objeto de estudo (conversa fora da plataforma). Registrar aqui a data e, se possível, uma confirmação por escrito: `<preencher>`.

---

## 1. O software e os três critérios

O Sentinela é um sistema web e mobile (PWA e APK Android) usado em produção por equipes de segurança patrimonial para registrar ocorrências, fichas de suspeitos, turnos, rotas, vistorias e patrulhas. Stack: Spring Boot 3.3 (Java 17), PostgreSQL, React 19, hospedado no Railway.

| Critério | Evidência | Fonte |
|---|---|---|
| Real | Sistema com mais de 50 controllers e cerca de 100 entidades, em uso por usuários reais fora do grupo. | Repositório e produção |
| Em operação | Em produção hoje, com deploy contínuo e último release em `<coletar: data>`. Primeiro commit em 21/02/2026. | Painel do Railway, histórico do repositório |
| Alto impacto | 22 usuários ativos, uso diário, uso intenso de banco de dados. Números de apoio: `<coletar: usuários ativos/dia, requisições/dia, linhas por tabela>`. | Métricas do próprio sistema (Actuator, `/api/metricas/atividade-usuarios`, contagens no banco) |

**Limitação assumida (e aprovada pelo professor):** 22 usuários é um impacto pequeno em escala absoluta. O impacto é medido em tempo de trabalho economizado por uma equipe operacional que depende do sistema todos os dias, e a generalização para outros sistemas é discutida como ameaça de validade externa (seção 8).

O objeto de pesquisa é o **software em funcionamento** (a aplicação e seu banco de dados), não o repositório de código. Não há mineração de commits, issues ou pull requests.

## 2. Contexto e problema

O banco de dados de produção foi construído durante meses com `ddl-auto=update`. Antes da migração Flyway **V2 (`V2__indices_operacionais.sql`, 09/08/2026)** existia **um único índice declarado em 55 entidades**. Toda listagem filtrava por unidade (`unidade_id`, o isolamento MG/ES) e ordenava por data decrescente, o que implica varredura completa da tabela e ordenação em memória.

A V2 criou índices compostos `(unidade_id, <data principal> DESC)` em 12 tabelas operacionais (ocorrências, apurações de furto, fichas, veículos, ferramentas, vistorias, campanas, conscientizações, vulnerabilidades, queimadas, ferro-velhos e passagens), mais um segundo índice na apuração de furto. A decisão foi tomada por raciocínio, sem medição, porque o sistema não tinha nenhuma métrica na época.

**Lacuna:** nunca se mediu se a mudança funcionou, quanto ganhou, e se o ganho muda conforme o volume de dados cresce.

## 3. Pergunta de pesquisa

**PP principal:** Os índices compostos `(unidade_id, data DESC)` da migração V2 reduzem o tempo de execução das listagens operacionais do Sentinela?

**PP2:** Esse efeito depende do volume de dados na tabela?

**PP3:** Em tempo poupado por dia, qual é o ganho para os usuários reais do sistema?

## 4. GQM

**Objetivo (template de Basili):**
Analisar os índices compostos da migração V2,
com o propósito de avaliar seu efeito,
quanto ao tempo de execução das listagens operacionais,
do ponto de vista dos usuários e mantenedores do Sentinela,
no contexto do sistema em produção (PostgreSQL) e de uma réplica controlada no ambiente do grupo.

| Pergunta | Métrica | Entidade e atributo | Tipo | Escala |
|---|---|---|---|---|
| Q1: Qual o tempo de execução da listagem com e sem os índices? | M1: tempo de execução da consulta (ms), por `EXPLAIN (ANALYZE, BUFFERS)` | Produto (consulta), atributo externo | Direta | Razão |
| Q2: O banco lê menos dados com os índices? | M2: linhas lidas e blocos acessados (buffers) | Produto, atributo interno | Direta | Razão |
| Q3: O plano de execução muda? | M3: tipo do nó principal (Seq Scan, Index Scan, Sort) | Produto, atributo interno | Direta | Nominal |
| Q4: O efeito cresce com o volume? | M4: razão sem/com índice (M1 sem ÷ M1 com) por tamanho de tabela | Produto | Derivada | Razão |
| Q5: Quanto tempo isso poupa por dia? | M5: tempo poupado/dia = (M1 sem - M1 com) × consultas/dia | Processo (uso), recurso (tempo de CPU) | Derivada | Razão |
| Q6: O que o usuário percebe? | M6: latência ponta a ponta do endpoint (p50 e p95, ms) em produção | Produto, atributo externo | Direta | Razão |

Cuidado com armadilhas de medição (Goodhart): tempo médio isolado pode esconder cauda longa, por isso reportar p95 e mediana junto com a média, e olhar o plano de execução (M2 e M3) para confirmar que o ganho vem do índice e não de cache.

## 5. Hipóteses

Unidade de análise: par (consulta, tamanho de tabela), medida repetida `n` vezes em cada condição.

- **H0 (PP1):** a mediana do tempo de execução com índices é igual à sem índices.
- **H1 (PP1):** a mediana do tempo de execução com índices é menor que sem índices (unilateral).
- **H0 (PP2):** a razão sem/com índice não varia com o volume de dados.
- **H1 (PP2):** a razão sem/com índice aumenta com o volume de dados.

Nível de significância α = 0,05.

## 6. Planejamento do experimento

### 6.1 Desenho

- **Fator principal:** presença dos índices da V2 (2 níveis: `sem_V2`, `com_V2`).
- **Fator secundário:** volume por tabela (3 níveis: 10 mil, 100 mil e 1 milhão de linhas, ajustar ao volume real de produção).
- **Objetos experimentais:** as consultas das listagens das 12 tabelas cobertas pela V2 (filtro por `unidade_id`, ordenação por data DESC, paginação), extraídas dos repositórios JPA e logadas com `show_sql`.
- **Desenho pareado (within-subject):** o mesmo banco, com os mesmos dados, é medido nas duas condições. Para alternar, o grupo aplica as migrações V1 apenas (`sem_V2`) e depois V1 + V2 (`com_V2`) sobre uma cópia idêntica dos dados.
- **Randomização:** a ordem das consultas e das condições é sorteada a cada rodada, com sementes registradas.
- **Repetições:** 30 medições por (consulta, tamanho, condição) após 5 de aquecimento descartadas.

### 6.2 Dados

- **Nunca usar dados reais do cliente.** O Sentinela guarda dados pessoais e de segurança (fichas de suspeitos, fotos, ocorrências). O experimento usa **dados sintéticos** gerados por script com distribuição realista (unidades, datas, status), calibrados pelas **contagens agregadas** da produção (ex.: número de linhas por tabela), que não identificam ninguém.
- Os dados sintéticos e a semente do gerador ficam versionados neste repositório.

### 6.3 Instrumentação

- PostgreSQL na mesma versão da produção, em contêiner Docker (mesma configuração de memória em todas as rodadas).
- Script de geração de dados (Python ou SQL `generate_series`).
- Script de benchmark que executa `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` e grava CSV (consulta, tamanho, condição, rodada, tempo, linhas, buffers, nó principal).
- Em produção, **somente leitura passiva**: métricas do Actuator/Micrometer (`/actuator/metrics`, `/actuator/prometheus`) e contagens agregadas. Nenhum teste de carga e nenhuma escrita.

### 6.4 Operação

1. Gerar dados sintéticos nos 3 tamanhos.
2. Subir o Postgres e aplicar V1 (sem índices), rodar o benchmark.
3. Aplicar V2, rodar o benchmark (mesma ordem sorteada).
4. Repetir para os 3 volumes.
5. Validar os dados (sem NaN, sem rodada duplicada, tempos positivos) e versionar o CSV.

## 7. Classificação da pesquisa (as 7 categorias)

| Categoria | Classificação | Justificativa |
|---|---|---|
| Natureza | Aplicada | Resolve uma pergunta prática de engenharia: se uma decisão de otimização funcionou. |
| Objetivos | Explicativa (com componente descritiva) | Busca explicar a relação causal entre índice e tempo de execução. Descreve também o perfil de uso. |
| Abordagem | Quantitativa | Variáveis numéricas em escala de razão, com teste estatístico. |
| Procedimentos | Experimento (controlado, em laboratório) e estudo de caso (produção) | A parte local manipula o fator. A parte de produção observa o sistema real. |
| Tempo | Transversal para o experimento e longitudinal para a leitura das métricas de produção ao longo da Sprint 2 | O experimento é um recorte. As métricas de uso acumulam no tempo. |
| Controle | Experimental na réplica local, observacional na produção | Só na réplica o grupo controla o fator e o ambiente. |
| Nível de evidência | Evidência forte para o efeito técnico (controlado), moderada para o impacto em produção (poucos usuários, único sistema) | O desenho pareado e a randomização sustentam a causalidade local. A generalização é limitada. |

Esta é a primeira versão. Será revisada na Lab05S03.

## 8. Ameaças à validade (versão inicial)

| Tipo | Ameaça | Mitigação |
|---|---|---|
| Conclusão | Poucos dados ou violação de pressupostos do teste. Variabilidade de medição. | 30 repetições por célula. Teste não paramétrico (Wilcoxon pareado). Reportar tamanho de efeito e intervalo de confiança. |
| Interna | Cache do Postgres e do sistema operacional distorcendo a segunda condição. Ordem das condições. Outras mudanças entre as versões do schema. | Aquecimento descartado, ordem sorteada, reinício do contêiner entre condições, comparar apenas V1 contra V1 + V2 com os mesmos dados. |
| Construto | Tempo de `EXPLAIN ANALYZE` não é a latência percebida pelo usuário. Dados sintéticos podem não refletir a distribuição real. | Complementar com a latência ponta a ponta (M6) da produção. Calibrar o gerador com agregados reais. |
| Externa | Um único sistema, 22 usuários, uma única empresa, um único SGBD. | Declarar que o resultado vale para listagens com filtro seletivo e ordenação por data em PostgreSQL. Não generalizar para outros sistemas. |

## 9. Plano de análise

1. **Estatística descritiva:** média, mediana, desvio, p95 e boxplots por (consulta, condição, tamanho).
2. **Normalidade:** Shapiro-Wilk nas diferenças pareadas.
3. **Teste de hipótese:** Wilcoxon de postos sinalizados (unilateral), ou teste t pareado se as diferenças forem normais.
4. **Tamanho do efeito:** correlação bisserial por postos (ou d de Cohen pareado) e estimador de Hodges-Lehmann para a diferença típica em ms.
5. **PP2:** regressão da razão sem/com sobre o log do tamanho, ou Spearman entre tamanho e razão.
6. **Múltiplos testes:** correção de Holm entre as 12 consultas.
7. **Dashboard:** gráficos de razão por volume e de tempo poupado por dia.

## 10. Estimativa de impacto (plano)

Tempo poupado por dia = (tempo médio sem índice - tempo médio com índice) × número de listagens por dia.

Número de listagens por dia vem das métricas de produção (`<coletar>`). Resultado traduzido como "horas de espera evitadas por mês para a equipe", sempre com a fonte e a data de acesso, e com a ressalva do que **não** é possível afirmar (seção 8).

## 11. Reaproveitamento dos laboratórios anteriores

| Lab | O que será reaproveitado |
|---|---|
| Lab02 | Desenho de experimento com tratamentos e repetições. |
| Lab03 | Conceitos de operação (DORA e tempo de recuperação) para contextualizar o impacto. |
| Lab04 | Escolha do teste de hipótese, simulação de erro tipo I e poder, dashboard. |

O que é novo: o objeto (software em operação, não repositório), o experimento controlado em banco de dados e a estimativa de impacto.

## 12. Coleta piloto (fim da Sprint 1)

- Gerar o menor volume (10 mil linhas) para 2 tabelas (por exemplo `ocorrencias` e `fichas`).
- Rodar as 2 condições com 10 repetições para validar o script, o formato do CSV e o tempo total de execução.
- Registrar o resultado preliminar, sem concluir nada.

## 13. Ética

- Nenhum dado pessoal de usuários ou de fichas sai do sistema.
- Nenhum teste de carga em produção. Em produção, apenas leitura passiva de métricas.
- Segredos (`.env`, chaves do Firebase, `JWT_SECRET`, credenciais do banco) nunca entram neste repositório.

## 14. Divisão do trio (sugestão)

| Integrante | Papel | Responsável por |
|---|---|---|
| A | Planejamento e método | Critérios, 7 categorias, GQM, hipóteses, ameaças. |
| B | Instrumentação e operação | Gerador de dados, benchmark, execução, validação. |
| C | Análise e impacto | Estatística, tamanho de efeito, dashboard, estimativa de impacto. |

## 15. Cronograma

| Entrega | Conteúdo |
|---|---|
| Lab05S01 | Esta proposta e a coleta piloto. |
| Lab05S02 | Coleta completa, dados validados e versionados, análise e ameaças. |
| Lab05S03 | Impacto, 7 categorias revisadas, conclusões e limitações, rascunho do documento e da apresentação. |
| Final | Documento e apresentação de 10 minutos. |

Repositório: https://github.com/yanresende/lab5-medicao-experimentacao
