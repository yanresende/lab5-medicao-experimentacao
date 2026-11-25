# Lab05S01: Proposta de experimento

**Disciplina:** Laboratório de Experimentação de Software (Engenharia de Software, 6º período, noite)
**Professor:** Danilo Maia
**Grupo:** Yan Araújo, Felipe Vieira
**Software estudado:** Sentinela (sistema de gestão operacional de segurança)
**Status:** rascunho da Sprint 1.

> Aprovação: o professor aprovou o uso do Sentinela como objeto de estudo em 24/11/2026 (conversa fora da plataforma).

---

## 1. Resumo

O Sentinela está migrando de uma empresa por deploy para **várias empresas (tenants) no mesmo banco**. A Fase 2 dessa migração entrou em produção em 24/11/2026 e faz toda consulta carregar `tenant_id = ?`. Ao observar o banco de produção, encontramos um problema concreto: **as 65 colunas `tenant_id` criadas pela migração V76 nunca passaram por `ANALYZE`**. Sem estatística, o planejador do PostgreSQL estimou 40 linhas onde havia 8.010 e escolheu o índice de tenant em vez do índice da V2, numa listagem de fichas.

Com uma empresa isso custa pouco. Com a segunda empresa o erro de estimativa começa a pesar, e o plano do sistema prevê de 2 a 5 empresas em 2 anos. Este trabalho **mede esse problema, mostra como ele escala com o número de empresas e avalia quais índices acompanham o crescimento**, com um estudo de caso da consulta que consome 73% do tempo do banco.

O estudo se organiza em **três perguntas**. O resto fica como análise de apoio.

## 2. O software e os três critérios

O Sentinela é um sistema web e mobile (PWA e APK Android) usado em produção por equipes de segurança patrimonial para registrar ocorrências, fichas de suspeitos, turnos, rotas, vistorias e patrulhas. Stack: Spring Boot 3.3 (Java 17), PostgreSQL 17.11, React 19, hospedado no Railway. O objeto de pesquisa é o **software em funcionamento** (a aplicação e seu banco), não o repositório de código. Não há mineração de commits, issues ou pull requests.

| Critério | Evidência | Fonte |
|---|---|---|
| Real | Sistema com mais de 50 controllers e cerca de 100 entidades, em uso por usuários reais fora do grupo. | Repositório do software (privado): https://github.com/yanresende/Site-Seguranca, e produção. O repositório é evidência de que o sistema existe, não o objeto de pesquisa. |
| Em operação | Em produção hoje, com deploy contínuo: última migração de banco aplicada em 24/11/2026 20:17, com 77 migrações aplicadas no total. Primeiro commit em 21/02/2026 e primeiro registro de auditoria em 03/04/2026. | `flyway_schema_history` e `auditoria_logs` de produção (consulta em 24/11/2026), histórico do repositório. Último deploy em 25/11/2026 (informado pelo mantenedor) |
| Alto impacto | 22 usuários cadastrados. Com escrita registrada: 8 usuários distintos nos últimos 7 dias, 11 nos últimos 30 dias e 12 no histórico. Média de 2,8 usuários distintos por dia (máximo 6) e de 26 operações por dia, em 28 dos últimos 30 dias. | `usuarios` e `auditoria_logs` de produção (consulta em 24/11/2026) |

**Limitação dos números de uso:** a auditoria registra só escritas (criar, editar, excluir, enviar foto). Não há registro de login nem de leituras, então os valores são um **limite inferior** do uso real.

**Limitação assumida (e aprovada pelo professor):** o impacto em escala absoluta é pequeno. Por isso o trabalho trata o impacto em duas camadas: o que acontece hoje (pequeno) e o que acontece quando o sistema crescer para 2 a 5 empresas (a escala que o próprio plano do sistema prevê).

## 3. O que a produção já mostra

Todas as observações abaixo vêm de consultas de **leitura** em produção (agregados, metadados e planos de execução, sem dados pessoais), feitas em 24 e 25/11/2026. Foi uma **coleta única**, usada para motivar e calibrar o estudo. Não haverá novas coletas, carga, usuários nem alterações em produção: **todos os experimentos rodam no ambiente do grupo**.

### 3.1 Volume de dados

Banco `railway`, PostgreSQL 17.11, 135 MB. Contagens exatas:

