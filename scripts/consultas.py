"""Catalogo das consultas medidas.

Cada consulta reproduz o FORMATO de uma consulta real do Sentinela, observada em
producao via pg_stat_statements em 24/11/2026 (texto normalizado, sem dados), ou,
quando marcado como `assumida`, o formato esperado mas ainda nao confirmado.

Como a Fase 2 do multi-tenant (tenant automatico) entrou em producao em 24/11/2026,
o Hibernate passa a acrescentar `tenant_id = ?` a toda consulta de entidade. Por
isso TODAS as consultas abaixo levam o predicado de empresa como primeiro parametro
($1), inclusive nas subconsultas. As consultas de producao capturadas antes do
deploy nao mostram esse predicado.

Todas sao executadas como PREPARE + EXECUTE, para testar plano customizado e plano
generico (o pgjdbc passa a usar plano generico depois de 5 execucoes).

O padrao `($2 IS NULL OR unidade_id = $3)` e o das consultas reais: $2 nulo
significa usuario global DA EMPRESA (ve as duas unidades dela).

As medicoes sao sempre feitas para a empresa 1. As demais empresas (--empresas N no
gerador) so aumentam o volume de dados nas tabelas, como num banco compartilhado.
"""

import datetime as _dt
from dataclasses import dataclass

from comum import REFERENCIA

EMPRESA_MEDIDA = 1


@dataclass(frozen=True)
class Consulta:
    id: str
    estudo: str                      # "v2" ou "vistorias"
    origem: str                      # "real" (formato visto em producao) ou "assumida"
    controle: bool                   # True: o indice do estudo nao deveria ajudar
    tipos: str                       # tipos dos parametros, para o PREPARE
    sql: str
    variantes: tuple                 # ((rotulo, (param1, param2, ...)), ...)


def _unidades(*extras_lista):
    """Combina os tres filtros de unidade da empresa 1 (unidade 1, unidade 2, global)
    com listas de parametros extras. O primeiro parametro e sempre a empresa."""
    filtros = (("u1", (1, 1)), ("u2", (2, 2)), ("global", (None, None)))
    resultado = []
    for rotulo_f, (p1, p2) in filtros:
        for rotulo_e, extras in extras_lista:
            rotulo = f"{rotulo_f}|{rotulo_e}" if rotulo_e else rotulo_f
            resultado.append((rotulo, (EMPRESA_MEDIDA, p1, p2, *extras)))
    return tuple(resultado)


# Regra de alerta com limite de 30 dias (valor de configuracao assumido).
_LIMITE_30D = REFERENCIA - _dt.timedelta(days=30)

CONSULTAS = (
    Consulta(
        id="ocorrencias_unidade_data",
        estudo="v2",
        origem="assumida",
        controle=False,
        tipos="bigint, bigint, bigint, int",
        sql=(
            "SELECT * FROM ocorrencias o "
            "WHERE o.tenant_id = $1 AND ($2 IS NULL OR o.unidade_id = $3) "
            "ORDER BY o.data_vandalismo DESC LIMIT 50 OFFSET $4"
        ),
        variantes=_unidades(("off0", (0,)), ("off500", (500,))),
    ),
    Consulta(
        id="fichas_data_sem_foto",
        estudo="v2",
        origem="real",
        controle=False,
        tipos="bigint, bigint, bigint",
        sql=(
            "SELECT * FROM fichas f "
            "WHERE f.tenant_id = $1 AND f.ativo = true "
            "AND coalesce(trim(both from f.foto_url), '') = '' "
            "AND ($2 IS NULL OR f.unidade_id = $3) "
            "ORDER BY f.data_criacao DESC LIMIT 32"
        ),
        variantes=_unidades(("", ()),),
    ),
    Consulta(
        id="fichas_nome",
        estudo="v2",
        origem="real",
        controle=True,  # ordena por nome: os indices por data nao ajudam
        tipos="bigint, bigint, bigint, text, text, int",
        sql=(
            "SELECT * FROM fichas f "
            "WHERE f.tenant_id = $1 AND f.ativo = true AND ($2 IS NULL OR f.unidade_id = $3) "
            "AND ($4 = '' OR f.perfil LIKE ('%' || $5 || '%') ESCAPE '\\') "
            "ORDER BY f.nome OFFSET $6 LIMIT 20"
        ),
        variantes=_unidades(("off0", ("", "", 0)), ("off100", ("", "", 100))),
    ),
    Consulta(
        id="vistorias_alertas",
        estudo="vistorias",
        origem="real",
        controle=False,
        tipos="bigint, bigint, bigint, date, int",
        sql=(
            "SELECT v.*, greatest((SELECT max(vv.data_visita) FROM vistoria_visitas vv "
            "WHERE vv.tenant_id = $1 AND vv.vistoria_id = v.id), v.data_vistoria) "
            "FROM vistorias v "
            "WHERE v.tenant_id = $1 AND v.data_vistoria IS NOT NULL "
            "AND v.status1 IN ('ABERTO', 'NECESSARIO_REPARO') "
            "AND v.em_rota = true "
            "AND ($2 IS NULL OR v.unidade_id = $3) "
            "AND greatest((SELECT max(vv2.data_visita) FROM vistoria_visitas vv2 "
            "WHERE vv2.tenant_id = $1 AND vv2.vistoria_id = v.id), v.data_vistoria) <= $4 "
            "ORDER BY greatest((SELECT max(vv3.data_visita) FROM vistoria_visitas vv3 "
            "WHERE vv3.tenant_id = $1 AND vv3.vistoria_id = v.id), v.data_vistoria) ASC "
            "LIMIT $5"
        ),
        variantes=_unidades(("", (_LIMITE_30D, 50)),),
    ),
    Consulta(
        # Tratamento (nao existe em producao): a mesma regra de alerta, com o max(data_visita)
        # calculado UMA vez por vistoria numa subconsulta agregada, em vez de tres subconsultas
        # correlacionadas por linha. greatest() ignora nulos, como na consulta original.
        id="vistorias_alertas_reescrita",
        estudo="vistorias",
        origem="proposta",
        controle=False,
        tipos="bigint, bigint, bigint, date, int",
        sql=(
            "SELECT v.*, greatest(m.ultima_visita, v.data_vistoria) AS ultima "
            "FROM vistorias v "
            "LEFT JOIN (SELECT vv.vistoria_id, max(vv.data_visita) AS ultima_visita "
            "FROM vistoria_visitas vv WHERE vv.tenant_id = $1 GROUP BY vv.vistoria_id) m "
            "ON m.vistoria_id = v.id "
            "WHERE v.tenant_id = $1 AND v.data_vistoria IS NOT NULL "
            "AND v.status1 IN ('ABERTO', 'NECESSARIO_REPARO') "
            "AND v.em_rota = true "
            "AND ($2 IS NULL OR v.unidade_id = $3) "
            "AND greatest(m.ultima_visita, v.data_vistoria) <= $4 "
            "ORDER BY greatest(m.ultima_visita, v.data_vistoria) ASC "
            "LIMIT $5"
        ),
        variantes=_unidades(("", (_LIMITE_30D, 50)),),
    ),
)


def consultas_do_estudo(estudo: str) -> list[Consulta]:
    return [c for c in CONSULTAS if c.estudo == estudo]
