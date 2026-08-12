# Source Contract — retail-demand-inventory-decision-engine

Estado: **auditado / ACEPTADO con condiciones; snapshot real adquirido,
verificado y evaluado sobre una población acotada** (fecha de auditoría +
adquisición 2026-08-11). Los datos de fuente NO se retienen en este repositorio
(los archivos crudos viven en el `data/raw/` gitignored). El desarrollo/tests/
demo offline se ejecutan sobre el fixture sintético comprometido (ver
[Fixture sintético](#fixture-sintético—no-un-resultado-de-fuente-auditado)).

## Propósito

Definir los requisitos exactos que debe cumplir un dataset de demanda antes de
implementar cualquier función de pronóstico, simulación o reposición, y registrar
la auditoría completada del candidato de fuente principal. Este contract debe
satisfacerse y documentarse ANTES de que el código toque datos de fuente reales.

## Registro de auditoría — FreshRetailNet-50K

| Propiedad | Valor |
| --- | --- |
| Nombre del dataset | FreshRetailNet-50K |
| Editor | Dingdong Limited (org de Hugging Face `Dingdong-Inc`) |
| URL oficial | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K |
| Snapshot fijado (revisión) | `08c1fab7f9257bc73679d415d65d644165d351d4` |
| URL del snapshot fijado | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/tree/08c1fab7f9257bc73679d415d65d644165d351d4 |
| Fecha de recuperación / auditoría | 2026-08-11 |
| Versión del dataset | 1.0 (fecha de lanzamiento 2025-05-08) |
| Semántica del snapshot | Pin de commit en el repo de Hugging Face; los bytes exactos que la tarjeta del dataset describía al momento de la auditoría |
| Licencia | Creative Commons Attribution 4.0 International (CC BY 4.0) |
| URL de la licencia | https://creativecommons.org/licenses/by/4.0/legalcode |
| Declaración de la tarjeta sobre el uso | "This dataset is ready for commercial/non-commercial use." |
| Reporte técnico | arXiv:2505.16319 (https://arxiv.org/abs/2505.16319) |
| Repo de baseline | https://github.com/Dingdong-Inc/frn-50k-baseline (solo referencia, no copiado) |
| Tamaño | 4,850,000 filas (train 4.5M / eval 350k), ~115 MB |

### URLs de evidencia (exactas, fijadas)

| Recurso | URL |
| --- | --- |
| Página del dataset | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K |
| Árbol fijado | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/tree/08c1fab7f9257bc73679d415d65d644165d351d4 |
| README fijado | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/raw/08c1fab7f9257bc73679d415d65d644165d351d4/README.md |
| URL resolve de train | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/08c1fab7f9257bc73679d415d65d644165d351d4/data/train.parquet |
| URL resolve de eval | https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/08c1fab7f9257bc73679d415d65d644165d351d4/data/eval.parquet |

### Archivos crudos adquiridos (locales, gitignored) — observado vs metadatos de HF

Los archivos crudos se conservan SOLO bajo `data/raw/` (gitignored, nunca
comprometidos). Los tamaños y SHA-256 observados se calcularon sobre los bytes
descargados intactos; los valores esperados son los metadatos LFS de HF
reportados en la revisión fijada. Ambos archivos coincidieron exactamente, y el
endpoint resolve reportó `x-repo-commit == 08c1fab7…` al momento de la descarga.

| Split | Archivo local (bajo `data/raw/`) | Filas | Tamaño esperado (HF) | Tamaño observado | SHA-256 esperado (HF LFS) | SHA-256 observado |
| --- | --- | --- | --- | --- | --- | --- |
| train | `freshretailnet-08c1fab7f9257bc73679d415d65d644165d351d4-train.parquet` | 4,500,000 | 106,436,287 | 106,436,287 | `6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d` | `6706832db892bbae4969c19d87e07975d2543d2ba7d7d4756360654785de5a3d` |
| eval | `freshretailnet-08c1fab7f9257bc73679d415d65d644165d351d4-eval.parquet` | 350,000 | 8,440,124 | 8,440,124 | `1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da1095e960e` | `1b118840664280c6b88bffc84c80ee1f54c05d911e354b7599e5da1095e960e` |

Todos los valores esperados y observados se registran en
`data/manifests/freshretailnet-real.json` (comprometido). La verificación se
puede re-ejecutar offline con:

```bash
uv run python -m retail_demand_inventory.data.acquisition \
    --manifest data/manifests/freshretailnet-real.json \
    --output-dir data/raw --mode verify
```

## Hallazgos de esquema (desde los bytes parquet reales)

- `train.parquet` y `eval.parquet` exponen exactamente las 19 columnas
  documentadas en el README fijado, con estos tipos (verificados contra los
  bytes): `city_id int64, store_id int64, management_group_id int64,
  first_category_id int64, second_category_id int64, third_category_id int64,
  product_id int64, dt string, sale_amount double, hours_sale list<double>,
  stock_hour6_22_cnt int32, hours_stock_status list<int64>, discount double,
  holiday_flag int32, activity_flag int32, precpt double, avg_temperature
  double, avg_humidity double, avg_wind_level double`.
- Discrepancia menor: la spec de features Python del README describe
  `hours_stock_status` como `sequence(int32)`, pero los bytes parquet llevan
  `list<int64>`. El loader no consume esa columna; se preserva cruda solo para
  auditoría.
- Ambos archivos tienen cero nulls en las columnas usadas (`store_id`,
  `product_id`, `dt`, `sale_amount`, `first_category_id`,
  `stock_hour6_22_cnt`).
- Las 50,000 claves de tienda-producto aparecen en ambos splits; cada clave tiene
  exactamente 97 filas diarias que cubren `2024-03-28 → 2024-07-02` sin huecos
  internos.
- `sale_amount` es un float continuo no negativo (0.0–49.9 observado), es decir,
  ventas normalizadas, no un conteo entero.
- `stock_hour6_22_cnt` va de 0 a 16 (el README documenta 0–17).

Ver `data/reports/freshretailnet-real-schema.json` para el schema report
determinista sobre la población acotada.

## Checksums crudos vs canónicos

- **Los checksums crudos** son SHA-256 sobre los bytes parquet intactos (arriba).
  Prueban la identidad de bytes con la revisión fijada.
- **El checksum de contenido canónico** es SHA-256 sobre una serialización JSON
  determinista de los registros canónicos (`sku, date, demand_units, category,
  stockout_flag`) de la población acotada:
  `cc7c57e6bd4071e1628e79833869ed7e11d856236c8db5da399fa21955ebd160`.
  Prueba que la tabla canónica cargada es reproducible desde los bytes crudos,
  independiente de cualquier detalle de formato de archivo. La materialización en
  modo real falla si alguno de los dos conjuntos de checksums no coincide.

### Vista general del dataset (de la tarjeta oficial, destacados textuales)

> FreshRetailNet-50K is the first large-scale benchmark for censored demand
> estimation in the fresh retail domain, **incorporating approximately 20%
> organically occurring stockout data**. It comprises 50,000 store-product
> 90-day time series of detailed hourly sales data from 898 stores in 18 major
> cities, encompassing 865 perishable SKUs with meticulous stockout event
> annotations.

## Términos de la licencia (CC BY 4.0) — deed textual y enlace

La licencia es la **Creative Commons Attribution 4.0 International License
(CC BY 4.0)**, disponible en https://creativecommons.org/licenses/by/4.0/legalcode.

El deed oficial en https://creativecommons.org/licenses/by/4.0/ declara,
textualmente:

> **You are free to:**
>
> - **Share** — copy and redistribute the material in any medium or format for
>   any purpose, even commercially.
> - **Adapt** — remix, transform, and build upon the material for any purpose,
>   even commercially.
> - The licensor cannot revoke these freedoms as long as you follow the license
>   terms.
>
> **Under the following terms:**
>
> - **Attribution** — You must give appropriate credit, provide a link to the
>   license, and indicate if changes were made. You may do so in any reasonable
>   manner, but not in any way that suggests the licensor endorses you or your
>   use.
> - **No additional restrictions** — You may not apply legal terms or
>   technological measures that legally restrict others from doing anything the
>   license permits.
>
> **Notices:**
>
> - You do not have to comply with the license for elements of the material in
>   the public domain or where your use is permitted by an applicable exception
>   or limitation.
> - No warranties are given. The license may not give you all of the permissions
>   necessary for your intended use. For example, other rights such as
>   publicity, privacy, or moral rights may limit how you use the material.

El deed lleva el siguiente aviso: "highlights only some of the key features and
terms of the actual license. It is not a license and has no legal value. You
should carefully review all of the terms and conditions of the actual license
before using the licensed material." El código legal es el instrumento
vinculante: https://creativecommons.org/licenses/by/4.0/legalcode.

### Uso permitido

- El uso comercial y no comercial están permitidos (declaración de la tarjeta del
  dataset más las libertades Share/Adapt de CC BY 4.0).
- Se requiere atribución (Sección 3 del código legal).
- El licenciante no otorga garantía; el usuario es responsable de confirmar que
  la licencia encaja con el propósito previsto (tarjeta del dataset, "Intended
  use").

### Atribución / cita

Según la tarjeta del dataset, cite:

```bibtex
@article{2025freshretailnet-50k,
      title={FreshRetailNet-50K: A Stockout-Annotated Censored Demand Dataset for Latent Demand Recovery and Forecasting in Fresh Retail},
      author={Yangyang Wang, Jiawei Gu, Li Long, Xin Li, Li Shen, Zhouyu Fu, Xiangjun Zhou, Xu Jiang},
      year={2025},
      eprint={2505.16319},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2505.16319},
}
```

Cuando se use cualquier dato real de FreshRetailNet (trabajo futuro), el nombre
del dataset, el editor, la versión, la revisión fijada y la licencia deben
registrarse junto a los resultados, y el código de este repositorio debe llevar
el aviso CC BY 4.0 para esos datos. La licencia MIT propia del repo cubre solo el
código original; nunca re-licencia datos de terceros.

## Decisión de redistribución / retención

- **NO comprometer datos de fuente en este repositorio.** `data/raw/` y
  `data/processed/` están gitignored; los archivos parquet crudos adquiridos
  viven bajo `data/raw/` para auditoría y nunca se comprometen ni se empujan.
- El `data/manifests/freshretailnet-real.json` comprometido registra la revisión
  fijada, la fecha de recuperación, los checksums SHA-256 esperados + observados
  a nivel de archivo y la decisión de retención. La distribución del dataset por
  este proyecto está fuera de alcance; los consumidores lo recuperan de la
  revisión fijada oficial.

## Campos de fuente usados y mapeo canónico

El split oficial expone estos campos (nombres textuales de la tarjeta):
`city_id, store_id, management_group_id, first_category_id, second_category_id,
third_category_id, product_id, dt, sale_amount, hours_sale, stock_hour6_22_cnt,
hours_stock_status, discount, holiday_flag, activity_flag, precpt,
avg_temperature, avg_humidity, avg_wind_level`.

| Campo de fuente | Campo canónico | Notas |
| --- | --- | --- |
| `dt` | `date` | Granularidad diaria, cadena de fecha ISO |
| `store_id` + `product_id` | `sku` | Clave canónica `"{store_id}|{product_id}"` (granularidad tienda-producto; serie de 90 días por tienda-producto) |
| `sale_amount` | `demand_units` | Ventas diarias después de la **normalización global** (tarjeta: "Multiplied by a specific coefficient"). **Float continuo no negativo; NO un conteo entero.** |
| `first_category_id` | `category` | Categoría de primer nivel como clave de agrupación gruesa |
| `stock_hour6_22_cnt` | `stockout_flag` | **Derivación directa finalizada**: un día es de stockout sii `stock_hour6_22_cnt > 0` (conteo documentado de horas sin stock en 06:00–22:00); entero validado en 0..17; un valor faltante permanece desconocido (`None`). **Nunca inferido de ventas cero.** |
| `discount`, `holiday_flag`, `activity_flag`, `precpt`, `avg_temperature`, `avg_humidity`, `avg_wind_level` | — (reservado) | Retenidos en la ruta del loader de fuente para trabajo futuro de features; NO forman parte del registro canónico de demanda v1 (los campos opcionales solo se agregan cuando un modelo realmente los usa) |

El split `train`/`eval` distribuido por el editor **no** se usa: este proyecto
re-corta cronológicamente según `docs/evaluation-protocol.md`.

## Reglas de missingness, filtrado, agregación y transformación

- **Granularidad**: tienda-producto × día. No se aplica agregación; las filas ya
  están en la granularidad objetivo. Las claves `(sku, date)` duplicadas son un
  error de validación.
- **Días faltantes**: los huecos internos dentro del tramo de un SKU se rellenan
  con `demand_units = 0.0` y `stockout_flag = None`. Racional: un día faltante es
  ausencia de un registro, no evidencia de un stockout. El relleno mantiene la
  tabla canónica en una cadencia diaria estricta (validada por `DemandTable`).
- **Celdas faltantes** en los campos de fuente usados (`dt`, `store_id`,
  `product_id`, `sale_amount`, `first_category_id`): la fila es un error de
  validación; los loaders lanzan con la fila infractora.
- **Filtros**: ninguno en v1 más allá de descartar filas cuyos campos usados son
  inválidos.
- **Transformación**: `sale_amount` se toma tal cual (ya normalizado); el campo
  canónico se documenta como unidades observadas continuas, no negativas.

## Limitación de censura por stockout

`demand_units` son **ventas observadas**, que están **censuradas** durante las
horas de stockout: cuando el stock se agota, las ventas no pueden subir para
satisfacer la demanda sin restricciones. FreshRetailNet es específicamente un
benchmark de *demanda censurada* (~20% de stockouts orgánicos). Por lo tanto:

- `stockout_flag` se preserva en los datos canónicos, derivado directamente del
  campo documentado `stock_hour6_22_cnt > 0` (nunca de ventas cero). Verificado
  sobre los bytes reales: los días con stockout conservan ventas positivas
  (stockouts de horas parciales), por lo que una regla de ventas cero sería
  incorrecta para estos datos.
- **Los pronósticos apuntan a ventas observadas, no a demanda sin
  restricciones.** No se hace ninguna afirmación de recuperación de demanda
  latente en este prototipo.
- La simulación de políticas trata la demanda como una serie observada exógena;
  los costos de stockout en la simulación se refieren a la política bajo prueba,
  no a la censura en la fuente.

## Política de checksum y manifest

- Cada artefacto de datos que se retiene (fixture, reporte de evaluación
  generado, schema report real) se declara en un manifest comprometido bajo
  `data/manifests/` con checksums SHA256
  (ver `src/retail_demand_inventory/data/manifests.py` y
  `src/retail_demand_inventory/data/real_manifest.py`).
- El manifest de snapshot real (`data/manifests/freshretailnet-real.json`)
  registra: id del dataset, revisión fijada, URLs de fuente, editor, licencia +
  atribución + cita, método de acceso, archivos crudos (tamaños esperados,
  SHA-256 esperado de HF-LFS, tamaños observados, SHA-256 observado),
  versión/regla de canonicalización, SHA-256 de contenido canónico, ruta del
  schema report, versión/regla de derivación de stockout y cinco gates explícitos
  (`source_verified`, `license_verified`, `snapshot_verified`,
  `schema_verified`, `stockout_semantics_verified`). Los cinco gates son true.
- El manifest de población expandida
  (`data/manifests/freshretailnet-real-population-v2.json`) se **genera desde el
  código sobre los bytes crudos verificados** (nunca escrito a mano) y registra
  el id de población, el id/ruta del manifest de fuente, la revisión fijada, los
  checksums por archivo crudo, la regla de selección congelada, los conteos
  candidatos/calificadores/elegibles/seleccionados/excluidos, los conteos de
  tiendas/productos, las filas train/eval, el rango de fechas, la separación
  train/eval, los checksums de las listas de claves seleccionadas/excluidas, el
  SHA-256 de contenido canónico v2, el presupuesto de recursos documentado,
  `seed: null`, `train_metadata_only: true` y el timestamp/revisión de código de
  generación. El modo real con `--population` carga exactamente las claves
  seleccionadas del manifest y falla claramente ante cualquier divergencia de
  fuente.
- **Los checksums observados faltantes FALLAN la verificación en modo real** (sin
  pase silencioso); el comportamiento de checksum opcional existe solo para el
  fixture sintético.
- Los checksums se verifican antes de que cualquier loader consuma el artefacto;
  la materialización en modo real además verifica el checksum de contenido
  canónico.

## Fixture sintético — NO un resultado de fuente auditado

`data/fixtures/freshretailnet_style_synthetic.csv` es una **serie sintética
pequeña y claramente etiquetada** (2 SKUs, ~120 puntos diarios) creada para
desarrollo offline, tests y la demo. Está estilizada según la granularidad de la
fuente auditada (tienda-producto × día, demanda continua normalizada,
`stockout_flag`) pero **no se deriva de, no se muestrea de y no es representativa
de FreshRetailNet-50K**. Ningún número producido a partir de ella es un
resultado del mundo real.

## Población real expandida (v2)

La evaluación acotada v1 cubre las primeras **10 claves de tienda-producto**
(todas de la tienda 0) bajo la regla determinista documentada. Una segunda
población expandida **opt-in** (`freshretailnet-real-population-v2`) amplía la
evaluación determinista a **100 claves** manteniendo el mismo snapshot fijado, la
misma regla de elegibilidad y la misma garantía de sin muestreo. La regla se
congela ANTES de materializar cualquier métrica y se registra textualmente en el
manifest de población y el reporte de perfil.

| Propiedad | Valor |
| --- | --- |
| ID de población | `freshretailnet-real-population-v2` |
| Regla de selección | claves observadas en train cuyos registros combinados train+eval abarcan al menos `REQUIRED_HISTORY_DAYS = 63` días consecutivos Y comparten el tramo de fechas idéntico (tramo modal entre las claves calificadoras); ordenar por `(store_id, product_id)` ascendente; aplicar un tope estructural de diversidad de tiendas de a lo sumo `PER_STORE_CAP_KEYS = 10` claves por tienda; seleccionar las primeras `TARGET_POPULATION_KEYS = 100` claves en total |
| Claves elegibles | 50,000 (cada clave abarca 97 días, 2024-03-28 → 2024-07-02) |
| Claves seleccionadas | 100 claves en **10 tiendas** (tiendas 0–9, 10 cada una) |
| Productos seleccionados | **40 productos distintos** (verificados desde los bytes; no los 865 completos) |
| Claves v1 preservadas | sí — las primeras 10 claves de la tienda 0 son exactamente la selección v1 |
| Filas seleccionadas | 9,700 (train 9,000 / eval 700) de 4,850,000 filas de fuente |
| Razones de exclusión | `beyond_store_cap` 41,053 · `beyond_target` 8,847 (49,900 excluidas) |
| Cobertura | 0,2% de claves y filas |
| Entradas de selección | solo metadatos (presencia de claves + tramos de fechas) — la demanda/los valores de stockout nunca influyen en la selección |
| Seed / muestreo | ninguno (`seed: null`); completamente determinista |
| Artefactos comprometidos | `data/manifests/freshretailnet-real-population-v2.json` (generado), `data/reports/freshretailnet-real-population-profile-v2.json` (perfil de dry-run) |
| Reporte expandido | `data/evaluations/freshretailnet-real-expanded-report.json` (distinto del reporte v1) |

La diferencia v1/v2 es **solo el tamaño y la estructura de la población**: el
snapshot de fuente, la canonicalización, la semántica de stockout, los
checksums, el protocolo, los modelos y las políticas son idénticos. v2 es
estrictamente opt-in (`materialize --source real --population …`); sin él, el
modo real mantiene el comportamiento de 10 claves de v1 y su reporte.

## Limitaciones restantes (snapshot real)

- La evaluación se ejecuta sobre una **población determinista acotada**, no sobre
  el snapshot completo de 50,000 claves: v1 = primeras 10 claves (toda la tienda
  0); v2 (opt-in) = 100 claves en 10 tiendas (tiendas 0–9). Ambas están
  etiquetadas `Deterministic bounded evaluation over pinned snapshot` /
  `Deterministic expanded bounded evaluation over pinned snapshot` y ninguna
  generaliza a otras claves, períodos o minoristas.
- La población expandida cubre 10 de 898 tiendas y 40 de 865 productos; las
  métricas agregadas describen solo las claves seleccionadas.
- `demand_units` son **ventas observadas**; la demanda censurada durante
  stockouts se documenta, no se recupera.
- Los pronósticos usan solo lags, estadísticas móviles y features de calendario;
  las covariables de descuento/festivo/actividad/clima aún no se consumen.
- Los bytes parquet crudos se retienen localmente en el `data/raw/` gitignored
  para auditoría; nunca se comprometen ni se redistribuyen por este proyecto.

## Aceptación

- [x] Dataset candidato listado con URL de fuente, revisión fijada y fecha de
      recuperación (2026-08-11).
- [x] Términos de la licencia (CC BY 4.0) documentados textualmente con enlace al
      código legal, atribución y declaración de uso permitido.
- [x] Propiedades requeridas de la fuente verificadas contra la tarjeta oficial y
      contra los bytes parquet reales (granularidad, señal de demanda, longitud
      de historial, calendario, missingness, versionado).
- [x] Mapeo canónico, reglas de missingness/filtrado/transformación y censura por
      stockout documentados arriba.
- [x] Archivos crudos adquiridos desde la revisión fijada; tamaños exactos y
      SHA-256 crudo observados y registrados (coinciden con los metadatos HF LFS).
- [x] Esquema verificado contra los bytes; schema report comprometido bajo
      `data/reports/freshretailnet-real-schema.json`.
- [x] Derivación de stockout finalizada como `stock_hour6_22_cnt > 0` y
      verificada sobre bytes reales (nunca desde ventas cero).
- [x] SHA-256 de contenido canónico calculado y registrado; distinción de
      checksum crudo-vs-canónico documentada.
- [x] Política de checksum/manifest definida y aplicada para snapshots reales.
- [x] Población expandida (v2): selección determinista de 100 claves congelada
      antes de cualquier métrica, manifest de población generado y perfil de
      dry-run comprometidos, reporte v1 intacto.
- [x] Fixture sintético comprometido bajo `data/fixtures/` y claramente
      etiquetado.

**Estado de aceptación: ACEPTADO con condiciones.** El desarrollo de metodología
sobre el fixture sintético y las **evaluaciones deterministas acotadas sobre el
snapshot real fijado** (v1: 10 de 50,000 claves; v2 opt-in: 100 de 50,000 claves)
están implementadas y son reproducibles. Las evaluaciones reales permanecen
**acotadas** por diseño; no se hace ninguna afirmación full-dataset, de
producción ni de generalización.