| Tabela | Linhas |
|---|---|
| `profissional_atividades` | 42.601 |
| `fichas` | 8.010 |
| `auditoria_logs` | 3.969 |
| `ocorrencias` | 1.001 |
| `vulnerabilidades` | 423 |
| `vistorias` | 351 (e 611 em `vistoria_visitas`) |
| demais tabelas operacionais | até 301 |

### 3.2 O plano de execução que chamou atenção

`EXPLAIN (ANALYZE, BUFFERS)` da listagem de `fichas` por `data_criacao` desc, sem foto, unidade 1:

| Item | Valor observado |
|---|---|
| Tempo de execução | 7,0 ms (a média antes da Fase 2 era 3,9 ms) |
| Método de acesso | `Bitmap Index Scan` em `idx_fichas_tenant`, depois `Bitmap Heap Scan` e `top-N heapsort` |
| Linhas lidas do índice de tenant | 8.010 (todas) |
| Linhas descartadas pelo filtro | 6.169, restando 1.841 |
| Estimativa do planejador | **40 linhas** para `tenant_id = 1` (real: 8.010) e 1 linha no final (real: 1.841) |
| Índice `idx_fichas_unidade_data` (V2) | **não foi usado** |
| Largura média estimada da linha | cerca de 3,4 kB |

A estimativa de 40 equivale exatamente a 0,5% de 8.010, a selectividade padrão quando **não há estatística da coluna**.

### 3.3 A causa: nenhuma coluna `tenant_id` tem estatística

| Tabela | `last_analyze` | `last_autoanalyze` | Modificações desde então |
|---|---|---|---|
| `fichas` | nunca | nunca | 602 |
| `ocorrencias` | nunca | nunca | 39 |
| `vistorias` | nunca | nunca | 43 |
| `vistoria_visitas` | nunca | nunca | 623 |

Em `pg_stats`, `fichas.unidade_id` tem estatística (`n_distinct` = 2) e `fichas.tenant_id` não tem nenhuma linha. Uma consulta geral listou **65 tabelas** com `tenant_id` sem estatística, que são todas as da V76. O autoanalyze padrão dispara com cerca de 50 mais 10% das linhas (perto de 850 em `fichas`, que está em 602); essa conta do gatilho é inferência, não medição.

**Por que isso piora com a segunda empresa:** hoje a empresa 1 tem 100% das linhas. Com duas empresas, `tenant_id = 1` devolveria metade da tabela e o planejador continuaria estimando 40 linhas.

### 3.4 O que domina o banco: a consulta de alertas de vistorias

Em `pg_stat_statements` (acumulado desde 23/11/2026 11:19), a listagem de `vistorias` ordenada por `greatest(max(data_visita) em subconsulta correlacionada, data_vistoria)` leva **491,5 ms em média** e consome **73,0% do tempo total de execução do banco** (426 chamadas). Todas as consultas ligadas à V2 somam menos de 3%.

Duas ressalvas: as 426 chamadas iguais indicam, provavelmente, que o motor de alertas calcula tudo a cada requisição de `/api/alertas` (a confirmar); e 491 ms com apenas 351 vistorias é alto demais para a falta de índice explicar sozinha, então a causa real pode ser outra.

### 3.5 Outros achados de apoio

- Os índices da V2 existem e são usados (3.740 varreduras em `idx_ocorrencias_unidade_data`, 1.587 em `idx_fichas_unidade_data`), mas são pequenos (16 kB a 336 kB).
- As consultas reais usam o padrão `($1 is null or unidade_id = $2)`, que em plano genérico pode impedir o uso do índice.
- O predicado de empresa aparece **duas vezes** nas consultas novas (`tenant_id = $1 and tenant_id = $2`). O repositório não o escreve, então vem do Hibernate.
- Depois da Fase 2, a consulta por data de fichas passou de 3,88 ms (426 chamadas) para 5,54 ms (28 chamadas). A amostra é pequena e o cache pode estar frio, então é indício, não prova.

## 4. Perguntas de pesquisa

**P1 (estatísticas, a central):** A ausência de estatística em `tenant_id` faz o planejador errar a estimativa e escolher o índice de tenant em vez do índice da V2? Quanto isso custa em tempo, comparado ao mesmo banco com a estatística atualizada?

