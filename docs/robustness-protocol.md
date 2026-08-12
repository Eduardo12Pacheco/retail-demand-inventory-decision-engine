# Protocolo de robustez de decisiones — retail-demand-inventory-decision-engine

Estado: **implementado (manifest de escenarios `robustness-scenarios-v1.0.0`,
versión 1.0 del protocolo)** — la matriz de escenarios se congeló ANTES de que se
materializara cualquier métrica de robustez.

## Propósito

La robustez de decisiones mide cómo responde la capa de decisión de reposición a
**supuestos de negocio modelados**: objetivos de servicio, multiplicadores de
costo, tiempos de entrega, cadencia de revisión y una escala de demanda de estrés
de pronóstico. Re-ejecuta el pipeline de decisión sobre la **población v2
existente** con los mismos hechos de fuente, pronósticos, políticas candidatas,
seed, horizonte y folds, variando solo el supuesto declarado de cada escenario.
Responde: *¿cambia la política seleccionada (y su cantidad de pedido / reorder
point) bajo cambios plausibles de supuestos?*

**Los costos, tiempos de entrega y objetivos de servicio modelados NO son hechos
de minoristas observados.** Son supuestos documentados de
`docs/evaluation-protocol.md`, multiplicados por multiplicadores de escenario
para este análisis.

## Ruta rápida

1. Congele la matriz: `data/manifests/robustness-scenarios-v1.0.0.json` (generador
   tipado: `src/retail_demand_inventory/decisions/scenarios.py`).
2. Materialice:
   `uv run python -m retail_demand_inventory.evaluation.robustness_materialize
   --source real --scenarios data/manifests/robustness-scenarios-v1.0.0.json`
3. Lea `data/evaluations/freshretailnet-robustness-report-v1.0.0.json`; el
   escenario baseline-v1 debe igualar las decisiones v2 actuales.

## Hechos de fuente vs supuestos modelados

| Tipo | Ítem | Origen |
| --- | --- | --- |
| Hecho de fuente | Revisión fijada, SHA-256 crudo, checksum canónico | `data/manifests/freshretailnet-real.json` + `data/raw/` verificado |
| Hecho de fuente | Población v2 (100 claves / 10 tiendas / 40 productos) | `data/manifests/freshretailnet-real-population-v2.json` |
| Hecho de fuente | Derivación de stockout (`stock_hour6_22_cnt > 0`; las ventas cero nunca implican un stockout) | source contract auditado |
| Hecho de fuente | Semántica de ventas observadas (demanda censurada documentada, no recuperada) | `docs/source-contract.md` |
| Supuesto modelado | Objetivos de servicio, multiplicadores de costo, lead/review, estrés de demanda | manifest de escenarios (este análisis) |
| Supuesto modelado | Costos baseline 0.10/2.00/5.00 por unidad | `docs/evaluation-protocol.md` |

El reporte separa los dos: `source_facts` de nivel superior (nunca cambiados por
ningún escenario) y `modeled_assumptions` (variados). **Nada en las columnas de
costo/lead/servicio son datos de minoristas observados.**

## Configuración exacta de baseline

`baseline-v1` es la referencia actual exacta y debe reproducir las decisiones v2
actuales:

- Objetivo de servicio `0.90`; lead time `3` días; período de revisión `1` día.
- Tenencia `0.10` / unidad / día; stockout `2.00` / unidad perdida; pedido `5.00` /
  pedido (multiplicadores `1.0`).
- Demanda de selección: demanda observada del último fold de validación,
  **sin escala**.
- Demanda de despliegue/simulación: el pronóstico de despliegue, **sin escala**;
  las escalas de sensibilidad `{0.9, 1.0, 1.1}` se aplican como en el protocolo
  principal.

## La matriz de escenarios congelada (12 escenarios)

IDs estables; un factor a la vez más casos de estrés conjuntos. Baseline primero,
luego costo OFAT, lead, review, servicio, un caso conjunto y estrés de demanda al
final. Todos los demás parámetros son invariantes (ver más abajo).

| ID | Cambio respecto al baseline | Racional |
| --- | --- | --- |
| `baseline-v1` | ninguno (referencia actual exacta) | Reproduce las decisiones v2 actuales; referencia de comparación |
| `holding-high` | multiplicador de tenencia `2.0` | Mayor tenencia debería reducir la cobertura de inventario |
| `stockout-high` | multiplicador de stockout `2.0` | Mayor stockout debería elevar la cobertura de servicio |
| `ordering-high` | multiplicador de pedido `2.0` | Mayor costo fijo de pedido favorece pedidos más grandes y menos frecuentes |
| `costs-low` | tenencia/stockout/pedido `0.5` | Deflación uniforme: verifica que la selección no esté impulsada por escala |
| `lead-short` | lead time `2` días | Lead de suministro más corto |
| `lead-long` | lead time `5` días | Lead de suministro más largo |
| `review-weekly` | período de revisión `7` días | Cadencia de revisión semanal |
| `lead-review-long` | lead `5` y review `7` (estrés conjunto) | Combina el estrés de lead + review |
| `service-085` | objetivo de servicio `0.85` | Objetivo de decisión relajado |
| `service-095` | objetivo de servicio `0.95` | Objetivo de decisión endurecido |
| `demand-stress-high` | escala de demanda `1.30` (solo simulación de escenario) | 30% de estrés de pronóstico en la ventana de despliegue/simulación |

