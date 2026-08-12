# AGENTS.md — retail-demand-inventory-decision-engine

## Objetivo

Construir pronóstico de demanda, simulación de políticas de inventario y
decisiones de reposición para retail. Proyecto independiente, greenfield. Puede
aprender de los baselines del proyecto existente `demand-inventory-optimizer`,
pero NO debe copiar su código.

## Estado

Implementación completa para el alcance declarado, con evaluaciones sintéticas
y evaluaciones reales acotadas documentadas.

## Límites

- NO modificar estos proyectos hermanos: `ecuador-job-market-intelligence`,
  `ecuador-mobility-reliability`, `demand-inventory-optimizer`,
  `ecuador-public-information-evidence-assistant`, `eduardo-github-profile`.
- La publicación actual ya está configurada en GitHub; no crear nuevos remotes
  ni hacer push sin autorización explícita del usuario.
- La fuente y licencia de FreshRetailNet-50K están auditadas y documentadas en
  `docs/source-contract.md`.

## Estructura

```text
src/retail_demand_inventory/   # paquete bajo layout src
tests/                         # pytest; solo tests reales, sin cobertura falsa
docs/                          # source contract, protocolo de evaluación, demo script
data/fixtures/                 # fixtures versionados pequeños
data/manifests/                # manifests versionados de artefactos capturados/procesados
data/raw/ data/processed/      # salida de ejecución gitignored
deploy/                        # notas de despliegue (más adelante)
```

## Comandos esperados

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run --extra demo streamlit run scripts/demo_forecast.py
```

## Política de datos

- Nunca comprometer `data/raw/` ni `data/processed/`.
- Comprometer únicamente fixtures y manifests pequeños.
- La licencia y la fuente de cualquier dataset DEBEN estar auditadas y
  documentadas antes de su uso.

## CodeGraph

Usar el índice `.codegraph/` para consultas estructurales. Nunca comprometer su
contenido.

## Testing

Los tests deben verificar el comportamiento real que existe. Sin tests
placeholder que pretendan que las características existen.