**P2 (escala multi-tenant):** Quando o banco passa a ter 1, 2, 5, 10 e 50 empresas, o tempo das listagens de **uma** empresa se mantém? Qual configuração de índices acompanha melhor o crescimento: a de produção hoje, `(tenant_id, unidade_id, data DESC)` ou `(tenant_id, data DESC)`?

**P3 (estudo de caso):** Um índice `(tenant_id, vistoria_id, data_visita)` em `vistoria_visitas` reduz o tempo da consulta de alertas de vistorias, e a partir de que volume? E uma **reescrita da consulta**, que calcula a última visita uma vez por vistoria em vez de três subconsultas por linha, reduz mais do que o índice sozinho, ou os dois juntos?

**Análises de apoio (sem hipótese própria):**
- Efeito dos índices da V2 em si (`sem_indice` contra `v2`), o objetivo original do trabalho.
- Plano customizado contra plano genérico (`plan_cache_mode`), porque o driver Java usa plano genérico depois de 5 execuções.
- Tempo poupado por dia nas condições de hoje.
- Etapa opcional de concorrência na réplica (`pgbench`, várias conexões simultâneas com as consultas reais), só se o núcleo estiver pronto com folga.

### 4.1 Caminhos escolhidos e qualidade avaliada

Entre os caminhos sugeridos no enunciado, o trabalho **combina três**:

1. **Rodar o software no ambiente do grupo:** o PostgreSQL na mesma versão da produção (17), com os mesmos índices e as mesmas consultas reais, variando configuração (índices e estatísticas) e carga (número de empresas). A réplica reproduz o banco do Sentinela, não a aplicação inteira.
2. **Analisar dados de operação:** `pg_stat_statements`, planos de execução, estatísticas e contagens do banco de produção, numa coleta única e só de leitura, usada para motivar e calibrar os experimentos.
3. **Avaliar a qualidade do produto (ISO/IEC 25010):** a característica avaliada é a **eficiência de desempenho**, nas subcaracterísticas comportamento no tempo (tempo de execução) e capacidade (comportamento com mais empresas e mais dados).

## 5. GQM e hipóteses

**Objetivo (template de Basili):**
Analisar o efeito da ausência de estatística em `tenant_id` e da configuração de índices,
com o propósito de avaliar seu impacto,
quanto ao tempo de execução das listagens e da consulta de alertas,
do ponto de vista dos usuários e mantenedores do Sentinela,
no contexto de um banco PostgreSQL multi-tenant que passa de 1 para até 50 empresas.

| Pergunta | Métrica | Tipo | Escala |
|---|---|---|---|
| P1: o plano e o tempo mudam com a estatística? | M1: tempo de execução (ms), por `EXPLAIN (ANALYZE, BUFFERS)`. M2: erro de estimativa = linhas reais ÷ linhas estimadas no primeiro nó de varredura. M3: tipo do nó principal (Seq Scan, Index Scan, Bitmap, Sort) | Direta, derivada (M2) e nominal (M3) | Razão e nominal |
| P2: o tempo se mantém com mais empresas? | M1 por número de empresas. M4: razão entre M1 com N empresas e M1 com 1 empresa | Direta e derivada | Razão |
| P3: o índice, a reescrita ou os dois reduzem a consulta de vistorias? | M1, M2 e M3 aplicadas a `vistorias_alertas` (original) e `vistorias_alertas_reescrita`, sem e com o índice | Direta | Razão e nominal |
| Calibração: a réplica reproduz a produção? | M5: tempo médio de produção (`pg_stat_statements`) contra M1 da réplica no volume real | Direta | Razão |

Cuidado com armadilhas de medição (Goodhart): reportar mediana e p95 além da média, e olhar M2 e M3 para confirmar que a diferença vem do plano e não de cache.

**Hipóteses** (unidade de análise: consulta × número de empresas × condição, medida `n` vezes; α = 0,05):

- **H0 (P1):** o plano e o tempo mediano não dependem de existir estatística em `tenant_id`.
- **H1 (P1):** sem estatística, o erro de estimativa (M2) é grande, o plano usa o índice de tenant e o tempo é maior do que com a estatística atualizada.
- **H0 (P2):** o tempo mediano da empresa 1 não varia com o número de empresas.
- **H1 (P2):** o tempo cresce com o número de empresas na configuração `producao` com estatística ausente, e permanece estável nas configurações com `tenant_id` na frente e estatística atualizada.
- **H0 (P3):** o tempo mediano de `vistorias_alertas` é igual com e sem o índice.
- **H1 (P3):** o tempo é menor com o índice (unilateral), e a razão sem/com cresce com o volume.
- **H0 (P3b):** a reescrita sem índice tem o mesmo tempo mediano que a consulta original com índice.
- **H1 (P3b):** a reescrita sem índice é pelo menos tão rápida quanto a original com índice, porque lê as visitas uma vez só. A reescrita só entra como tratamento válido se devolver o **mesmo resultado** da original (conferido por `scripts/verificar_equivalencia.py`).

