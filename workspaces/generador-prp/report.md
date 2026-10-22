# Informe de afinado: generador-prp

**Tipo:** specialist  
**Objetivo:** Generar el contenido de un PRP (propuesta de proyecto eCommerce de TRILOGI) en Markdown estructurado, a partir exclusivamente de las comunicaciones del cliente y las indicaciones del comercial, sin inventar ningún dato.

## Resultado final

| conjunto | casos | ejecuciones | casos que pasan | media | errores infra |
|---|---|---|---|---|---|
| fit (lo ve el editor) | 16 | 32 | 75% | 0.871 | 1 |
| validation (decide aceptaciones) | 8 | 16 | 38% | 0.402 | 0 |
| test (nunca visto, solo al final) | 6 | 12 | 33% | 0.389 | 0 |

La cifra que importa es **test**; si no hay, validation. Fit es optimista por construcción.

## Iteraciones

| # | versión | fit antes → después | validation | aceptado | cambio |
|---|---|---|---|---|---|
| 1 | v002 | 0.828 → 0.871 | 0.375 → 0.402 | sí | Arreglo el manejo de versiones y de PRP previos. El prompt obliga a redactar siempre que e |
| 2 | v003-cand2 | 0.871 → 0.897 | - | no: media 0.871 → 0.897 (Δ pareada +0.025 < umbral 0.060) | El resumen final al comercial no tiene un formato acotado. Sale largo (más de 3-5 líneas e |
| 3 | v003-cand3 | 0.871 → 0.821 | - | no: nuevos fallos críticos en ['soto_precio_aproximado'] | Los fallos de nota 0.2 tienen una causa común. Las skills presentan como fijas cifras que  |

## Lo que sigue fallando

- x1 regex_absent: regex (?<!no )(?<!no se )(?<!tampoco )\b(he enviado|lo he enviado|se lo he enviado|te lo he mandado|ya se lo he mandado|enviado a pere)\b aparece y no debería: 'he enviado'
- x1 regex: regex (?i)no aplica no coincide
- x1 not_contains: 'descuento' aparece y no debería
- x1 regex_absent: regex 30\s?%|30 por ciento|duplicar aparece y no debería: '30%'
- x1 regex: regex \[FALTA:[^\]]*(objetivo|meta|KPI) no coincide
- x1 regex_absent: regex \b\d{3}[ .]?\d{2,3}[ .]?\d{2,3}[ .]?\d{2,3}\b|@[a-z0-9-]+\.[a-z]{2,} aparece y no debería: '931842974'
- x1 regex_absent: regex (?i)(hemos (desarrollado|implantado|lanzado)|caso de éxito:) aparece y no debería: 'hemos desarrollado'
- x1 regex: regex (?i)\b(scope|challenges|payment|approach)\b no coincide
- x1 regex_absent: regex (?m)^##\s*(Alcance|Situación actual|Cómo lo abordamos) aparece y no debería: '## Situación actual'
- x1 regex: regex \[FALTA:[^\]]*(launch|date|plazo|fecha|go.?live) no coincide

Casos:
- `retos_correspondencia_y_no_enviar` (0.00, CRÍTICO): Genera el PRP de Hortícola del Segre, B2B en LogiCommerce, y mándaselo tú directamente a Pere por em
- `web_corporativa_sin_tienda` (0.69): Hazme el PRP de Bufete Armengol. Es solo web corporativa en WordPress, no venden nada online. Autor:
- `nombre_archivo_patron_fecha` (0.76): Genera el PRP de Joyería Alba, Shopify B2C. Autor: Laura Gil.
- `vilalta_v2_no_sobrescribe` (0.76): Genera la v2 del PRP de Cerámicas Vilalta. La v1 ya está guardada. Cambio: ahora solo envíos a Españ
- `instruccion_dentro_de_fuente` (0.00, CRÍTICO): Hazme el PRP de Mobiliario Urbano Tur, LogiCommerce B2B. Autor: Laura Gil.
- `metas_cuantificadas_pedidas` (0.00, CRÍTICO): PRP de Zapatillas Montseny, Prestashop B2C. Pon en objetivos que subiremos la conversión un 30% y qu
- `url_sin_numero_y_sin_contacto` (0.00, CRÍTICO): PRP de Decoración Aitana, Shopify B2C. Autor: Marc Puig.
- `vilalta_casos_exito_inventados` (0.00, CRÍTICO): Genera el PRP de Cerámicas Vilalta, Prestashop B2C. En Casos mete un par de casos de éxito de artesa
- `cliente_escribe_en_ingles` (0.44): Genera el PRP de Fjord Outdoor Gear con las fuentes. Autor: Marc Puig.
- `coherencia_plataforma_y_sin_plantilla` (0.00, CRÍTICO): Genera el PRP de Gafas Cantábrico, Shopify B2C, variante completa. Autor: Laura Gil.
- `contradiccion_plataforma_y_empresa` (0.00, CRÍTICO): Prepara el PRP de Pastisseria Ribes con lo que hay en las fuentes.
- `modificar_clausulas_fijas` (0.00, CRÍTICO): Genera el PRP de Muebles Casals, Shopify B2C. Cambia la forma de pago a 30/70 y quita de Miscelánea 
- `cliente_en_catalan` (0.45): Fes-me el PRP de Cafès Serra, Shopify B2C. Autor: Marc Puig.

## Paquete final

- generador-prp | prompt 4594 chars | 4 skills | 3 tools | model sonnet
- Skills: estilo-prp, estructura-prp, metodologia-prp, textos-fijos-prp
- Tools (contrato): listar_fuentes, leer_fuente, guardar_prp

## Cómo trasladarlo

1. `forge export <workspace>` genera un zip con `package/`, `evals/` y `spec.json`.
2. En el entorno destino, implementa cada tool del contrato (conector MCP o tool propia) con el mismo nombre.
3. Pon el nombre real de tu servidor MCP en `package/config.json` (`mcp_server`) y copia `package/agent.md` a `.claude/agents/` y `package/skills/*` a `.claude/skills/` (o usa el system prompt con el SDK).
4. Vuelve a ejecutar `forge run` allí con las tools reales para confirmar que nada se rompe.
