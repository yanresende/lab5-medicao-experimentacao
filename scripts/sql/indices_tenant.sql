-- Indice simples de tenant da migracao V76 do Sentinela (idx_<tabela>_tenant), nas
-- tabelas dos estudos. Junto com os indices da V2, forma o estado de producao
-- ("producao"). Uma instrucao por linha.

CREATE INDEX IF NOT EXISTS idx_ocorrencias_tenant ON ocorrencias (tenant_id);
CREATE INDEX IF NOT EXISTS idx_fichas_tenant ON fichas (tenant_id);
