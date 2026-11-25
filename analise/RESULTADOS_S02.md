# Lab05S02: Coleta completa e análise

Relatório da Sprint 2: coleta completa das Matrizes A e B, validação e versionamento dos dados, análise estatística (descritiva, testes e tamanho do efeito) e ameaças à validade revisadas. O desenho está em `PROPOSTA.md` (seções 4 a 9).

Todos os números abaixo vêm da **réplica no ambiente do grupo**, com dados sintéticos. Nenhuma coleta nova foi feita em produção.

## 1. Coleta

| Item | Valor |
|---|---|
| Ambiente | PostgreSQL 17.11 em Docker (mesma versão da produção), `shared_buffers` 256 MB, `work_mem` 4 MB |
| Execuções | 14 (10 da Matriz A, 4 da Matriz B), orquestradas por `scripts/rodar_matrizes.py` |
| Medições | 47.880 (45.000 na Matriz A, 2.880 na Matriz B), 30 por célula, depois de 5 de aquecimento descartadas |
| Medições censuradas por tempo limite (60 s) | 0 |
| Validação | as 14 execuções passaram em `scripts/validar.py` (desenho balanceado, sem duplicatas, sem vazios) |
| Equivalência da reescrita | conferida antes de cada execução da Matriz B: mesmo resultado nas 3 variantes, nos 4 bancos |
| Duração total | 828 s |
| Semente | 42 em todas as execuções |
| Dados versionados | `dados/A_*.csv`, `dados/B_*.csv` e os `.meta.json` correspondentes |

A Matriz B rodou com a estatística de `tenant_id` **ausente**, como a produção hoje (seção 3.3 da proposta).

## 2. Calibração: a réplica reproduz a produção? (Q9)

| Observação | Produção | Réplica | Reproduziu? |
|---|---|---|---|
| Plano da listagem de fichas sem estatística em `tenant_id` | Bitmap no índice de tenant, sem usar o índice da V2 | O mesmo plano (condição `producao`, estatística `ausente`) | Sim |
| Erro de estimativa sem estatística | 8.010 reais contra 40 estimadas (200 vezes) | `ocorrencias`: mediana de 200 vezes, com 1 a 10 empresas | Sim |
| Tempo da consulta de alertas de vistorias com 351 vistorias | 491,5 ms | 2,7 ms (mediana, consulta original, sem índice) | **Não** |

O plano e o erro de estimativa foram reproduzidos. O tempo da consulta de vistorias **não** foi: no volume real a réplica leva cerca de 180 vezes menos. Isso confirma o que a proposta suspeitava: com 351 vistorias, a falta de índice não explica os 491 ms de produção. A causa está em outro lugar (largura das linhas de `vistorias`, outra parte da requisição ou o servidor), e como decidimos não fazer novas coletas em produção, ela fica em aberto. Os resultados da P3 valem para o efeito do volume e do índice, não para explicar o tempo de produção.

## 3. P1: o efeito da falta de estatística em `tenant_id`

**Resultado:** na condição `producao` (o estado de hoje: índices da V2 mais o índice simples de tenant), 34 das 150 comparações entre `ausente` e `atualizada` foram significativas depois da correção de Holm, **todas no mesmo sentido: sem estatística, a consulta fica mais lenta**. Nenhuma ficou mais rápida.

O caso mais claro é a listagem de ocorrências de uma unidade (primeira página, plano customizado):

| Empresas | Com estatística | Sem estatística | Razão | Plano sem estatística |
|---|---|---|---|---|
| 1 | 0,05 ms | 0,85 ms | 17 vezes | Bitmap mais Sort |
| 2 | 0,05 ms | 1,15 ms | 23 vezes | Bitmap mais Sort |
| 5 | 0,07 ms | 1,60 ms | 23 vezes | Bitmap mais Sort |
| 10 | 0,06 ms | 2,34 ms | 39 vezes | Bitmap mais Sort |
| 50 | 3,62 ms | 3,73 ms | 1 vez | os dois usam Bitmap mais Sort |

