-- Candidato B (NAO existe em producao): empresa na frente, depois data.
-- Atende a listagem do usuario global da empresa (`$1 IS NULL`, sem filtro de unidade),
-- que ordena por data dentro da empresa e nao consegue usar um indice com
-- unidade_id na frente.

CREATE INDEX IF NOT EXISTS idx_ocorrencias_tenant_data ON ocorrencias (tenant_id, data_vandalismo DESC);
CREATE INDEX IF NOT EXISTS idx_fichas_tenant_data ON fichas (tenant_id, data_criacao DESC);
