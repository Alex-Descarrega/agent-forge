---
name: estructura-prp
description: Cárgala al montar o revisar un PRP de TRILOGI. Indica qué plantilla elegir, el orden de las diapositivas y qué texto es fijo o variable, incluidas las tablas de Software, Soporte y Presupuesto. Trae el esqueleto con marcadores [FALTA].
---

# Estructura del PRP de TRILOGI

El PRP es un **PPTX sobre plantilla corporativa** que se exporta a PDF. Ocupa entre 55 y 65 páginas, y más del 70 % del texto es fijo. Rellena solo las variables a partir de las fuentes y no reescribas el texto fijo.

## Nombre de archivo
`DDMMAA_TRILOGI Propuesta Proyecto eCommerce <Plataforma>_<Cliente>_v<N>`.
- La fecha va en formato DDMMAA. Está confirmado con Masterfoam: el archivo es `041125` y el Alcance dice «contenidos a fecha 04/11/25».
- Variantes reales del nombre: «Propuesta Proyecto Web Wordpress_Masterfoam», «Propuesta Migración eCommerce Prestashop Alonsonavidad».
- Usa `_` entre plataforma y cliente salvo que el comercial indique otra cosa.

## 1. Elige la plantilla
| Variante | Muestras | Índice |
|---|---|---|
| Completa (por defecto) | casi todas | .01 Cronología · .02 El Método · .03 Consultoría · .04 Proyecto · .05 Software · .06 Soporte · .07 Presupuesto · .08 Miscelánea |
| Quick-Start LogiCommerce / Migración sin consultoría | Vapvapor, e-guasch, Sombikers, Alonsonavidad | la completa sin .03 Consultoría, con la numeración corrida |
| Migración LogiCommerce Beyond | Barovari | .01 Cronología · .02 Proyecto · .03 Equipo · .04 Diseño · .05 Software · .06 Soporte · .07 Miscelánea |
| Web corporativa | Masterfoam | la completa, cambiando «eCommerce» por «Web» |

- No uses como modelo Missglinter (plantilla de 2024), TOMBLACK ni «LogiCommerce Propuesta BUSINESS».
- Si no consta qué variante usar, pregunta al comercial.
- En la diapositiva del índice, «.08 Miscelánea» aparece antes que «.07 Presupuesto». Así viene en la plantilla: no lo toques.

## 2. Orden de la variante completa
Leyenda: FIJA = texto literal, solo sustituyes [CLIENTE]; SEMIFIJA = texto con huecos; VARIABLE = se redacta a partir de las fuentes.

1. **Portada** (FIJA).
2. **Transparencia** (FIJA). Cuatro viñetas; solo cambias «según necesidades de [CLIENTE]».
3. **Situación actual** (opcional, de 250 a 450 palabras). Orden: quién es el cliente → situación digital → contacto y qué busca → cierre fijo («Esta propuesta detallará el alcance…»).
4. **Retos y Oportunidades**: entre 5 y 10 retos y entre 4 y 9 oportunidades.
5. **Cómo lo abordamos**: entre 4 y 7 viñetas.
6. **Casos** (opcional). Solo los que aporte el comercial; si no hay, pon [FALTA].
7. **Objetivos** (SEMIFIJA). Variables: tipo de creación, plataforma, canal (B2C/B2B) y público.
8. **Índice** (FIJA).
9. **.01 Cronología**: Consultoría **3 semanas** · Proyecto **[N - M meses]** · arranque «entre [N] y [M] semanas». Coletilla opcional con `*` sobre las cargas de trabajo.
10. **.02 El Método TRILOGI** (FIJA).
11. **.03 Consultoría**, 2 diapositivas (SEMIFIJA). Ajusta el canal y los sistemas externos (ERP/CRM/PIM/LMS). Quita los sistemas y la parte de POS que no apliquen.
12. **.04 Ámbito**: 7 viñetas. Variables: partes implicadas (por ejemplo «Italseta / trilogi / Axalpha»), nivel de marca y «formación de todos los módulos/apps que incluye [Plataforma]».
13. **.04 Alcance**, de 2 a 8 diapositivas:
    - General.
    - Carga y migración de datos.
    - Migración SEO.
    - «Alcance – [Plataforma]»: tablas `Descripción | Implementación y configuración` con valores como «Incluido», «1 moneda» o «Hasta 3».
    - Marketing Digital Cookieless (3 diapositivas FIJAS).
    - Lawwwing.
    - Set-up Modo Consentimiento de Google (v2).
