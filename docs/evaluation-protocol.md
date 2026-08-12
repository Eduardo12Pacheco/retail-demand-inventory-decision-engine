# Protocolo de evaluación — retail-demand-inventory-decision-engine

Estado: **implementado (versión 1.0 del protocolo)** — fijado ANTES de que se
materialice cualquier reporte.

## Propósito

Definir exactamente cómo se miden los pronósticos, las políticas de inventario y
las decisiones de reposición. El protocolo se fija antes de producir resultados
para que los números reportados no se moldeen para verse bien. Este documento es
normativo; el materializer (`src/retail_demand_inventory/evaluation/materialize.py`)
lo codifica.

## Frecuencia de datos y calendario

- **Frecuencia**: diaria. La `DemandTable` canónica está en una cadencia diaria
  estricta por SKU; los días internos faltantes se rellenan con
  `demand_units = 0.0` y `stockout_flag = None` por los loaders (ver
  `docs/source-contract.md`).
- Todas las fechas en la serie de un SKU son días de calendario consecutivos.

## Historial mínimo

- `MIN_TRAIN_PERIODS = 42` días. Un SKU debe tener al menos este número de
  observaciones antes del primer fold para ser evaluado. El fixture proporciona
  ~120 días por SKU, por lo que todos los SKUs califican.

## Splits (cronológicos, sin fuga)

- **Horizonte**: `HORIZON = 7` días.
- **Test final intacto**: los últimos `FINAL_TEST_PERIODS = 14` días del
  calendario. Esta ventana **nunca** se usa para la selección de modelos o
  políticas; se usa solo para el reporte final del modelo ya seleccionado.
- **Ventana de backtest**: todas las fechas anteriores al test final.
- **Orígenes**: orígenes móviles de ventana expansiva sobre la ventana de
  backtest.
  - Ventana de train: `calendar[0 : origin]` (expansiva; origin es el punto de
    corte).
  - Ventana de validación: `calendar[origin : origin + HORIZON]`.
  - Paso de origen = `HORIZON`, por lo que las ventanas de validación
    consecutivas son **disjuntas (sin superposición)** y el train de cada fold
    precede estrictamente a su validación.
  - Un fold existe solo si `len(train) >= MIN_TRAIN_PERIODS`.
- Los splits los calcula `data/splits.py` y se validan (sin superposición entre
  folds, ningún fold toca el test final, el train nunca contiene fechas de
  validación ni de test final).

## Criterios de SKU

- Un SKU se evalúa si tiene una serie diaria continua que soporta el historial
  mínimo requerido, al menos un fold y la ventana de test final. El fixture
  define 2 SKUs que cumplen estos criterios; la población real de snapshot se
  selecciona por la regla acotada documentada (ver más abajo).

## Sin fuga de features futuras

- Los modelos de pronóstico consumen solo: demanda observada pasada (lags y
  estadísticas móviles) y **features de calendario derivadas de la fecha misma**
  (día de la semana, día del mes, mes, día del año, flag de fin de semana).
- Las covariables futuras (descuento, festivo, actividad, clima) **no** se usan,
  por lo que ninguna feature futura no observada puede filtrarse en una
  predicción. Las features de calendario para fechas futuras son deterministas.

## Aleatoriedad

- Seed fijo `SEED = 20260811`. El pipeline es completamente determinista:
  cualquier paso estocástico (actualmente no se requiere ninguno, pero el seed
  está fijado de todos modos) se extrae de `random.Random(SEED)` / la
  configuración fija de sklearn. Dos ejecuciones del materializer con entradas
  idénticas producen reportes byte-idénticos.

## Modos de fuente

- **Modo fixture (por defecto, offline):** `materialize --source fixture` (o el
  `python -m retail_demand_inventory.evaluation.materialize` simple) se ejecuta
  sobre el fixture sintético comprometido. Lee solo archivos comprometidos bajo
  `data/fixtures/`, `data/manifests/`, `data/evaluations/` y **nunca toca la
  red**. Salida: `data/evaluations/experiment_report.json`.
- **Modo real (snapshot fijado):** `materialize --source real` se ejecuta sobre
  los archivos parquet crudos verificados bajo `data/raw/`. **Falla claramente**
  si los archivos crudos están ausentes, si algún gate de manifest no está
  verificado, si los checksums crudos/canónicos no coinciden o si el checksum
  canónico nunca se registró — **nunca cae al fixture**. Salida:
  `data/evaluations/freshretailnet-real-report.json`.

## Población real de snapshot (fijada antes de cualquier métrica)

La evaluación real es una **`Deterministic bounded evaluation over pinned
snapshot`** — NO es un resultado full-dataset y no generaliza.

