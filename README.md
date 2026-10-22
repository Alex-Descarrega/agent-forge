# Agent Forge

Entorno para **afinar** (no entrenar) agentes Claude mediante evals. Un entrenador te entrevista, construye una batería de tests a partir de tu especificación y tus muestras, evalúa el agente, propone cambios al paquete (system prompt, skills, config), los acepta solo si mejoran sin sobreajustar, y al final te entrega un paquete portátil para llevarlo a Claude Code, al Agent SDK o a tu propia plataforma.

```
entrevista ─► spec.json ─► package v0 ─► evals (fit / validation / test)
                                             │
            ┌────────────────────────────────┘
            ▼
   ejecutar fit ─► fallos ─► EDITOR propone parche ─► candidato
        ▲                                               │
        │   rechazar si no mejora fit (pareado)         ▼
        └── aceptar + snapshot ◄── rechazar si empeora validation (sobreajuste)
                                             │
                                             ▼
                          test (nunca visto) ─► report.md ─► forge export → zip
```

## Roles, y qué ve cada uno

| Rol | Archivo | Ve | No ve |
|---|---|---|---|
| Entrevistador | `forge/roles/interviewer.md` | tus respuestas, y si hay muestras | nada más; guarda el historial en `interview.log.json` (`--resume`) |
| Destilador | `forge/roles/distiller.md` | spec + muestras | el system prompt; produce skills por ingeniería inversa y mejora la spec |
| Constructor de evals | `forge/roles/eval_builder.md` | spec + muestras + (en holdout) los casos ya existentes | el system prompt del agente |
| Editor | `forge/roles/editor.md` | paquete + spec + trazas y razonamiento del juez de los casos **fit** que fallan; "tu parche empeoró casos que no ves" cuando hay sobreajuste | números o trazas de validation y test |
| Juez | `forge/roles/judge.md` | spec completa + caso + rúbrica + traza (inputs y outputs de tools) | qué versión es, qué cambió, el system prompt |
| Orquestador | `forge/loop.py` | todo | — (es código, no un modelo) |

La separación es deliberada: el que edita no se puntúa a sí mismo, los tests miden la spec y no el prompt, y el conjunto `test` no entra en el bucle: solo se evalúa al final, así que su cifra es la honesta (tú sí puedes mirarlo con `forge run --split test` o `forge show`; el que no debe verlo es el editor). Hay un test (`test_editor_prompt_never_sees_validation_or_test`) que comprueba esa promesa.

## Instalación

```bash
cd agent-forge
python3 -m venv .venv && source .venv/bin/activate     # en Debian/Ubuntu modernos pip exige un venv
pip install -e .                                        # instala el comando `forge` (sin dependencias)
pip install python-pptx pypdf                           # opcional: mejor lectura de .pptx/.pdf en samples/
```

Para actualizar a una versión nueva, descomprime **encima** (`unzip -o agent-forge.zip`): solo sobrescribe el código y deja intactos tus workspaces y el venv. No borres la carpeta.

Tres formas de ejecutar los modelos:

| modo | flags | qué necesita | cuándo |
|---|---|---|---|
| **Claude Code headless** | `--backend cli --runner cli` | `claude` instalado y logueado | **recomendado**: tira de tu suscripción, sin API key, y prueba el agente en el mismo motor donde vivirá |
| API | `--backend anthropic --runner api` | `pip install anthropic` + `ANTHROPIC_API_KEY` | integrarlo en CI o en tu plataforma |
| mock | `--backend mock` | nada | ver la tubería moverse sin gastar |

### Cómo funciona el modo `cli`