14. **.04 Formación** (FIJA, 4 horas en remoto).
15. **.04 Customer-Driven Design**, unas 10 diapositivas FIJAS con [CLIENTE].
16. **Diseño gráfico** (VARIABLE). Puede ser template premium o diseño modular. Varían el número de páginas de contenido, el límite de revisiones (2 o 3) y si la compra del template está incluida.
17. **.04 Equipo** (FIJA): organigrama, Funciones del PM (dentro y fuera de su ámbito) y Seguimiento de Dirección Estratégica.

### .05 Software (SEMIFIJA, 1-2 diapositivas según la plataforma)
- **Shopify**:
  - Diapositiva 1: «Somos una agencia experta en la instalación, desarrollo y mantenimiento de Shopify.», la descripción, la URL y «Confía en un partner Shopify para el soporte y mantenimiento».
  - Diapositiva 2, titulada «.06 Costes Shopify»: los costes de la plataforma y de Shopify Payments los factura Shopify directamente a **[CLIENTE]**; las apps se contratan en la App Store y no entran en la propuesta.
- **PrestaShop**:
  - Diapositiva 1: «Somos agencia PrestaShop Partner Expert ***…», la URL y «Confía en un partner PrestaShop…».
  - Diapositiva 2: «La contratación del hosting es responsabilidad del cliente. [CLIENTE] deberá contratar…», más la mención a PrestaShop Hosting.
- **LogiCommerce**:
  - Diapositiva 1: «LogiCommerce es la plataforma de comercio electrónico Headless…».
  - Diapositiva 2: «Expertos en LogiCommerce» (PARTNERSHIPS y CERTIFICACIONES).
  - En este texto, «cliente» es una palabra genérica y **no** se sustituye por el nombre del cliente.

### .06 Soporte (6 diapositivas; FIJA salvo lo indicado)
1. **Introducción** con texto fijo: «Estamos a tu lado desde el lanzamiento…». Incluye:
   - horario de lunes a viernes de 8.00 h a 17.00 h (horario peninsular), excepto festivos nacionales y de Cataluña;
   - 2 viñetas de mantenimiento de primer nivel;
   - 7 servicios que se cubren con T-Points.
2. **«Planes de Servicio de Mantenimiento [SaaS | Open Source] – Opcional -»**.
   - Usa SaaS para Shopify y LogiCommerce, y Open Source para PrestaShop.
   - Tabla:

| | SILVER | GOLD | PLATINUM |
|---|---|---|---|
| Tipología eCommerce | B2C o B2B | B2C y/o B2B | B2C y/o B2B |
| Soporte L-V 8 a 17h (CET) | Incluido | Incluido | Incluido |
| Monitorización uptime 24x7 (criticidad «Muy Alta») | Incluido | Incluido | Incluido |
| Gestión de Tickets (acceso 24x7 herramienta ticketing) | Ilimitado | Ilimitado | Ilimitado |
| Soporte telefónico L-V 8 a 17h (CET) | - | Incluido | Incluido |
| Tickets de soporte / consultas | 4 | 6 | 10 |
| Descuentos en Packs T-Points (no acumulables) | - | 5% | 10% |
| (precio) | 90 € mensual | 150 € mensual | 250 € mensual |

   - Variaciones vistas en las muestras:
     - Virtagora (B2C/B2B) muestra solo GOLD y PLATINUM, sin «– Opcional -».
     - LogiCommerce rotula la fila de tickets ilimitados como «Tickets de gestión de Incidencia (diagnóstico)» y la coloca tras la de soporte telefónico.
