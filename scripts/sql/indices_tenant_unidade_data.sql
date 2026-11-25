-- Candidato A (NAO existe em producao): empresa na frente, depois unidade e data.
-- Com @TenantId toda consulta leva `tenant_id = ?`; este indice atende o filtro de
-- empresa, o de unidade e a ordem por data na mesma estrutura.

CREATE INDEX IF NOT EXISTS idx_ocorrencias_tenant_unidade_data ON ocorrencias (tenant_id, unidade_id, data_vandalismo DESC);
CREATE INDEX IF NOT EXISTS idx_fichas_tenant_unidade_data ON fichas (tenant_id, unidade_id, data_criacao DESC);