## Parámetros de protocolo sin cambios (invariantes)

Hechos de fuente, la población v2, modelos/versiones de pronóstico (`naive`,
`moving_average`, `ses`, `hist_gradient_boosting`), familias/versiones de
políticas candidatas, horizonte `7`, folds temporales (orígenes expansivos, test
final intacto), seed `20260811` y semántica observada de la ventana de selección.
El backtest se calcula una vez por población y se reutiliza; **ningún pronóstico
se re-entrena y ninguna política se ajusta a partir de los resultados de los
escenarios.**

## Población de evaluación v2

La población v2 exacta de `freshretailnet-real-population-v2.json` (100 claves de
tienda-producto en 10 tiendas, 40 productos, ~9,700 filas canónicas). La
selección usa solo metadatos; los resultados están acotados a estas claves y no
generalizan a todos los minoristas.

## Objetivo de selección y desempate

Objetivo: **minimizar el costo total sujeto a nivel de servicio simulado ≥
objetivo del escenario**; infactible → fallback transparente de mayor servicio
con `constraint_satisfied = false`. Desempate factible: menor costo total, luego
menores unidades de stockout, luego menor inventario promedio, luego run ID
menor. Desempate de fallback: mayor servicio, luego menor costo, luego run ID
menor. La selección es entre candidatos generados y nunca se etiqueta como óptima.

## Estrés de demanda solo en escenario

`demand-stress-high` modela `scale 1.30` **solo en la ventana de estrés de
despliegue/simulación**: la simulación de la recomendación y las ejecuciones de
sensibilidad `{0.9, 1.0, 1.1}` usan el pronóstico de despliegue multiplicado por
`1.30` (escalas de sensibilidad efectivas `1.17 / 1.30 / 1.43`). La demanda de
fuente, el entrenamiento de pronóstico, la evaluación de test final y la
**selección de políticas candidatas** no se tocan — la selección siempre usa la
demanda observada de la ventana de selección sin escala.

## Reglas de interpretación

- Compare cada escenario contra `baseline-v1` **por clave**; los deltas son
  escenario menos baseline sobre el resultado de la recomendación en la ventana
  de despliegue.
- `policy_retained` significa que se seleccionó el mismo `policy_id`; un cambio
  solo de parámetros se registra en los deltas de `trigger_level`/`order_quantity`.
- Los deltas relativos están indefinidos (reportados `null`) cuando el valor de
  baseline es 0.
- Los conteos de factibilidad/fallback provienen del resultado de selección, no
  del resultado de despliegue.
- `observed_tradeoffs` son resúmenes descriptivos neutrales (costo vs servicio,
  inventario vs fill, stockouts vs tenencia). **Nada es una afirmación de Pareto
  ni de optimalidad.**

## Serialización determinista y timestamps

Seed fijo, protocolo fijo y el timestamp determinista documentado
(`SOURCE_DATE_EPOCH` cuando se define, si no `2026-08-11T00:00:00+00:00`); JSON
con claves ordenadas e indentación fija. Dos ejecuciones idénticas producen
reportes byte-idénticos. El manifest de escenarios registra un `content_sha256`
estable sobre su serialización canónica. El runtime se registra como una
constante documentada, nunca un número de wall-clock, para que la salida repetida
permanezca byte-idéntica.

## Limitaciones

- Todos los números son análisis de sensibilidad sobre la población v2
  determinista; NO son costos de minoristas observados y no generalizan.
- Los costos/tiempos de entrega/objetivos de servicio modelados son supuestos, no
  hechos medidos.
- El escenario de estrés de demanda es un supuesto modelado de estrés de
  pronóstico; no altera la demanda de fuente ni el entrenamiento.
- Sin afirmación de optimalidad/Pareto; los resúmenes son observaciones
  neutrales.
- Los datos crudos permanecen en el `data/raw/` gitignored; solo se comprometen
  checksums.

## Definición de terminado

- [x] Matriz de escenarios congelada y comprometida antes de materializar
      métricas.
- [x] `baseline-v1` reproduce las decisiones v2 actuales.
- [x] Un comando reproduce el reporte byte-idéntico.
- [x] Los hechos de fuente y los supuestos modelados están separados en el
      reporte.
- [x] El reporte de robustez es distinto y nunca sobrescribe los reportes v1/v2.