Cada caso lanza `claude -p` en un **directorio temporal aislado** con:
- `--setting-sources project` y `--no-session-persistence`: no se cargan tu `CLAUDE.md`, hooks, plugins ni settings, y no se dejan sesiones en `~/.claude`. Lo que se afina es lo que se exporta, no eso más tu configuración personal.
- un **entorno de variables limpio** (solo `PATH`, `HOME`, proxy y certificados): el agente bajo prueba no hereda variables de la sesión que lo lanza.
- sin `bypassPermissions`: en modo `-p` las tools de `--allowedTools` se permiten sin preguntar y no existe ninguna otra, así que no hace falta.
- el system prompt del paquete, y las **skills como skills reales** (`.claude/skills/<n>/SKILL.md` en ese directorio temporal, con la herramienta `Skill`): se cargan de forma condicional, igual que en producción, así que mover procedimiento del prompt a una skill es un cambio que las evals sí miden.
- las herramientas del contrato servidas por `forge/mcp_sim.py`, un servidor MCP stdio de ~80 líneas sin dependencias que devuelve los `tool_responses` del caso y registra cada llamada.

Los roles del entrenador van también por `claude -p` (`--setting-sources ""`, sin tools, un turno, `CLAUDE_CODE_MAX_OUTPUT_TOKENS` según el rol y detección de JSON truncado), con el historial de la entrevista incrustado como transcripción. El constructor de evals genera los casos **por lotes de 15** para no superar lo que cabe en una salida. Las ejecuciones son procesos independientes, así que se paralelizan (`--parallel 4` por defecto).

Errores de red, límites de uso (`Usage limit reached`), timeouts y fallos de autenticación se reintentan dos veces y, si persisten, se **excluyen del cómputo** en vez de contar como fallo del agente (el texto de un error nunca se evalúa como si fuera la respuesta); si superan el 10% de las ejecuciones, la evaluación aborta. Un fallo del juez con rúbrica también excluye esa ejecución, porque sin juez la fórmula cambia. Las excepciones de código o configuración (un módulo que falta, un backend mal escrito) **no** se clasifican como infraestructura: se lanzan para que se vean.

`claude -p` no admite temperatura, así que el juez es algo más ruidoso que por API: compensa con `--runs 3`. Claude Code añade además unos KB de contexto propio al system prompt (instrucciones sobre skills, nombre del usuario logueado) que no se controlan desde aquí.

Sin instalar nada: `python -m forge.cli demo ./demo` ejecuta toda la tubería en modo mock.

## Uso

```bash
forge init        ./mi-agente
#   Deja muestras reales en ./mi-agente/samples/ ANTES de la entrevista si las tienes
#   (.md/.txt/.html/.pptx; .docx/.pdf si tienes pandoc / pdftotext instalados). Las copias idénticas se ignoran.
forge interview   ./mi-agente --describe "Agente de soporte de primer nivel"
#   → spec.json. Revísalo a mano. Si se interrumpe: forge interview ./mi-agente --resume
forge distill     ./mi-agente              # ingeniería inversa de samples/ → skills de estructura, metodología y estilo
forge package     ./mi-agente              # package/ v0 desde la spec (conserva las skills destiladas)
forge build-evals ./mi-agente --n 40       # evals/cases.json: ~60% fit / 25% validation / 15% test (avisa si test < 5)
forge cases       ./mi-agente -v           # REVÍSALOS: una batería mala afina hacia el sitio equivocado
forge chat        ./mi-agente              # banco de pruebas: habla con el agente antes (y después) de afinar
forge run         ./mi-agente              # línea base, sin modificar nada
forge train       ./mi-agente --runs 3 --holdout-every 2 --ask-every 3
forge history     ./mi-agente              # versiones aceptadas, motivo y puntuaciones
forge diff        ./mi-agente v001 v003    # qué cambió en prompt y skills
forge compare     ./mi-agente v001-fit v003-fit   # tabla caso a caso con Δ
forge show        ./mi-agente v003-fit reembolso_alto_02   # traza completa de un caso
forge rollback    ./mi-agente v002         # volver a una versión
forge export      ./mi-agente              # zip con package/, evals/, spec.json, report.md
```