## 6. Planejamento do experimento

### 6.1 Duas matrizes

**Matriz A (P1 e P2): listagens de `ocorrencias` e `fichas`.**

| Fator | Níveis |
|---|---|
| Estatística de `tenant_id` | `ausente` (como produção hoje) e `atualizada` |
| Configuração de índices | **Núcleo:** `producao` (V2 mais índice simples de tenant), `tenant_unidade_data` (candidato `(tenant_id, unidade_id, data DESC)`), `tenant_data` (candidato `(tenant_id, data DESC)`). **Referência:** `sem_indice` e `v2` (rodam nas mesmas rodadas, sem hipótese própria) |
| Número de empresas | 1, 2, 5, 10 e 50 |
| Linhas por empresa | 8.000 (o volume de `fichas`; com 50 empresas chega a 400 mil por tabela) |
| Modo de plano | `custom` e `generic` (robustez) |

Consultas: `fichas_data_sem_foto` e `ocorrencias_unidade_data`, mais `fichas_nome` como **controle** (ordena por nome, os índices por data não deveriam ajudar). Cada uma com as unidades 1, 2 e "global da empresa" (`$2` nulo). As medições são sempre da empresa 1; as demais só aumentam o volume do banco, como num banco compartilhado. Os candidatos de índice são hipóteses de trabalho, não recomendações de mudança em produção.

**Matriz B (P3): consulta de alertas de vistorias.**

| Fator | Níveis |
|---|---|
| Configuração de índices | `sem_indice` (produção hoje, só o índice simples de tenant em `vistoria_visitas`) e `com_indice` |
| Versão da consulta | `original` (como está em produção) e `reescrita` (última visita calculada uma vez por vistoria, resultado equivalente) |
| Tamanho | 350 vistorias × 1 empresa (volume real), 1.000 × 1, 8.000 × 1 e 8.000 × 5 empresas |
| Modo de plano | `custom` e `generic` |

Sem índice, a consulta cresce de forma quase quadrática. Um tempo limite (`--timeout-s 60`) registra as medições estouradas como **censuradas**, não como erro.

### 6.2 Desenho

- **Pareado (within-subject):** o mesmo banco, com os mesmos dados, é medido em todas as condições. O benchmark remove todos os índices do estudo, cria os da condição e roda `ANALYZE` a cada troca. Com `--estatistica-tenant ausente`, remove as estatísticas de `tenant_id` depois de cada `ANALYZE`, reproduzindo a produção.
- **Validação da réplica:** com 8.000 fichas, 1 empresa e a condição `producao`, a estatística atualizada deu `Seq Scan` mais `Sort`, e a estatística ausente deu `Bitmap Index Scan` no índice de tenant, o mesmo plano visto em produção.
- **Consultas reais:** formato observado por `pg_stat_statements` (catálogo em `scripts/consultas.py`), executadas como consultas preparadas, todas com `tenant_id = $1`. `ocorrencias_unidade_data` tem formato assumido, a confirmar.
- **Randomização e repetições:** ordem de condições, modos e consultas sorteada pela semente; 30 medições por célula, após 5 de aquecimento descartadas.

### 6.3 Dados e instrumentação

- **Nunca usar dados reais do cliente.** O Sentinela guarda dados pessoais e de segurança. O experimento usa **dados sintéticos**, calibrados só por contagens agregadas de produção (por exemplo, 25% das fichas sem foto, vindo do plano de execução).
- PostgreSQL 17 em contêiner Docker, com a mesma configuração em todas as rodadas. Gerador (`gerar_dados.py --empresas N`), benchmark (`benchmark.py`) e validador (`validar.py`). Cada execução grava CSV e metadados (versão, configuração, semente).
- Produção: uma coleta única, só de leitura (seção 3). Nenhuma nova coleta, teste de carga, escrita ou usuário em produção.

