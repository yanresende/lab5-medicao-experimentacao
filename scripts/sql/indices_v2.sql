-- Indices da migracao V2 do Sentinela (V2__indices_operacionais.sql, 09/08/2026),
-- limitados as tabelas do piloto. Definicao identica a da V2:
--   CREATE INDEX IF NOT EXISTS idx_<tabela>_unidade_data ON <tabela> (unidade_id, <coluna> DESC)
-- O benchmark le este arquivo, cria os indices na condicao "com_indice" e os remove
-- na condicao "sem_indice". Uma instrucao por linha, nomes no padrao da V2.
--
-- Na V2 real tambem existe um indice em (unidade_id, data_acionamento DESC) para
-- ocorrencias, criado depois (V28). Ele NAO entra aqui: o piloto isola o efeito
-- dos indices da V2.

CREATE INDEX IF NOT EXISTS idx_ocorrencias_unidade_data ON ocorrencias (unidade_id, data_vandalismo DESC);
CREATE INDEX IF NOT EXISTS idx_fichas_unidade_data ON fichas (unidade_id, data_criacao DESC);