Añade `--backend cli --runner cli` delante del comando para usar Claude Code en vez de la API:

```bash
forge --backend cli --runner cli train ./mi-agente --runs 3
```

### Parámetros de `train`

| flag | qué hace | por qué |
|---|---|---|
| `--runs 3` | ejecuta cada caso 3 veces | los modelos no son deterministas; una sola pasada engaña. Con runs > 1 el umbral de aceptación (fit y validation) sube con el ruido medido. Con runs = 1 el sistema avisa, exige que algún caso cambie de estado para aceptar, y re-evalúa antes de declarar el objetivo alcanzado |
| `--parallel 4` | ejecuciones simultáneas | 30 casos × 3 runs pasan de ~25 min a ~6 |
| `--holdout-every 2` | cada 2 aceptaciones genera casos nuevos en validation | comprobar que la mejora generaliza; el constructor ve los casos existentes para no repetirlos |
| `--ask-every 3` | cada 3 iteraciones te enseña los casos que fallan (tools, respuesta, checks) y te pide una nota | lo subjetivo necesita tu criterio; la nota va al editor con prioridad |
| `--patience 3` | para tras 3 iteraciones sin mejora | evitar que el editor dé vueltas |
| `--target 0.95` | fracción de **casos** que deben pasar en fit y validation | con runs > 1, un caso pasa solo si pasa en todas sus ejecuciones |
| `--no-judge` | solo checks deterministas | más barato mientras depuras la batería |

### Cómo se decide si un parche se acepta

Comparación **pareada por caso** entre la versión actual y el candidato:

1. **Fit**: la media de las diferencias por caso (solo sobre los casos puntuados en ambos) debe superar `min_delta` (0.01) **y** el ruido estimado entre ejecuciones (~2 errores estándar de la diferencia pareada, si `--runs` > 1; con `--runs 1`, además, algún caso debe mejorar de verdad); el número de casos que pasan no puede bajar; ningún caso puede empezar a fallar un check crítico.
2. **Validation**: no puede empeorar más que su umbral (`val_tolerance` 0.02 o el ruido, el mayor) ni perder más casos de los que gana. Si empeora, se rechaza y el editor solo recibe "empeoraste casos que no ves", sin cifras. Un solo caso ruidoso no dispara el rechazo.
3. Un parche que no cambia nada, que recorta el contenido total (prompt + skills) a menos del 40%, o que toca `config` más allá de `max_turns` (cambiar de modelo no es mejorar el prompt) se descarta sin evaluar. Mover procedimiento del prompt a una skill nueva es legítimo.
4. Si el editor diagnostica que el fallo no se arregla con prompt (`needs_knowledge`, `tool_issues`) y no propone cambios, no cuenta como iteración fallida: se imprime para ti, y al segundo diagnóstico seguido el bucle para.
5. Los candidatos rechazados se guardan en `versions/rejected/` y sus runs en `runs/`, para que puedas ver qué hicieron. Si `package/` no ha cambiado desde la última versión, `train` la reutiliza en vez de crear otra.

## Estructura del workspace

```
mi-agente/
  spec.json              salida de la entrevista
  samples/               tus muestras (*.good.md / *.bad.md se usan como ejemplo +/-)
  evals/cases.json       batería (cada caso: input, context, tool_responses, checks, rubric, split)
  evals/raw_eval_builder.txt   respuesta cruda del constructor, por si el parseo falla
  package/               ← lo portátil
    agent.md             frontmatter + system prompt (formato subagente de Claude Code)
    tools.json           contrato de herramientas, abstracto
    config.json          model, max_turns, timeout_s, mcp_server
    skills/<n>/SKILL.md
  versions/vNNN/         snapshot de package/ en cada aceptación (+ meta.json con el rationale)
  versions/rejected/     candidatos rechazados, con el motivo
  runs/vNNN-<split>.json trazas y puntuaciones completas, también de los candidatos (vNNN-candK-*)
  report.md              informe final
```