### 6.4 Operação

1. Matriz A: 10 execuções (5 números de empresas × 2 estados de estatística), cada uma com `gerar_dados.py` e `benchmark.py --estudo v2`.
2. Matriz B: 4 execuções, com `benchmark.py --estudo vistorias --timeout-s 60`.
3. Antes da Matriz B, conferir que a reescrita é equivalente à consulta original (`verificar_equivalencia.py`). No teste com 8.010 vistorias, as três unidades deram resultados iguais.
4. Validar cada CSV (`validar.py`: sem vazios indevidos, sem duplicatas, desenho balanceado) e versionar.
5. Analisar com `analise/analisar.py` (seção 9).
6. **Opcional, se sobrar tempo:** concorrência na réplica, repetindo as consultas reais com várias conexões simultâneas (`pgbench`). Fica fora do núcleo e, se não for feita, entra nas limitações.

### 6.5 Calibração da réplica

**Feito (25/11/2026):**
- **Tamanho físico de `fichas`.** Em produção, 8.010 fichas ocupam 330 páginas de heap, cerca de 340 bytes por linha, e o resto da largura estimada de 3,4 kB fica fora da linha (TOAST). A réplica agora tem uma coluna larga fora da linha (`dados_extras`, 3.000 caracteres, sem compressão) e textos menores nas outras colunas. Resultado com 8.010 fichas: 320 páginas de heap (produção: 330) e cerca de 31 MB fora da linha. A coluna ocupa disco: 400 mil fichas (50 empresas) chegam a cerca de 1,2 GB, e o valor deve ser o mesmo em todas as execuções comparadas (`--largura-extra`).
- **Proporção de fichas sem foto:** 25%, a partir de 1.841 fichas sem foto na unidade 1 no plano de produção. Página de 32 linhas.
- **Limite do que se reproduz:** o `ANALYZE` ignora valores acima de 1 kB nas estatísticas, então a **largura que o planejador estima** (240 bytes na réplica, 3.420 em produção) não é reproduzível. Isso afeta só a estimativa de custo, não o tamanho físico nem o trabalho de leitura.
- **Tempo absoluto:** a largura das linhas não explica a diferença entre 7 ms em produção e cerca de 1 ms na réplica no mesmo plano. A causa mais provável é o hardware compartilhado do servidor de produção. Por isso a comparação com produção é feita pelo **plano escolhido e pela razão entre condições**, não pelo tempo absoluto.

**Pendente:**
- Distribuição de `status1` e `em_rota` em `vistorias`, e visitas por vistoria (hoje assumidas).
- Reproduzir os 491 ms de vistorias no volume real (351 vistorias). No teste com 8.010 vistorias a consulta original levou cerca de 420 ms, então no volume de produção deve ser muito menor, e a causa dos 491 ms em produção segue em aberto.

## 7. Classificação da pesquisa (as 7 categorias)

| Categoria | Classificação | Justificativa |
|---|---|---|
| Natureza | Aplicada | Resolve um problema prático de engenharia observado em produção. |
| Objetivos | Explicativa, com componente descritiva | Busca explicar como a falta de estatística e a configuração de índices determinam o plano e o tempo. Descreve também o estado de produção. |
| Abordagem | Quantitativa | Variáveis numéricas em escala de razão, com teste estatístico. |
| Procedimentos | Experimento (controlado, em laboratório) com calibração por um estudo de caso observacional | A réplica manipula os fatores. A produção foi observada uma vez, só para leitura, para calibrar a réplica. |
| Tempo | Transversal | O experimento é um recorte, e a observação de produção é uma foto de 24 e 25/11/2026. |
| Controle | Experimental | O grupo controla os fatores e o ambiente na réplica. Nada é controlado em produção. |
| Nível de evidência | Forte para o efeito técnico (controlado), limitado para o impacto em produção (uma foto, uma empresa, poucos usuários) | O desenho pareado e a randomização sustentam a causalidade na réplica. A generalização é limitada. |

Esta é a primeira versão. Será revisada na Lab05S03.

## 8. Ameaças à validade (versão inicial)

