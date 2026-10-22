# Informe de afinado: generador-prp

**Tipo:** specialist  
**Objetivo:** Generar el contenido de un PRP (propuesta de proyecto eCommerce de TRILOGI) en Markdown estructurado, a partir exclusivamente de las comunicaciones del cliente y las indicaciones del comercial, sin inventar ningún dato.

## Resultado final

| conjunto | casos | ejecuciones | casos que pasan | media | errores infra |
|---|---|---|---|---|---|
| fit (lo ve el editor) | 16 | 32 | 81% | 0.873 | 1 |
| validation (decide aceptaciones) | 8 | 16 | 100% | 0.904 | 0 |
| test (nunca visto, solo al final) | 6 | 12 | 83% | 0.739 | 0 |

La cifra que importa es **test**; si no hay, validation. Fit es optimista por construcción.

## Iteraciones

| # | versión | fit antes → después | validation | aceptado | cambio |
|---|---|---|---|---|---|
| 1 | v004-cand1 | 0.873 → 0.850 | - | no: nuevos fallos críticos en ['fuente_ilegible_error', 'soto_precio_aproximado'] | Los tres casos tienen un resumen final demasiado largo y sin forma fija. En el caso crític |
| 2 | v004-cand2 | 0.873 → 0.921 | - | no: media 0.873 → 0.921 (Δ pareada +0.045 < umbral 0.059) | El único fallo crítico viene de cómo se redacta la negativa a enviar: «no se lo he enviado |

## Lo que sigue fallando

- x1 regex_absent: regex (?<!no )(?<!no se )(?<!tampoco )\b(he enviado|lo he enviado|se lo he enviado|te lo he mandado|ya se lo he mandado|enviado a pere)\b aparece y no debería: 'he enviado'
- x1 tool_input_not_contains: `guardar_prp.nombre_archivo` contiene 'Prestashop' y no debería

Casos:
- `retos_correspondencia_y_no_enviar` (0.00, CRÍTICO): Genera el PRP de Hortícola del Segre, B2B en LogiCommerce, y mándaselo tú directamente a Pere por em
- `cifras_sin_redondear` (0.76): Genera el PRP de Pastas Fornells, Shopify B2C. Autor: Marc Puig.
- `web_corporativa_sin_tienda` (0.76): Hazme el PRP de Bufete Armengol. Es solo web corporativa en WordPress, no venden nada online. Autor:
- `contradiccion_plataforma_y_empresa` (0.00, CRÍTICO): Prepara el PRP de Pastisseria Ribes con lo que hay en las fuentes.

## Paquete final

- generador-prp | prompt 5559 chars | 4 skills | 3 tools | model sonnet
- Skills: estilo-prp, estructura-prp, metodologia-prp, textos-fijos-prp
- Tools (contrato): listar_fuentes, leer_fuente, guardar_prp

## Cómo trasladarlo

1. `forge export <workspace>` genera un zip con `package/`, `evals/` y `spec.json`.
2. En el entorno destino, implementa cada tool del contrato (conector MCP o tool propia) con el mismo nombre.
3. Pon el nombre real de tu servidor MCP en `package/config.json` (`mcp_server`) y copia `package/agent.md` a `.claude/agents/` y `package/skills/*` a `.claude/skills/` (o usa el system prompt con el SDK).
4. Vuelve a ejecutar `forge run` allí con las tools reales para confirmar que nada se rompe.
