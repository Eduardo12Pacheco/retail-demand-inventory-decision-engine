# Product — retail-demand-inventory-decision-engine

Estado: **implementado como prototipo sobre fixture sintético** (sin datos reales
usados; cada número reportado está explícitamente etiquetado como sintético).

## Plataforma

Web (demo local) + pipeline de análisis offline.

## Usuarios

- Planificadores de inventario que necesitan una recomendación de reposición
  defendible.
- Evaluadores técnicos que quieren verificar la metodología de pronóstico y
  simulación antes de confiar en un número.
- El autor: demostrar habilidades de pronóstico, simulación y ciencia de
  decisiones con evidencia reproducible.

## Problema

Los pronósticos y las políticas de inventario solo son útiles si su evidencia es
auditable. Sin un protocolo de evaluación fijo, cualquier mejora reportada puede
ser el resultado de cherry-picking. Este producto hace de la evaluación la pieza
central: cada decisión de reposición es trazable a una ejecución de simulación
puntuada.

## Qué NO es todavía

- No es un servicio de pronóstico, sin API, sin despliegue de producción.
- No está integrado con ningún sistema retail en vivo.
- No afirma ninguna precisión sobre datos reales (ninguno ha sido auditado
  todavía).
- Los números de robustez son análisis de sensibilidad sobre supuestos de
  negocio modelados (costos/tiempos de entrega/objetivos de servicio), nunca
  costos de minoristas observados.

## Métrica de éxito (producto)

Un revisor puede ejecutar un comando, ver un pronóstico y una simulación de
política con baselines, y trazar la acción recomendada hasta su evidencia de
simulación — sin leer código.

## Riesgos

- Acceso al dataset: todo el pipeline depende de una fuente auditada y con
  licencia.
- Confianza en la metodología: splits sin fijar invalidarían cada resultado.

## No-objetivos

- Sin SaaS multi-tenant, sin cuentas de usuario.
- Sin aplicación móvil.
- Sin streaming en tiempo real; el análisis por lotes es el patrón.

## Definición de terminado

- [ ] La demo responde "¿debería reponer X y por qué?" con evidencia en menos de
      un minuto.
- [ ] Cada número reportado es reproducible con un comando.
- [ ] Los baselines y las limitaciones están documentados junto a los
      resultados.