3. **Nivel de Servicio: definiciones de criticidad**: Muy alta, Alta, Media y Baja, con sus ejemplos (FIJA).
4. **Nivel de Servicio: tabla SLA**. Columnas: `Tipología incidencia por criticidad | Tiempo máximo de primera respuesta | % en plazo | Tiempo máximo de primera acción | % en plazo`.

| Criticidad | Primera respuesta | % en plazo | Primera acción | % en plazo |
|---|---|---|---|---|
| Muy alta (naturales) | 1 hora | >=90% | 4 horas | >=90% |
| Alta (laborables) | 4 horas | >=80% | 12 horas | >=80% |
| Media (laborables) | 16 horas | >=80% | 36 horas | >=80% |
| Baja (laborables) | 24 horas | >=80% | 72 horas | >=80% |
| Consulta | 24 horas | >=80% | | |

   - En LogiCommerce, «primera acción» se llama «diagnóstico» y esta diapositiva va antes que la de definiciones.
5. **«Packs T-Points [SaaS | Open Source]»**. Cinco bloques: Mantenimiento Técnico, Diseño gráfico, Gestión de Contenidos, SEO y Marketing Digital, Formación y Consultoría.
   - En Open Source y Shopify, Mantenimiento Técnico tiene 7 puntos, entre ellos «últimas versiones de [Plataforma]».
   - En LogiCommerce solo tiene Integración con terceros y Velocidad de carga.
6. **Packs T-Points (precios)**. Tabla `T-Points | Importe`:
   - Pack 5* 410 €, 10* 780 €, 25 1850 €, 50 3500 €, 100 6700 €, 250 16000 €;
   - nota: «* Solo disponible a partir de la compra del segundo pack.»;
   - Ekron (LogiCommerce) usa otra tabla: de 10 a 250, más Pack 500 a 31000 €, sin asterisco.

Después vienen dos separadores fijos: **«turn visitors into customers»** y **«Presupuesto»**, con el texto «trilogi llevará a cabo el siguiente proyecto y los servicios teniendo en cuenta las siguientes diapositivas.».

### .07 Presupuesto – Proyecto eCommerce (1 diapositiva)
Tabla `Descripción | Proyecto | Soporte y Mantenimiento (mensual)`, con las filas en este orden:
1. «Consultoría Ámbito y Alcance del Proyecto eCommerce ([10|25] T-points)». El importe es el del pack: 10 → 780 €, 25 → 1850 €. Columna mensual: «-».
2. «Desarrollo proyecto según alcance [definido | comercial] [+ Redirecciones 301 hasta N urls] [+ formación]». Importe: [FALTA]. Columna mensual: «A concretar» o «A valorar».
3. Integraciones, si las hay. Ejemplos: «Implementación de conector a cargo de Axalpha…», con «- €» en Proyecto y «282 € (Axalpha)» en la mensual; «Soporte a la integración LMS… (25 T-Points)», con 1850 €.
4. «Pack Marketing Digital Cookiesless»: **1235 €**. Así, con la errata, en todas las muestras.
5. «Lawwwing & Set-up Modo Consentimiento de Google (v2)»: **345 €**.
6. Desarrollos a medida, si los hay. Ejemplo: «Webservice de consulta de facturas, albaranes y pedidos…» (3600 € o 1900 €).
7. Opcional: «Paquete de 25 T-Points para creatividades / diseños», 1850 €.
8. «Paquete de [5|10|50] T-Points para pequeños ajustes o desarrollos no contemplados»: «(Incluido)».
9. Opcional: «Descuento comercial directo», en negativo (por ejemplo «- 1000 €»).
10. **«Total Proyecto»**: la suma exacta de la columna; la columna mensual dice «A concretar».