| Tipo | Ameaça | Mitigação |
|---|---|---|
| Conclusão | Variabilidade de medição de milissegundos. Medições censuradas por tempo limite nos volumes grandes sem índice. | 30 repetições por célula, teste não paramétrico, tamanho de efeito e intervalo de confiança. Reportar as censuras por célula e tratá-las como "pelo menos X ms", sem descartá-las. |
| Interna | Cache do banco distorcendo a segunda condição. Ordem das condições. Autovacuum refazendo estatística no meio da rodada. | Aquecimento descartado, ordem sorteada, mesmos dados em todas as condições, autovacuum desligado nas tabelas durante a rodada com estatística ausente. |
| Construto | Tempo de `EXPLAIN ANALYZE` não é a latência percebida. Dados sintéticos (linhas estreitas, distribuições assumidas). A réplica pode não reproduzir os 491 ms de vistorias em produção se a causa for outra. | Calibrar o gerador com agregados reais, comparar a réplica com a produção no volume real e, se não bater, investigar antes de concluir. |
| Construto | Empresas sintéticas idênticas, e a empresa medida é sempre a 1. A Row-Level Security (Fase 3) não é modelada e acrescentará custo por consulta. As consultas rodam uma de cada vez, sem concorrência de usuários. | Declarar o limite e tratar o resultado como efeito do volume, da estatística e dos índices isolados, sem contenção entre usuários. |
| Externa | Um único sistema, uma empresa, 22 usuários cadastrados (cerca de 11 ativos em 30 dias), um SGBD, tabelas de até cerca de 8 mil linhas. | Declarar que o resultado vale para consultas com filtro de empresa e unidade em PostgreSQL. Não generalizar para outros sistemas. |

## 9. Plano de análise

1. **Descritiva:** média, mediana, desvio, p95 e boxplots por (consulta, condição, estatística, número de empresas).
2. **P1:** `ausente` contra `atualizada` por **Mann-Whitney U**, com delta de Cliff (tamanho do efeito) e estimador de Hodges-Lehmann (diferença típica em ms). Foi escolhido no lugar do Wilcoxon pareado porque as duas condições são execuções diferentes, medidas em momentos diferentes: as amostras são independentes e não formam pares casados. Distribuição de M2 (erro de estimativa) e frequência de cada tipo de plano (M3).
3. **P2:** relação entre tempo e log do número de empresas (Spearman e inclinação de regressão), por configuração de índices e estado de estatística.
4. **P3:** Mann-Whitney U entre `sem_indice` e `com_indice`, e entre original e reescrita, com delta de Cliff e razão sem/com por tamanho. Medições censuradas por tempo limite ficam fora dos testes e são contadas à parte, com o limite inferior reportado.
5. **Múltiplos testes:** correção de Holm dentro de cada pergunta.
6. **Normalidade:** Shapiro-Wilk nas amostras, para confirmar que o teste não paramétrico é a escolha certa (tempos de consulta costumam ter cauda longa).
7. **Dashboard:** razão por número de empresas, e plano escolhido por condição.

## 9.1 Conceitos da disciplina aplicados

| Tema | Como aparece no estudo |
|---|---|
| Armadilhas de medição | **Goodhart:** mediana e p95 além da média, e o plano de execução como conferência, para o tempo não ser "jogado". **Falácia de McNamara:** o tempo de execução no banco é fácil de medir, mas não é a latência que o usuário percebe (rede e front-end ficam de fora), o que entra como ameaça de construto. |
| GQM | Objetivo no template de Basili, perguntas P1 a P3 e métricas M1 a M5 (seção 5). |
| Entidades e atributos | Entidade: o **produto** (uma consulta, um plano de execução). Atributos externos: tempo de execução e tempo de planejamento. Atributos internos: linhas lidas, blocos acessados, tipo do plano, erro de estimativa. Medidas diretas: tempo, linhas, blocos. Medidas derivadas: erro de estimativa (reais ÷ estimadas) e razão entre N empresas e 1 empresa. |
| Escalas | Razão (tempo, linhas, blocos, razões derivadas) e nominal (tipo do plano), cada uma com as estatísticas permitidas: mediana, Wilcoxon e Spearman para razão, e frequências para nominal. |
| Métricas de produto, processo e recurso | Produto: tempo e plano das consultas. Recurso: blocos e linhas lidos, memória do banco. Processo: cadência de migrações do Sentinela (77 migrações desde fevereiro de 2026) como indicador de que o sistema muda com frequência e por isso precisa de `ANALYZE` repetido. Em SLI e SLO: o tempo por listagem é o indicador, e 100 ms é o limiar de percepção que usamos. |
| Categorias de pesquisa | As 7 da seção 7, com justificativa. |
| Planejamento de experimentos | Hipóteses (seção 5), variáveis e fatores (6.1), objetos (consultas reais), design pareado, instrumentação e operação (6.2 a 6.4). |
| Ameaças à validade | Conclusão, interna, construto e externa, cada uma com mitigação (seção 8). |
| Análise | Estatística descritiva, teste de hipótese adequado à escala e tamanho do efeito (seção 9). |

