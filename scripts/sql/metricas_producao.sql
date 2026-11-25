-- Metricas de producao do Sentinela para a Lab05S01 (evidencias dos 3 criterios).
--
-- SOMENTE LEITURA e SOMENTE AGREGADOS: nenhuma consulta devolve nome, e-mail, CPF
-- ou qualquer dado pessoal. Rode em transacao somente leitura (primeira linha).
-- Cole no resultado apenas o que as consultas devolverem. Nunca cole credenciais.
--
-- Como rodar: psql, DBeaver ou o console de dados do Railway, conectado ao banco
-- de producao com um usuario de leitura se houver. Uma consulta por vez.

BEGIN READ ONLY;

-- ============================================================================
-- 1. Ambiente: versao do PostgreSQL e tamanho do banco
-- (usar a versao em PG_VERSION no docker-compose)
-- ============================================================================
SELECT version()                                          AS versao_postgres,
       pg_size_pretty(pg_database_size(current_database())) AS tamanho_banco;

-- ============================================================================
-- 2. "Em operacao": ultima migracao aplicada (proxy de ultimo release/deploy)
-- ============================================================================
SELECT max(installed_on)                       AS ultima_migracao_em,
       count(*) FILTER (WHERE success)         AS migracoes_aplicadas,
       max(installed_rank)                     AS maior_rank
FROM flyway_schema_history;

SELECT version, description, installed_on
FROM flyway_schema_history
WHERE success
ORDER BY installed_rank DESC
LIMIT 5;
-- Observacao: o ultimo DEPLOY pode ser mais recente que a ultima migracao.
-- Confirme a data no painel do Railway (aba Deployments) e anote a fonte.

-- ============================================================================
-- 3. "Alto impacto": usuarios cadastrados (contagens, sem identificar ninguem)
-- ============================================================================
SELECT count(*)                          AS usuarios_total,
       count(*) FILTER (WHERE ativo)     AS usuarios_ativos_cadastro
FROM usuarios;

SELECT unidade_id, count(*) AS usuarios_ativos_cadastro
FROM usuarios
WHERE ativo
GROUP BY unidade_id
ORDER BY unidade_id NULLS FIRST;

-- ============================================================================
-- 4. Uso real: usuarios distintos com operacao auditada, por dia (ultimos 30 dias)
--
-- LIMITACAO: auditoria_logs registra operacoes de ESCRITA (create, update,
-- delete, upload). Nao ha tabela de login nem de leituras. Logo, isto e um limite
-- INFERIOR de usuarios ativos. Declarar isso no documento (ameaca de construto).
-- ============================================================================
SELECT ("timestamp")::date                 AS dia,
       count(DISTINCT usuario_id)          AS usuarios_distintos,
       count(*)                            AS operacoes
FROM auditoria_logs
WHERE "timestamp" >= now() - interval '30 days'
  AND usuario_id IS NOT NULL
GROUP BY 1
ORDER BY 1;

-- Resumo da serie acima: media, mediana e maximo de usuarios por dia
WITH dia AS (
    SELECT ("timestamp")::date AS d,
           count(DISTINCT usuario_id) AS u,
           count(*) AS ops
    FROM auditoria_logs
    WHERE "timestamp" >= now() - interval '30 days'
      AND usuario_id IS NOT NULL
    GROUP BY 1
)
SELECT count(*)                                              AS dias_com_atividade,
       round(avg(u), 1)                                      AS media_usuarios_dia,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY u)        AS mediana_usuarios_dia,
       max(u)                                                AS max_usuarios_dia,
       round(avg(ops), 0)                                    AS media_operacoes_dia,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY ops)      AS mediana_operacoes_dia
FROM dia;

-- Usuarios distintos em janelas de 7 e 30 dias, e historico total
SELECT
    count(DISTINCT usuario_id) FILTER (WHERE "timestamp" >= now() - interval '7 days')  AS usuarios_7d,
    count(DISTINCT usuario_id) FILTER (WHERE "timestamp" >= now() - interval '30 days') AS usuarios_30d,
    count(DISTINCT usuario_id)                                                          AS usuarios_historico,
    min("timestamp")::date                                                              AS primeiro_registro,
    count(*)                                                                            AS operacoes_historico
