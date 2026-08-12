# Demo Script — retail-demand-inventory-decision-engine

Estado: **implementada** — fixture-por-defecto y offline; los modos de snapshot
real se muestran solo cuando existe un reporte real verificado, y nunca se
re-etiquetan.

Capturas de pantalla en vivo de la aplicación están comprometidas bajo
`docs/assets/publication/`.

## Recorrido rápido (60–90 s)

Ejecute la aplicación y luego narre este flujo en orden:

1. **0–10 s — modo de datos y alcance.** Al título le sigue el banner rojo
   `Synthetic fixture — not a real business result` y el panel expandido de
   **Experiment status**: fuente de datos, licencia, checksum, seed, versiones de
   paquete / protocolo / esquema y la nota source-contract-vs-fixture. El panel
   de **Real snapshot status** está colapsado (las evaluaciones acotadas viven
   allí).
2. **10–30 s — pronóstico.** Elija un SKU en el selectbox. El gráfico de
   **Demand history and forecasts** muestra la demanda observada, el pronóstico
   de test final del modelo seleccionado vs real y el pronóstico de despliegue.
   La tabla de **Error metrics** muestra MAE / RMSE / WMAPE / MASE fuera de
   muestra.
3. **30–45 s — simulación de política.** **Policy comparison** lista cada política
   candidata simulada (nivel de servicio, fill rate, stockouts, costo total) con
   la seleccionada marcada, solo sobre el último fold de validación.
4. **45–60 s — recomendación y evidencia.** El bloque de **Recommendation**
   indica la política seleccionada, la cantidad de pedido, el servicio / fill /
   costo simulados y el **evidence run ID** (`recommendation_run_id`), más la
   tabla de sensibilidad a la escala de demanda.
5. **60–80 s — robustez.** Abra **Robustness (sensitivity over modeled business
   assumptions)**: el panel indica los avisos de supuesto-modelado y alcance-
   acotado, y luego el **scenario selector** (12 escenarios congelados) impulsa
   la comparación baseline-vs-escenario. Como el SKU de la demo es un SKU de
   fixture, el panel muestra honestamente la estabilidad a nivel de escenario en
   la población real v2 acotada (por ejemplo, 100 claves, % de retención de
   política) en lugar de una comparación real por clave.
6. **80–90 s — limitaciones.** Cierre con la lista de **Assumptions and
   limitations** y la etiqueta sintética explícita.

Línea de cierre a usar: la demo por defecto es un fixture sintético, no un
resultado de negocio real; las evaluaciones reales son deterministas, acotadas a
sus poblaciones y no generalizan.

## Qué muestra la demo

Una aplicación Streamlit sobre archivos comprometidos. El usuario elige un SKU y
ve:

1. **Experiment status** — información de dataset/manifest, seed fijo, versiones
   de protocolo y paquete, y la etiqueta prominente
   `Synthetic fixture — not a real business result`.
2. **Panel de estado de snapshot real** — si existe un reporte real verificado
   muestra la revisión fijada, la ruta/versión del manifest, el alcance
   determinista-acotado, la semántica de stockout y las limitaciones. Cuando
   existe el reporte **expandido (v2)** se muestra explícitamente con su id de
   población (`freshretailnet-real-population-v2`), conteos de claves/tiendas/
   productos, la advertencia de población acotada, la semántica de stockout y un
   resumen distribucional compacto (mediana/p25/p75/p95 de las métricas de test
   final y política). Si no existe ningún reporte real, muestra que el modo real
   no está disponible y da los comandos de recuperación exactos (adquisición →
   schema report → materialize).
3. **Demand history** para el SKU seleccionado (desde el fixture).
4. **Forecast comparison** — pronóstico de test final del modelo seleccionado vs
   demanda observada, más el pronóstico de despliegue para el próximo horizonte.
5. **Error metrics** — MAE / RMSE / WMAPE / MASE del reporte.
6. **Policy comparison** — cada política candidata simulada con nivel de servicio,
   fill rate, unidades/eventos de stockout y costo total.
7. **Recommendation** — política seleccionada, cantidad de pedido, servicio / fill
   / stockouts / costo simulados, estado de la restricción, razón, evidencia y run
   IDs.
