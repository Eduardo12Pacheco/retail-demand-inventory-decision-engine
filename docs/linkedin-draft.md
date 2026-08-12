# Publicación de LinkedIn — Retail Demand · Inventory Decision Engine

Idioma: español profesional neutro. Público objetivo: profesionales de retail,
supply chain y analítica. Los URLs de GitHub y de la demo quedan como
marcadores para completar antes de publicar.

---

**Borrador:**

¿Cuánto debería pedir un minorista y cuándo? La pregunta no la responde un
pronóstico, sino la simulación de una política de inventario. Por eso construí
un motor de decisiones de reposición que va del dato auditado a la recomendación
y, sobre todo, a la evidencia que la respalda.

**El problema de negocio.** Predecir la demanda no basta: un pronóstico no dice
cuánto inventario sostener ni cuándo reponer. La decisión real es una política
(reorder point / order-up-to) que se elige comparando costos de tenencia,
ruptura y pedido bajo una restricción de nivel de servicio. Y ninguna política
es confiable si no se prueba bajo supuestos que pueden estar equivocados.

**Qué construí.** Una cadena reproducible y determinista:

1. datos canónicos validados desde un snapshot de demanda auditado
   (FreshRetailNet-50K, revisión fijada, CC BY 4.0);
2. pronóstico temporal con cuatro modelos y selección en folds de validación;
3. simulación diaria de inventario lost-sales con dos familias de políticas;
4. recomendación por costo total mínimo sujeto a nivel de servicio, con run IDs
   y versiones auditables;
5. análisis de robustez sobre una matriz de 12 escenarios congelados.

**Tres detalles técnicos que me importan:**

- Cada recomendación adjunta evidencia: versión de código, seed fijo, run ID de
  simulación y ruta del reporte. Nada es una caja negra.
- Los hechos de fuente, los pronósticos, los supuestos de negocio y las
  recomendaciones se guardan separados en el reporte; el lector puede distinguir
  qué es observado y qué es modelado.
- La robustez no revalida los supuestos: muestra cuánto cambia la decisión
  cuando los supuestos cambian.

**Insight de robustez (alcance acotado).** Sobre 100 claves reales de la
población v2 y 12 escenarios pre-registrados, la política recomendada se
**mantuvo en el ≈98,3 % (1.081 de 1.100) pares escenario-clave no baseline**;
el 1,7 % cambió y el 10,7 % quedó sin candidato factible y usó el fallback
documentado. Estos números son deterministas, acotados a esa población y **no
se generalizan** a otros minoristas.

**Advertencia explícita.** Los valores de demanda provienen de un snapshot
auditado; los tiempos de entrega, niveles de servicio, períodos de revisión y
multiplicadores de costo son **supuestos modelados**, no costos ni contratos
observados. El proyecto no afirma optimalidad ni aptitud de producción.

**Limitaciones.** La demo por defecto es un fixture sintético, claramente
etiquetado; los resultados reales son evaluaciones acotadas y deterministas; no
hay ajuste de hiperparámetros por SKU ni features de promociones/clima.

**Lo que quiero que se lleven:** el pronóstico por sí solo es insuficiente; las
políticas deben simularse; las recomendaciones deben estresarse; y los hechos de
fuente deben separarse de los supuestos de negocio. La confianza no viene del
modelo, viene de la evidencia reproducible.

Código: [GitHub URL]
Demo: [Demo URL]

---

**Notas de publicación**

- Reemplazar `[GitHub URL]` y `[Demo URL]` antes de publicar.
- Números citados de `data/evaluations/freshretailnet-robustness-report-v1.0.0.json`
  (retention 1081/1100 = 98,27 %; changed 19/1100; infeasible 118/1100) y de los
  reportes v1/v2 comprometidos.
- No usar términos como "óptimo", "IA", "producción" ni generalizaciones.
- En negrita, solo los énfasis ya indicados.