Debajo, en dos columnas:
- **Forma de pago (FIJA)**:
  - 40% a la aceptación;
  - 25% a 60 días;
  - 20% a 90 días;
  - 10% a 120 días;
  - 5% a 150 días de la aceptación o Go-Live (lo que suceda antes).
  - «Proyecto: mediante transferencia bancaria. Vencimiento a 5 días desde emisión factura. Mantenimiento: Domiciliación bancaria. Vencimiento a día 5 de cada mes.»
- **Condiciones**:
  - «La estimación de dedicación… es de [N] horas.» Valores vistos: 150, 325 y 444.
  - Arranque «entre 1 y 3 semanas des del primer pago».
  - «Propuesta válida hasta [1 mes | 2 meses] después de su presentación.»
  - «Todos los precios mostrados en esta propuesta son sin IVA.» Esta frase es obligatoria. El IVA no se calcula en ningún sitio.

### .07 Presupuesto eMarketing (opcional, 2 diapositivas)
1. **«Inversión online»**. Tabla `Descripción | Primer mes | Servicio continuo (mensual)`:
   - «Servicios de marketing (SEO, SEM, RRSS, … ) (20 horas/mes)»: [1350 | 1600] € el primer mes y 1350 € mensual.
   - Opcional: «Servicios SOLO de Paid Media»: 1600 € el primer mes. La cuota mensual va por tramos de inversión: 0-20.000 € → 1400 €; 20.001-50.000 € → 7%; 50.001-100.000 € → 6%; +100.000 € → 5%.
   - Pie: domiciliación a día 5, servicio mínimo de 6 meses, y desarrollos, diseño y creatividades por T-Points.
2. **Tareas incluidas en Paid Media** (FIJA, 17 viñetas).

### Cierre
- **.08 Miscelánea** (4 diapositivas, cláusulas FIJAS con [CLIENTE]).
- **Servicios** (FIJA).
- **Control de cambios**. Tabla `Descripción | Autor | Versión`:
  - la v1 lleva «Presentación propuesta | [autor/es] | 1.0»;
  - cada versión nueva añade «Propuesta VN: [cambio y su efecto en el precio]» | autor | N.0. Ejemplo: «aplicamos un descuento directo de 1000€… coste final de 7520€».
- **Contraportada** (FIJA).

## Esqueleto de las partes variables
```
SITUACIÓN ACTUAL / RETOS / CÓMO LO ABORDAMOS: [FALTA: datos del cliente]
CRONOLOGÍA: Proyecto [FALTA: N - M meses]; arranque [FALTA: N] y [FALTA: M] semanas
ALCANCE: integraciones [FALTA]; módulos [FALTA: tabla]; URL 301 [FALTA]
DISEÑO: [FALTA: template premium | modular; nº páginas]
SOFTWARE: bloque [Shopify | PrestaShop | LogiCommerce]
SOPORTE: planes [SaaS | Open Source]; ¿SILVER? [FALTA]
PRESUPUESTO:
  Consultoría ([FALTA: 10|25] T-points) | [importe del pack] | -
  Desarrollo proyecto según alcance … | [FALTA: €] | A concretar
  [FALTA: integraciones / desarrollos a medida con importe]
  Pack Marketing Digital Cookiesless | 1235 € | -
  Lawwwing & Set-up Modo Consentimiento de Google (v2) | 345 € | -
  Paquete de [FALTA: N] T-Points … | (Incluido) | -
  Total Proyecto | [suma] | A concretar
  Dedicación [FALTA: horas]; validez [FALTA: 1|2 meses]; sin IVA
EMARKETING: ¿incluir? [FALTA]; ¿fila Paid Media? [FALTA]
CONTROL DE CAMBIOS: Presentación propuesta | [FALTA: autor] | 1.0
LISTA DE HUECOS: (todos los [FALTA])
```
