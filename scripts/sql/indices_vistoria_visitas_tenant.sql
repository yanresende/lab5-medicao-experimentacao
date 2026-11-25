-- Indice simples de tenant da V76 em vistoria_visitas (idx_vistoria_visitas_tenant).
-- Faz parte do estado de producao e por isso existe nas DUAS condicoes do estudo
-- de vistorias.

CREATE INDEX IF NOT EXISTS idx_vistoria_visitas_tenant ON vistoria_visitas (tenant_id);
