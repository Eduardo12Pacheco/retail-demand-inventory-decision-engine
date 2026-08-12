# Design — retail-demand-inventory-decision-engine

Estado: **implementado como prototipo sobre fixture sintético** (sin datos
reales usados; ver `docs/source-contract.md`).

## Problema

Los minoristas necesitan pronósticos de demanda y políticas de inventario que
sean defendibles: un pronóstico que nunca se compara con la realidad, o una
política ajustada para verse bien en datos pasados, no es un motor de
decisiones. Este proyecto construye un pipeline pequeño y reproducible que va de
los datos de demanda a una recomendación de reposición, con la evaluación como
ciudadana de primera clase.

## Arquitectura planificada

```text
src/retail_demand_inventory/
├── data/          # loaders tipados sobre el source contract
├── forecasting/   # modelos de pronóstico detrás de una interfaz
├── simulation/    # simulación de políticas de inventario por eventos discretos
├── decisions/     # reglas de reposición sobre la salida de la simulación
└── evaluation/    # métricas impulsadas por protocolo, agregación/materialización de robustez
```

Cada capa es reemplazable y solo depende de interfaces documentadas.

## Decisiones clave

| Tema | Decisión |
| --- | --- |
| Lenguaje | Python >=3.11, `uv`, layout src de hatchling |
| Interfaz de pronóstico | `fit(train_data) / predict(future_context, horizon)` sobre `DemandTable` de un solo SKU; naive, moving average, SES, histogram gradient boosting |
| Simulación | Motor determinista diario de ventas perdidas, seed fijo, política-in → resultados-out, run IDs auditables |
| Evidencia | Cada recomendación cita los run IDs de simulación, versiones y rutas de reporte que la respaldan |
| Robustez de decisión | Manifest de 12 escenarios congelados (`decisions/scenarios.py`), ejecutor `evaluation/robustness_materialize.py`, agregación `evaluation/robustness.py`; las re-ejecuciones varían solo los supuestos declarados; hechos de fuente vs supuestos modelados separados |
| Demo | Aplicación Streamlit local que lee solo fixtures comprometidos y el reporte generado |

## No-objetivos

- Sin integración con tienda en vivo, sin ingesta POS real todavía.
- Sin afirmación de aptitud para producción de decisiones de negocio reales.
- Sin copia de código ni datos de `demand-inventory-optimizer`.

## Riesgos

- Licencia/fuente del dataset no disponible → el trabajo de pronóstico queda
  bloqueado por diseño.
- Fuga de datos en los splits → prevenida por el protocolo de evaluación de
  tiempo fijo.
- Políticas sobreajustadas → comparaciones de baseline requeridas en cada
  reporte.

## Definición de terminado (para el proyecto, no solo el scaffold)

- [ ] Source contract satisfecho con un dataset auditado y con licencia.
- [ ] Pipeline reproducible de pronóstico + simulación + decisión.
- [ ] Protocolo de evaluación ejecutado y reportado.
- [ ] Demo se ejecuta desde fixtures sin acceso a red.
- [ ] Sin afirmaciones sin respaldo en README ni docs.
