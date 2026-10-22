---
name: metodologia-prp
description: Cárgala cuando el comercial pida un PRP nuevo o una nueva versión. Es el proceso paso a paso desde las comunicaciones del cliente hasta un deck revisable.
---

# Cómo producir un PRP

Las muestras son PRP terminados y no muestran el proceso. Los pasos marcados como **(inferido)** se deducen de cómo se rellenan las variables y de los changelogs de versiones.

## 1. Autonomía, variante y versión
- Pregunta el nivel de autonomía.
- Pregunta la variante de plantilla si no consta: completa, Quick-Start, Migración o Web (ver estructura-prp).
- Si ya existe un PRP del cliente, pregunta si partes de él.
- **Nunca sobrescribas.** La versión nueva es `_v<N+1>` con la fecha del día.
- Añade una fila al control de versiones con el cambio en una línea, igual que en las muestras:
  - «Propuesta V.2 -> incluimos las personalizaciones a medida según archivo Excel compartido por el cliente»;
  - «Propuesta V.4 -> Ajustamos a 20% el pago final a Go-live, según petición del cliente».
- El cambio tiene que salir de las fuentes o de la instrucción del comercial.
- No deduzcas cuál es la versión vigente por el nombre de archivo: Animalsdog tiene dos «v1» distintos.

## 2. Ficha de datos con su fuente (inferido)
| Dato | Dónde se usa |
|---|---|
| Nombre comercial del cliente (uno solo) y marca del canal | Todas las diapositivas, notas, Miscelánea y nombre de archivo |
| Actividad, año, cifras, mercados, competidores | Situación actual |
| Plataforma actual y problemas | Situación actual, Retos |
| Interlocutor del cliente | Situación actual |
| Plataforma nueva y modelo (Open Source, SaaS, Headless, plugin) | Objetivos, Ámbito, Alcance, nombre de archivo |
| Canal B2B/B2C, o web sin tienda | Objetivos, Consultoría, Ámbito, Miscelánea |
| Integraciones con nombre (Middleware, PIM, Hubspot, Tipsa, Odoo…) | Retos, Cómo lo abordamos, Consultoría, Alcance, Miscelánea |
| Requisitos y desarrollos a medida (Excel del cliente, calculadoras, multitienda) | Alcance |
| Exclusiones (p. ej. «No se incluye … la web B2B») | Alcance |
| Nº de referencias, quién carga los datos, nº de URL para SEO | Alcance |
| Fecha objetivo, duración y arranque | Retos, Cronología |
| Plan de soporte, precio y forma de pago | Software, Soporte, Presupuesto |
| Tratamiento (tú/usted) e idioma | Todo el documento |
| Casos de éxito | Casos |
| Autor de la propuesta | Control de versiones |

## 3. Datos internos de TRILOGI: pídelos siempre
Estos datos no salen del cliente:
- duración del proyecto y semanas de arranque (dependen de la carga de producción);
- duración de la consultoría (3 semanas en todas las muestras, sin confirmar que sea fija);
- precio, plan SILVER/GOLD/PLATINUM y porcentajes de pago;
- casos de éxito;
- autor;
- nº de URL de la migración SEO, si el cliente no lo ha dado.

## 4. Una sola lista de faltantes
Envía un único mensaje con tres bloques: «del cliente», «internos de TRILOGI» y «contradicciones (con las dos fuentes)». Riesgos reales que hay que vigilar:
- plataforma distinta entre secciones (Silicium);
- tres nombres para el mismo cliente (Advanced Beauty Supplements / Solandpure / ABS);
- integración dudosa: en FBO, la web de Quartup no ofrece conector pero el cliente dice que sí lo hay. Recógelo como [FALTA: confirmación de conector …] y no como nota interna.

## 5. Traducir necesidades a diapositivas
Una misma necesidad aparece en varias diapositivas:
- **Integrar con X:**
  - Reto: «Integración con sistemas existentes (X)».
  - Cómo lo abordamos: «Conectaremos el eCommerce con X».
  - Consultoría: «integraciones de datos con sistemas externos (X)», tanto en Análisis técnico como en Definición de Datos.
  - Alcance: «Soporte a la integración con X …», con su límite.
  - Miscelánea: testeo de los datos de X.
- **Fecha límite:** Reto «Arrancar el proyecto antes de finalizar enero 2026» o «Tener el proyecto en Go-live …», y Cronología.
- **Plataforma actual cara o limitada:** Situación actual y Retos «Reducir el actual coste de plataforma» y «Migrar a la nueva plataforma lo antes posible».
- **Web sin tienda:** variante Web, con Transportes y Check-out «no aplica».
- **Excel de requerimientos del cliente:** en Alcance, «Basado en el Excel de requerimientos del cliente:», con una viñeta por requisito y lo que incluye o excluye.
- **Cliente que ya conoce la tecnología:** Oportunidad «El cliente ya conoce el entorno Wordpress…».

Los retos y oportunidades genéricos («Mejorar el canal digital», «Estar a la vanguardia del eCommerce», «Tranquilidad técnica») son repertorio comercial. Úsalos solo si encajan con las fuentes. **(inferido)**

## 6. Alcance: incluir y acotar
Cada elemento del Alcance indica qué se incluye y dónde está el límite, siguiendo los patrones de las muestras:
- «Implementación del conector … Cualquier personalización del conector en su funcionamiento estándar no está incluida»;
- «(pendiente de previo análisis técnico de requerimientos)*»;
- «El coste de compra del plugin no está incluido»;
- «se valorará a parte».

No inventes límites técnicos ni añadas funcionalidades que no consten en las fuentes.

## 7. Redactar
- Copia literalmente las diapositivas fijas, incluida toda la Miscelánea.
- Sustituye [CLIENTE] en **todas** las diapositivas y notas. En las muestras han quedado «Italsetas», «Kibucs», «La tienda del Alérgico» y «MARMERAKI».
- Si es una web sin tienda, cambia «eCommerce» por «Web» o «web» donde lo hace Masterfoam.
- La fecha de «contenidos a fecha DD/MM/AA» es la del archivo.

## 8. Precios y plazos
No calcules, no estimes y no copies cifras de otro PRP. El rango de meses lo da el comercial. Las cláusulas contractuales de Miscelánea (garantía, pago, tiempos del PM, transportistas) no se tocan sin una indicación expresa del comercial.

## 9. Revisión antes de entregar
- [ ] No queda «COPIA AQUI», «Otros…», «A CONFIRMAR JOSE!!», ninguna diapositiva vacía ni ninguna nota interna en el cuerpo.
- [ ] Ningún nombre de otro cliente en el cuerpo, las notas ni las tablas.
- [ ] Un solo nombre de cliente, el mismo en todo el deck, Miscelánea incluida.
- [ ] La plataforma coincide en Situación, Cómo lo abordamos, Objetivos, Ámbito, Alcance y nombre de archivo.
- [ ] El canal B2B/B2C es coherente en Objetivos, Consultoría, Ámbito y Alcance.
- [ ] Cada reto concreto tiene su viñeta en Cómo lo abordamos y en Alcance.
- [ ] Los sistemas de Consultoría y de la cláusula de testeo son los del cliente.
- [ ] La Cronología está completa o con [FALTA].
- [ ] El tratamiento es uniforme. Marmeraki mezcla «su» en Transparencia con «tu» en el resto.
- [ ] El control de versiones está actualizado.
- [ ] El número de [FALTA] del cuerpo coincide con la lista final.