Regla de población (el texto de la regla idéntico se registra en el manifest, el
schema report y el reporte): seleccionar las primeras `MAX_POPULATION_KEYS = 10`
claves en orden numérico ascendente de `(store_id, product_id)` entre las claves
que están **observadas en train** y cuyos registros combinados **train+eval**
abarcan al menos `REQUIRED_HISTORY_DAYS = 63` días consecutivos (el mínimo que
necesita el protocolo: `MIN_TRAIN_PERIODS + HORIZON + FINAL_TEST_PERIODS =
42 + 7 + 14`) Y comparten el tramo de fechas idéntico (el tramo modal entre las
claves elegibles, de modo que cada clave seleccionada cubra el mismo calendario
que exige el protocolo). **Sin muestreo aleatorio.** La regla de selección se
define en los docs y el manifest antes de calcular cualquier métrica y nunca se
cambia después de ver resultados. El reporte registra el conteo de filas de
fuente, el conteo de filas seleccionadas, el conteo de filas excluidas, las
claves seleccionadas/conteo, el rango de fechas y la regla.

### Población expandida (v2, opt-in)

v2 amplía la población determinista acotada a **100 claves** manteniendo la misma
regla de elegibilidad, snapshot y protocolo. Es opt-in vía un manifest de
población; el default v1 (10 claves, sin límite por tienda) no cambia.

| v1 (default) | v2 (opt-in vía manifest de población) |
| --- | --- |
| `MAX_POPULATION_KEYS = 10` | `TARGET_POPULATION_KEYS = 100` |
| sin límite por tienda | `PER_STORE_CAP_KEYS = 10` claves por tienda |
| sin manifest | `data/manifests/freshretailnet-real-population-v2.json` |
| reporte `freshretailnet-real-report.json` | reporte `freshretailnet-real-expanded-report.json` |

La elegibilidad para v2 es idéntica a v1 (observada en train, tramo combinado ≥
63 días, tramo de fechas modal). La regla v2 luego ordena las claves elegibles
por `(store_id, product_id)` ascendente, aplica el tope estructural de diversidad
de tiendas (a lo sumo 10 claves por tienda) y toma las primeras 100 claves en
total. Sin muestreo, sin métricas finales y sin filtros de rendimiento que
participen en la selección; la regla se congela antes de materializar cualquier
métrica. La selección usa **solo metadatos** (presencia de claves y tramos de
fechas) — la demanda y los valores de stockout nunca la influyen.

El modo real con `--population` carga exactamente las claves seleccionadas del
manifest y falla claramente (nunca cae) si la revisión fijada, los checksums
crudos, el esquema, las claves o los tramos de fechas divergen de la fuente, o si
el checksum canónico no coincide. Sin `--population`, el modo real mantiene el
comportamiento de 10 claves de v1 y el reporte v1.

El split `train`/`eval` del propio publicador NO se usa para la evaluación: este
proyecto re-corta cronológicamente sobre el tramo combinado de cada clave
seleccionada, tanto para v1 como para v2.

## Tratamiento de días faltantes y stockout

- Los días faltantes están ausentes de las filas crudas y se rellenan como ceros
  por los loaders; son entonces días ordinarios (con demanda cero), y un día
  faltante **nunca** se trata como un stockout.
- `stockout_flag` se deriva directamente del campo de fuente documentado
  `stock_hour6_22_cnt > 0` (entero validado en 0..17); un valor faltante
  permanece desconocido (`None`). **Las ventas cero nunca implican un stockout**
  (verificado sobre bytes reales: los días con stockout conservan ventas
  positivas).
- Los días con `stockout_flag` permanecen en la serie con su demanda observada
  (posiblemente cero). **Los pronósticos y las métricas apuntan a las ventas
  observadas, no a la demanda sin restricciones**; la censura se documenta, no se
  corrige.

## Política de hiperparámetros

- Todos los hiperparámetros de modelos y políticas usan los defaults
  documentados fijados en código. **Sin ajuste por SKU o por fold**, para evitar
  sesgo de selección en los datos de evaluación. Los identificadores versionados
  `model_version` / `policy_version` identifican la configuración exacta que
  produjo cada número.

## Métricas

Todas las métricas comparan la demanda observada `a_t` con la demanda predicha
`f_t` sobre una ventana de longitud `n`. Una métrica indefinida devuelve `None` y
se reporta como tal; los valores indefinidos nunca cuentan silenciosamente como
cero.

| Métrica | Definición | Caso indefinido |
| --- | --- | --- |
| MAE | `mean(|a_t - f_t|)` | sin observaciones → `None` |
| RMSE | `sqrt(mean((a_t - f_t)^2))` | sin observaciones → `None` |
| WMAPE | `sum(|a_t - f_t|) / sum(a_t)` | `sum(a_t) == 0` → `None` |
| MASE | `MAE / mean(|e_naive|)` donde `e_naive` son los errores naive in-sample de un paso de la ventana de train del mismo fold | errores naive de train ausentes o `mean(|e_naive|) == 0` → `None` |