Com a estatística, o planejador usa `Index Scan` no índice da V2 e lê só a página pedida. Sem ela, estima `tenant_id = 1` em 0,5% da tabela (o padrão sem estatística), escolhe o índice de tenant, lê todas as linhas da empresa e ordena. O erro de estimativa mediano sem estatística foi de **200 vezes**, exatamente o que vimos em produção.

Na listagem de fichas por data, sem foto, a diferença é pequena: 25% das fichas não têm foto, a consulta não é seletiva e nenhum índice ajuda muito. É o resultado esperado e serve como contraste.

**Leitura:** a hipótese H1 (P1) é sustentada para as listagens seletivas. O efeito é grande em proporção (17 a 39 vezes) e pequeno em tempo absoluto (menos de 2,5 ms).

## 4. P2: como o tempo escala com o número de empresas

Tempo mediano da listagem de ocorrências de uma unidade (primeira página), de 1 para 50 empresas no banco:

| Configuração | Modo de plano | Estatística | 1 empresa | 50 empresas | Crescimento |
|---|---|---|---|---|---|
| `sem_indice` | customizado | atualizada | 0,78 ms | 11,94 ms | 15 vezes |
| `producao` (hoje) | customizado | atualizada | 0,05 ms | 3,62 ms | 72 vezes, mas abaixo de 4 ms |
| `producao` (hoje) | genérico | atualizada | 0,78 ms | 3,72 ms | 5 vezes |
| `tenant_data` | genérico | atualizada | 0,06 ms | 0,09 ms | **estável** |
| `tenant_data` | genérico | ausente | 0,96 ms | 3,88 ms | 4 vezes |

Três achados:

1. **Só `(tenant_id, data DESC)` com estatística atualizada mantém o tempo estável** de 1 a 50 empresas, inclusive com plano genérico e para o usuário global da empresa (0,05 a 0,08 ms). Sem estatística, ela perde a vantagem.
2. **Com plano genérico, o índice da V2 não serve para nada.** A configuração `v2` em modo genérico teve o mesmo tempo de `sem_indice` (cerca de 14 ms com 50 empresas). O padrão `($2 IS NULL OR unidade_id = $3)` impede o uso do índice que começa por `unidade_id` quando o plano é genérico, o que confirma a hipótese levantada na proposta.
3. **Achado inesperado: mesmo com estatística, o erro de estimativa cresce com o número de empresas.** A mediana de linhas reais sobre estimadas foi 0,9 com 1 empresa, 4,5 com 5, 10 com 10 e 48 com 50, ou seja, cerca de N. A explicação mais provável é que o planejador trata `tenant_id` e `unidade_id` como independentes, quando cada unidade pertence a uma única empresa. Ele multiplica as duas seletividades e subestima as linhas por um fator próximo do número de empresas. Com 50 empresas isso leva o planejador a abandonar o `Index Scan` mesmo com estatística (3,62 ms). Um teste natural para a Sprint 3 é a estatística estendida do PostgreSQL (`CREATE STATISTICS ... (dependencies) ON tenant_id, unidade_id`).

**Tempo absoluto:** em todas as configurações com índice, o tempo ficou abaixo de 5 ms mesmo com 50 empresas (400 mil linhas por tabela), e abaixo de 3 ms na escala prevista pelo sistema (2 a 5 empresas). Nenhuma listagem chegou perto do limiar de 100 ms. O problema é de **robustez do plano** (cai de 0,05 para 1 a 4 ms conforme a estatística e o modo de plano), não de lentidão perceptível hoje.

**Leitura:** H1 (P2) é sustentada em parte. O tempo cresce com o número de empresas em todas as configurações menos `tenant_data` com estatística. As configurações com `tenant_id` na frente só ficam estáveis quando a estatística existe.

## 5. P3: consulta de alertas de vistorias

Tempo mediano (plano customizado, todas as variantes):

| Banco | Original sem índice | Original com índice | Reescrita sem índice | Reescrita com índice |
|---|---|---|---|---|
| 350 vistorias, 1 empresa | 2,72 ms | 0,25 ms | 1,92 ms | 1,92 ms |
| 1.000, 1 empresa | 15,24 ms | 0,46 ms | 13,34 ms | 13,36 ms |
| 8.000, 1 empresa | 741,61 ms | 2,34 ms | 4,74 ms | 3,55 ms |
| 8.000 por empresa, 5 empresas | 1.176,68 ms | 11,79 ms | 7,29 ms | 7,30 ms |