8. **Robustness (sensitivity over modeled business assumptions)** — se muestra
   solo cuando existe el reporte de robustez comprometido
   (`data/evaluations/freshretailnet-robustness-report-v1.0.0.json`). Un selector
   de escenarios permite comparar `baseline-v1` contra cualquiera de los 12
   escenarios congelados para el SKU seleccionado (política, cantidad de pedido,
   reorder point / order-up-to level, servicio, costo) y muestra el resumen entre
   claves (% de retención de política, % de cambios, % infactibles). Renderiza
   las etiquetas exactas `Sensitivity analysis over modeled business assumptions
   — not observed retailer costs` y `Results are bounded to the deterministic v2
   population and do not generalize to all retailers.`
9. **Assumptions and limitations** — expuestas textualmente desde el reporte.

La demo distingue visiblemente el **source contract auditado**
(`docs/source-contract.md`, FreshRetailNet-50K), los **reportes de snapshot
real** opcionales (v1, v2 y el reporte de robustez) y el **fixture de desarrollo
sintético** que usan todos los gráficos y números: el fixture nunca se presenta
como datos reales, los reportes reales nunca se presentan como resultados
full-dataset o de producción, y los números de robustez nunca se presentan como
costos de minoristas observados.

## Restricciones

- Lee SOLO archivos comprometidos bajo `data/fixtures/`, `data/manifests/`,
  `data/evaluations/` y `data/reports/`. Los archivos crudos reales en
  `data/raw/` NO son leídos por la demo.
- **Sin acceso a red** en tiempo de ejecución.
- Streamlit es un extra opcional; el módulo se importa de forma segura sin él. La
  demo en sí requiere `--extra demo` para ejecutarse.

## Run book

```bash
uv sync --dev --extra demo
uv run --extra demo streamlit run scripts/demo_forecast.py
```

## Reproducir los reportes que lee la demo

Reporte de fixture (offline, por defecto):

```bash
uv run python -m retail_demand_inventory.evaluation.materialize
```

Reportes de snapshot real (la adquisición necesita red una vez, luego offline):

```bash
uv run python -m retail_demand_inventory.data.acquisition \
    --manifest data/manifests/freshretailnet-real.json --output-dir data/raw
uv run python -m retail_demand_inventory.data.schema_report \
    --manifest data/manifests/freshretailnet-real.json \
    --report data/reports/freshretailnet-real-schema.json
uv run python -m retail_demand_inventory.evaluation.materialize \
    --source real --manifest data/manifests/freshretailnet-real.json
```

Reporte real expandido (v2) — manifest de población opt-in + perfil de dry-run, y
luego materialize con `--population`:

```bash
uv run python -m retail_demand_inventory.data.population_manifest \
    --source-manifest data/manifests/freshretailnet-real.json \
    --raw-dir data/raw --out data/manifests/freshretailnet-real-population-v2.json
uv run python -m retail_demand_inventory.data.population_profile \
    --manifest data/manifests/freshretailnet-real.json \
    --report data/reports/freshretailnet-real-population-profile-v2.json
uv run python -m retail_demand_inventory.evaluation.materialize \
    --source real --manifest data/manifests/freshretailnet-real.json \
    --population data/manifests/freshretailnet-real-population-v2.json
```

Reporte de robustez — congele la matriz de escenarios y luego materialice sobre
la población v2:

```bash
uv run python -m retail_demand_inventory.decisions.scenarios \
    --out data/manifests/robustness-scenarios-v1.0.0.json
uv run python -m retail_demand_inventory.evaluation.robustness_materialize \
    --source real --scenarios data/manifests/robustness-scenarios-v1.0.0.json
```

Estos regeneran `data/evaluations/experiment_report.json` (fixture),
`data/evaluations/freshretailnet-real-report.json` (v1),
`data/evaluations/freshretailnet-real-expanded-report.json` (v2) y
`data/evaluations/freshretailnet-robustness-report-v1.0.0.json` (robustez) de
forma determinista.

## Qué la demo NO debe afirmar

- Sin números de precisión del mundo real: cada métrica está etiquetada como
  producida desde el fixture sintético.
- Los reportes de snapshot real (v1 y v2), cuando se muestran, están etiquetados
  como evaluaciones deterministas acotadas sobre el snapshot fijado y nunca se
  llaman resultados full-dataset.
- El reporte de robustez, cuando se muestra, está etiquetado `Sensitivity
  analysis over modeled business assumptions — not observed retailer costs` y
  `Results are bounded to the deterministic v2 population and do not generalize
  to all retailers.` Nunca se presenta como costos de minoristas observados ni
  como una generalización.
- Sin afirmación de que una política sea "la mejor": la demo dice que la política
  fue "seleccionada bajo el objetivo del protocolo", nunca "óptima".