## Granularidad del reporte

- **Por fold**: métricas por modelo de cada fold.
- **Por modelo**: métricas agrupadas en todos los folds más la media de las
  métricas por fold.
- **Por SKU** y **por categoría**: métricas agrupadas por esa clave.
- **Por horizonte**: los horizontes están fijos en `HORIZON` en este protocolo;
  el summarizer igualmente usa horizonte como clave para que la estructura del
  reporte sobreviva a un cambio de horizonte.
- Todos los números reportados se redondean a 6 decimales.

## Selección de modelo

- La selección ocurre **por SKU** y usa **solo folds de validación** (nunca el
  test final).
- Regla: minimizar el **MAE** agrupado de validación; desempatar por **WMAPE**
  agrupado más bajo; desempate final por `model_id` lexicográficamente menor.
- Después de la selección, el modelo elegido se reajusta en todos los datos
  anteriores al test final y se evalúa en el test final (reportado como
  `final_test`), y se reajusta en todo el historial para producir el pronóstico
  de despliegue para los próximos `HORIZON` días.

## Simulación y selección de política

- Las políticas se simulan con el motor determinista diario de ventas perdidas
  (`simulation/engine.py`); cada ejecución tiene un run ID auditable sobre su
  configuración, política, versiones, seed y fuente de demanda.
- **Ventana de evaluación de política**: la demanda de la ventana de validación
  del último fold (ventas observadas). El test final **no** se usa para la
  selección de política.
- Las políticas candidatas se generan determinísticamente a partir de
  estadísticas de demanda por SKU (media/desviación estándar) con parámetros
  documentados.
- Objetivo de selección: **minimizar el costo total sujeto a nivel de servicio ≥
  `SERVICE_LEVEL_TARGET = 0.90`**, donde el costo total = costo de tenencia +
  stockout + pedido sobre la ventana simulada.
- Caso infactible (ningún candidato alcanza el objetivo): caer al candidato con
  el mayor nivel de servicio simulado (empate → menor costo) y reportar
  `feasible = false` con una razón transparente. Esto es un fallback, no una
  solución "óptima" — ninguna selección en este proyecto se etiqueta nunca como
  óptima.
- Desempate determinista entre candidatos factibles: menor costo total, luego
  menores unidades de stockout, luego run ID lexicográficamente menor.
- **Sensibilidad**: la política seleccionada se re-simula con demanda escalada
  por `{0.9, 1.0, 1.1}`; el nivel de servicio, el fill rate y el costo total se
  reportan por escala.

## Supuestos y limitaciones (normativos)

1. La demanda es exógena a la política: la disponibilidad de inventario no cambia
   la serie de demanda usada en la simulación.
2. Las ventas perdidas durante un stockout están **perdidas, no en backlog**.
3. Los pedidos colocados al final de un día de revisión llegan al **inicio del día
   `lead_time` días después**; el lead time es constante; el suministro es
   ilimitado.
4. El costo de tenencia se carga sobre el inventario disponible al final del día;
   el costo de pedido se carga por pedido colocado; el costo de stockout se carga
   por unidad perdida.
5. La revisión ocurre después de la demanda del día (revisión de fin de período).
6. Sin perecibilidad/vencimiento, sin descuentos por cantidad, sin límites de
   capacidad.
7. Los pronósticos apuntan a **ventas observadas**; la demanda censurada durante
   stockouts no se recupera.
8. El fixture es sintético; **ningún número reportado es un resultado del mundo
   real**.

## Definición de terminado para la evaluación

- [x] Splits, seeds, horizontes y fórmulas de métricas comprometidos en este
      documento.
- [x] Un único comando reproducible reproduce cada número reportado:
  `uv run python -m retail_demand_inventory.evaluation.materialize` (fixture) y
  `uv run python -m retail_demand_inventory.evaluation.materialize --source real
  --manifest data/manifests/freshretailnet-real.json` (real, después de la
  adquisición y el schema report).
- [x] El reporte real expandido (v2) se reproduce con
  `uv run python -m retail_demand_inventory.evaluation.materialize --source real
  --manifest data/manifests/freshretailnet-real.json
  --population data/manifests/freshretailnet-real-population-v2.json`
  (después de generar el manifest de población con `population_manifest` y el
  perfil de dry-run con `population_profile`).
- [x] La comparación de baseline (pronóstico naive) está incluida en cada
      reporte.
- [x] Cada recomendación cita los run IDs de simulación que la respaldan.
- [x] El modo real está etiquetado `Deterministic bounded evaluation over pinned
  snapshot`, nunca full-dataset, y nunca cae al fixture. El modo expandido v2
  está etiquetado `Deterministic expanded bounded evaluation over pinned
  snapshot` y de igual manera nunca cae ni generaliza.