FROM auditoria_logs
WHERE usuario_id IS NOT NULL;

-- ============================================================================
-- 5. Volume de dados: linhas exatas das tabelas que a V2 indexou
-- (calibra os tamanhos do experimento: 10 mil, 100 mil, 1 milhao)
-- ============================================================================
SELECT t.tabela,
       (xpath('/row/c/text()',
              query_to_xml(format('SELECT count(*) AS c FROM public.%I', t.tabela), false, true, ''))
       )[1]::text::bigint AS linhas
FROM (VALUES ('ocorrencias'), ('apuracoes_furto'), ('fichas'), ('veiculos'),
             ('ferramentas'), ('vistorias'), ('campanas'), ('conscientizacoes'),
             ('vulnerabilidades'), ('queimadas'), ('ferro_velhos'), ('passagens'),
             ('auditoria_logs')) AS t(tabela)
WHERE to_regclass('public.' || t.tabela) IS NOT NULL
ORDER BY linhas DESC;

-- As 15 maiores tabelas por tamanho em disco (dados + indices)
SELECT relname                                            AS tabela,
       n_live_tup                                         AS linhas_estimadas,
       pg_size_pretty(pg_total_relation_size(relid))      AS tamanho_total,
       pg_size_pretty(pg_indexes_size(relid))             AS tamanho_indices
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 15;

-- ============================================================================
-- 6. Distribuicao por unidade e janela de datas (calibra o gerador sintetico)
-- ============================================================================
SELECT unidade_id,
       count(*)                                  AS linhas,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS percentual
FROM ocorrencias
GROUP BY unidade_id
ORDER BY unidade_id NULLS FIRST;

SELECT unidade_id,
       count(*)                                  AS linhas,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS percentual
FROM fichas
GROUP BY unidade_id
ORDER BY unidade_id NULLS FIRST;

SELECT min(data_vandalismo) AS data_mais_antiga,
       max(data_vandalismo) AS data_mais_recente,
       count(*) FILTER (WHERE data_vandalismo >= current_date - 365) AS ultimos_365_dias
FROM ocorrencias;

-- ============================================================================
-- 7. Os indices da V2 existem em producao? Sao usados?
-- idx_scan e o numero de varreduras desde o ultimo reset das estatisticas.
-- ============================================================================
SELECT s.relname        AS tabela,
       s.indexrelname   AS indice,
       s.idx_scan       AS varreduras_desde_reset,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS tamanho
FROM pg_stat_user_indexes s
WHERE s.indexrelname LIKE 'idx\_%\_unidade\_data%'
ORDER BY s.idx_scan DESC;

SELECT stats_reset FROM pg_stat_database WHERE datname = current_database();

COMMIT;

-- ============================================================================
-- 8. Latencia real das consultas (so funciona se pg_stat_statements existir)
-- Se der erro "relation does not exist", a extensao nao esta ativa: anote isso e
-- siga adiante (a V28 do Sentinela tenta cria-la, mas pode nao ter permissao).
-- Um segundo erro logo depois ("transaction is aborted") e consequencia do primeiro.
-- O texto das consultas vem normalizado (constantes viram $1, $2), sem dados.
-- ============================================================================
BEGIN READ ONLY;

SELECT calls,
       round(mean_exec_time::numeric, 3)   AS media_ms,
       round(max_exec_time::numeric, 3)    AS max_ms,
       round(total_exec_time::numeric, 0)  AS total_ms,
       left(regexp_replace(query, '\s+', ' ', 'g'), 160) AS consulta
FROM pg_stat_statements
WHERE query ILIKE '%unidade_id%'
  AND query ILIKE '%order by%'
  AND query ILIKE '%desc%'
  AND query NOT ILIKE '%pg_stat%'
ORDER BY calls DESC
LIMIT 20;

SELECT stats_reset FROM pg_stat_statements_info;

COMMIT;