## 10. Impacto

- **Hoje:** com uma empresa e tabelas de até 8 mil linhas, o ganho de acertar o plano é de poucos milissegundos por listagem. Isso será reportado como resultado, com o que **não** é possível afirmar.
- **Na escala prevista (2 a 5 empresas):** tempo de uma listagem com 1, 2, 5, 10 e 50 empresas, e o ponto em que passa a ser perceptível (por exemplo, acima de 100 ms por listagem). Os marcos de 2 a 5 empresas vêm do plano do próprio sistema (`docs/MULTITENANT.md`).
- **Ação decorrente:** a recomendação provável é rodar `ANALYZE` depois das migrações que adicionam colunas filtradas pelo Hibernate e antes de cada empresa nova entrar. O efeito de `ANALYZE` é medido na réplica (estado `atualizada` contra `ausente`), sem alterar a produção.

## 11. Reaproveitamento dos laboratórios anteriores

| Lab | O que será reaproveitado |
|---|---|
| Lab01 | Coleta automatizada de dados: os scripts coletam as medições de forma automática e repetível, só que sobre um banco em vez de uma API. |
| Lab02 | Desenho de experimento com tratamentos e repetições. |
| Lab03 | Conceitos de operação (DORA): a frequência de migrações aplicadas serve de indicador (proxy) da frequência de mudança do sistema. Reaproveitamento pequeno, só como contexto. |
| Lab04 | Escolha do teste de hipótese (aqui, Mann-Whitney por serem amostras independentes e de cauda longa), simulação de erro tipo I e poder, dashboard. |

O que é novo: o objeto (software em operação, não repositório), o experimento controlado em banco de dados e o ângulo multi-tenant.

## 12. Coleta piloto (fim da Sprint 1)

- Gerar um banco com 3 empresas e 2.000 linhas por empresa em cada tabela, e rodar os dois estudos com 10 repetições, para validar os scripts, o formato do CSV e o tempo total.
- Registrar o resultado preliminar, sem concluir nada.

## 13. Ética

- Nenhum dado pessoal de usuários ou de fichas sai do sistema.
- Nenhum teste de carga e nenhum usuário (real ou sintético) em produção. A carga é aplicada somente na réplica local.
- A produção foi consultada uma única vez, só para leitura de metadados, planos e contagens.
- Segredos (`.env`, chaves do Firebase, `JWT_SECRET`, credenciais do banco) nunca entram neste repositório.

## 14. Divisão da dupla

O grupo é uma dupla, então os três papéis sugeridos no enunciado se combinam em dois. Cada integrante é responsável por uma frente, mas **ambos acompanham e sabem explicar o estudo inteiro**, porque o professor pode pedir a qualquer um que explique qualquer parte.

| Integrante | Papel | Responsável por | Revisa |
|---|---|---|---|
| Yan Araújo | Instrumentação, operação e validação | Gerador de dados, benchmark, execução das matrizes A e B, validação e versionamento dos CSV, calibração da réplica com os dados de produção. | A análise estatística e as conclusões de impacto. |
| Felipe Vieira | Planejamento, método, análise e impacto | Critérios do software, 7 categorias, GQM, hipóteses, ameaças à validade, análise estatística, tamanho de efeito, dashboard, estimativa de impacto, documento e apresentação. | Os scripts, o desenho do experimento e a coerência com a proposta. |

## 15. Cronograma

| Entrega | Conteúdo |
|---|---|
| Lab05S01 | Esta proposta e a coleta piloto. |
| Lab05S02 | Coleta completa (matrizes A e B), dados validados e versionados, análise e ameaças. |
| Lab05S03 | Impacto, 7 categorias revisadas, conclusões e limitações, rascunho do documento e da apresentação. |
| Final | Documento e apresentação de 10 minutos. |

Repositório: https://github.com/yanresende/lab5-medicao-experimentacao
