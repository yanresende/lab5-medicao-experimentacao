-- Intervencao do estudo de caso "vistorias" (nao existe em producao hoje).
--
-- A consulta de alertas de vistorias calcula, por vistoria, a subconsulta
--   (SELECT max(data_visita) FROM vistoria_visitas WHERE tenant_id = ? AND vistoria_id = v.id)
-- tres vezes (select, where e order by). Hoje so existe o indice simples de tenant
-- (idx_vistoria_visitas_tenant, V76), que nao ajuda a achar as visitas de UMA vistoria.
-- O indice composto cobre os dois filtros de igualdade e o max() (varredura so de indice).
--
-- O benchmark cria este indice na condicao "com_indice" e o remove em "sem_indice".

CREATE INDEX IF NOT EXISTS idx_vistoria_visitas_tenant_vistoria_data ON vistoria_visitas (tenant_id, vistoria_id, data_visita);