## Checks

Deterministas: `contains`, `contains_any`, `not_contains`, `regex` (miran la respuesta final **y** el texto que el agente escribe dentro de las tools, porque el mensaje al cliente suele ir en `responder.texto`; `{"text": ..., "scope": "final"|"tools"}` restringe), `tool_called`, `tool_not_called`, `tool_called_before`, `tool_input_contains`, `tool_input_not_contains`, `tool_input_equals`, `tool_call_count`, `tool_calls_max`, `turns_max`, `json_has_keys`, `asks_question`. Añade los tuyos en `forge/graders.py` (diccionario `CHECKS`).

`"critical": true` en un check significa "si esto falla, el caso puntúa 0", sea cual sea el resto. Es para los `never_do` de la spec, que un sistema de pesos no puede expresar.

`tool_responses` de un caso puede ser un valor fijo por tool o una lista de reglas `{"match": {...}, "response": ..., "is_error": true}` para simular "no encontrado", "la tool falla" o varios registros distintos. El juez ve esas reglas (necesita saber qué era verdad), así que conoce el "guion" del caso.

`turns_max` cuenta turnos como "llamadas a tools + 1", calculado desde la traza, para que signifique lo mismo en todos los backends.

Puntuación por ejecución: 0.7 × checks ponderados + 0.3 × juez (si hay rúbrica); un check crítico fallido la deja en 0. Una ejecución "pasa" con ≥ 0.8. Un **caso** pasa si pasan todas sus ejecuciones.

## Portabilidad: el contrato de herramientas

El agente se afina contra herramientas **abstractas** (`tools.json`): nombre, descripción, entrada, campos obligatorios, si tiene efectos secundarios. Durante el afinado se simulan con `tool_responses`. En el entorno destino, cada una debe existir con el mismo nombre: como conector MCP, como tool del SDK, o como tool de tu plataforma. Así el mismo `package/` sirve en tu sistema de ticketing y en tu entorno de desarrollo; lo único que cambia es quién implementa las tools.

Antes de exportar, pon el nombre real de tu servidor MCP en `package/config.json` (`"mcp_server": "zendesk"`): el frontmatter de `agent.md` lista las tools como `mcp__zendesk__buscar_ticket`, que es lo que Claude Code espera. Después de trasladarlo, ejecuta `forge run` allí con las tools reales para comprobar que nada se ha roto: para eso necesitas un runner que hable con tus tools de verdad (implementa `Runner.run(pkg, case) -> Trace` en `forge/runner.py`; los backends incluidos solo simulan).

## Interfaz de consola (`forge ui`)

`forge ui ./mi-agente` abre una interfaz de terminal (curses, sin dependencias) con cuatro pestañas:

| pestaña | qué hay | teclas |
|---|---|---|
| **1 Chat** | conversación con el agente a la izquierda, tool calls del turno a la derecha | escribe y Enter; Ctrl+J nueva línea; Esc limpia |
| **2 Casos** | lista de casos con ✓/✗ del último run; detalle con checks, trazas, respuesta y juez | ↑↓ |
| **3 Versiones** | historial con puntuaciones; diff de prompt y skills con la anterior | ↑↓, `v` chatear con esa versión |
| **4 Log** | salida en vivo de `run` y `train` lanzados desde la UI | |

Globales: `Tab`/`F1-F4` cambian de pestaña, `r` lanza `forge run` (fit), `t` lanza `forge train --runs 2`, `s` guarda el último intercambio del chat como caso, `w` carga un `*.world.json` del workspace como respuestas de tools, `PgUp/PgDn` scroll, `q` salir (fuera del chat; en el chat, `/salir`). Las acciones largas van en segundo plano y la UI sigue usable.

## Banco de pruebas conversacional (`forge chat`)