- **O índice resolve a consulta original.** Razão mediana sem/com de 55 vezes, e as 24 comparações foram significativas. Sem índice, o tempo cresce de forma quase quadrática: de 1.000 para 8.000 vistorias (8 vezes mais linhas) ficou 49 vezes mais lento. Com 8.000 vistorias sem índice, a consulta já passa de 700 ms.
- **A reescrita também resolve, e não depende do índice** (só 9 de 24 comparações significativas, razão mediana 1,0). Ela fica entre 2 e 13 ms em todos os volumes.
- **A original com índice é a mais rápida até 8.000 vistorias**, e a reescrita é a mais rápida com 5 empresas (7,3 contra 11,8 ms). A hipótese H1 (P3b), de que a reescrita sem índice seria pelo menos tão rápida quanto a original com índice, **não** se sustentou nos volumes pequenos.
- **Anomalia explicada:** a reescrita levou 13 ms com 1.000 vistorias e só 5 ms com 8.000. Nos volumes pequenos, o planejador estimou 1 linha onde havia 38 a 108 e escolheu `Nested Loop`, que recalcula o agregado das visitas por linha. Nos volumes maiores escolheu `Hash Join`. É o mesmo problema da P1: a Matriz B rodou sem estatística em `tenant_id`, como a produção.

## 6. Ameaças à validade (revisadas com os dados)

| Tipo | O que os dados mostraram | Consequência |
|---|---|---|
| Conclusão | Diferenças de frações de milissegundo são muitas. A correção de Holm sobre 150 comparações por pergunta é conservadora e deixou de marcar algumas diferenças grandes em proporção. | Relatar tamanho de efeito (delta de Cliff e razão das medianas) junto com o p-valor, e não só a contagem de significativos. |
| Interna | Nenhuma medição censurada. Ordem de condições e modos sorteada. O plano em `ausente` coincidiu com o de produção. | Ameaça baixa para as conclusões sobre plano e estatística. |
| Construto | A consulta de vistorias não reproduziu o tempo de produção (2,7 ms contra 491 ms). | Os resultados da P3 mostram o efeito do volume, do índice e da reescrita, e **não** explicam o tempo de produção. Dito explicitamente nas conclusões. |
| Construto | A dependência entre `tenant_id` e `unidade_id` é perfeita na réplica (cada unidade pertence a uma empresa), como no modelo do Sentinela. | O erro de estimativa proporcional ao número de empresas é uma consequência do modelo de dados, não do gerador. Vale para empresas reais. |
| Externa | Empresas sintéticas iguais em tamanho e distribuição. Uma consulta de cada vez, sem concorrência. Sem RLS. | Os tempos absolutos não se generalizam. A direção dos efeitos (plano, estatística, escala) é o que se espera transferir. |

## 7. O que vai para a Sprint 3

- **Impacto:** traduzir os tempos para a escala de 2 a 5 empresas e para o uso real. A conclusão provável é que o impacto para o usuário é pequeno hoje e o risco está na robustez do plano.
- **Recomendações a avaliar:**
  - `ANALYZE` depois de migrações que adicionam colunas filtradas pelo Hibernate;
  - índice `(tenant_id, data DESC)` nas listagens principais;
  - índice composto em `vistoria_visitas` ou reescrita da consulta de alertas.
- **Teste opcional:** estatística estendida `(dependencies)` entre `tenant_id` e `unidade_id`, para ver se corrige o erro de estimativa que cresce com o número de empresas.
- **Gráficos** (issue de dashboard) e revisão das 7 categorias com os resultados.

## 8. Como reproduzir

```powershell
.\.venv\Scripts\python scripts/rodar_matrizes.py
.\.venv\Scripts\python analise/analisar.py dados/A_*.csv dados/B_*.csv
```

As tabelas completas ficam em `analise/resultados/`: `descritiva.csv`, `p1_estatistica.csv`, `indice_contra_sem.csv`, `p2_escala.csv`, `p3_reescrita.csv`, `erro_estimativa.csv` e `planos.csv`.