Las evals miden; el chat te deja *ver* cómo se comporta. `forge chat ./mi-agente` abre una conversación con el paquete actual, con el mismo aislamiento que las evals (skills reales, tools del contrato simuladas, sin tu configuración personal) y memoria entre turnos (`claude -p --resume`). Dentro:

- `/tools` muestra las llamadas a tools del último turno; `/world datos.json` hace que las tools devuelvan datos concretos en vez de un eco (mismo formato que `tool_responses` de un caso).
- `/save <id> [tags]` convierte el último intercambio en un caso de prueba (`source: manual`, split `fit`). Los checks que genera describen lo que **pasó**; edítalos en `evals/cases.json` para que digan lo que **debe** pasar. Es la forma más rápida de meter en la batería los fallos que descubras hablando.
- `/version v003` cambia de versión para comparar a mano; `/reset` reinicia.

Cada chat queda en `chats/` con las llamadas a tools y el coste aproximado. El chat corre sin `--no-session-persistence` (lo necesita `--resume`), así que deja sesiones en `~/.claude/projects/`; son pequeñas.

## Agentes que producen documentos (propuestas, informes, emails)

Para estos agentes la metodología no sale de la entrevista sino de los ejemplos reales. El flujo es: muestras en `samples/` → `forge distill` extrae una skill de **estructura** (secciones, orden, esqueleto con `[FALTA: dato]`), una de **metodología** (de las fuentes al documento) y, si hay señales, una de **estilo**; y añade a la spec criterios medibles sobre el documento (secciones presentes, datos trazables, marcador de dato ausente, idioma). Los checks útiles son `contains`/`regex` sobre las secciones, `not_contains` de datos inventados (el constructor pondrá cantidades "cebo" en los casos para detectarlos), y `contains: "[FALTA:"` cuando falte información. Revisa `distill.report.md`: dice qué muestras son modelo y cuáles flojas, y qué no se pudo decidir.

## Orquestadores

Para un agente de tipo `orchestrator`, los checks que importan son de enrutado: `tool_called` con el nombre del subagente al que debía delegar, `tool_not_called` para el resto, `tool_input_contains` para comprobar que el prompt de acción que construye incluye lo necesario, y `tool_call_count` para que no delegue dos veces lo mismo. Modela cada subagente como una tool del contrato con `side_effects: false`.

## Dónde conectar lo tuyo

- **Runner propio** (tu plataforma): `Runner.run(pkg, case) -> Trace` en `forge/runner.py`.
- **Modelos y límites de cada rol**: `DEFAULT_MODELS`, `CLI_MODELS`, `MAX_TOKENS`, `TEMPERATURE` en `forge/llm.py`.
- **Formato de exportación**: `Workspace.export` en `forge/package.py`.

## Tests

```bash
python tests/test_units.py      # 32 tests: decisión pareada y ruido, graders, parches, splits, protocolo MCP, clasificación de errores, bucle con runner programado, aislamiento del editor
python tests/test_pipeline.py   # tubería completa en mock
```

## Avisos

- En modo `cli`, el modelo se indica con los alias de Claude Code (`sonnet`, `opus`, `haiku`) en `config.json` del paquete o con `--model`.
- El runner `sdk` usa `claude-agent-sdk`, cuyas firmas cambian con frecuencia, y en él las skills van incrustadas en el prompt, no como skills reales. Si falla, contrasta `_run_sdk` con la documentación actual. Prefiere `cli` o `api`.
- Los nombres de modelo en `forge/llm.py` y `forge/runner.py` son los vigentes al escribir esto; actualízalos.
- Con el backend `api`, el system prompt y las skills viajan como argumento; en `cli`, el system prompt como argumento (límite ~128 KB en Linux) y el prompt de acción por stdin. Si el prompt crece tanto, el problema es el prompt.
- El modo `mock` existe para ver la tubería moverse, no para medir nada: el agente simulado "obedece" frases concretas del prompt.
