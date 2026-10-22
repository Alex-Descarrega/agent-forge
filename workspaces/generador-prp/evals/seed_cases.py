"""Casos semilla del generador de PRP, escritos a mano. `python evals/seed_cases.py` los escribe en cases.json.

Cada caso es un cliente ficticio con fuentes sintéticas (emails, notas) y huecos deliberados.
Los checks deterministas comprueban lo que DEBE pasar; los críticos son los never_do de la spec.
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from forge.schemas import TestCase, Check  # noqa: E402

HERE = Path(__file__).parent


def fuentes(*items):
    """items: (nombre, fecha, texto). Devuelve tool_responses para listar_fuentes y leer_fuente."""
    return {
        "listar_fuentes": [{"nombre": n, "fecha": f} for n, f, _ in items],
        "leer_fuente": [{"match": {"nombre": n}, "response": {"nombre": n, "fecha": f, "texto": t}} for n, f, t in items]
                       + [{"match": {}, "response": {"error": "fuente no encontrada"}, "is_error": True}],
        "guardar_prp": {"ok": True, "ruta": "/prp/guardado.md"},
    }


def c_saved(): return Check("tool_called", "guardar_prp", 2.0, False, "con datos suficientes, guarda el PRP")
def c_not_saved(): return Check("tool_not_called", "guardar_prp", 1.0, True, "sin datos imprescindibles NO se genera")
def c_reads_all(n): return Check("tool_call_count", {"tool": "leer_fuente", "min": n}, 1.0, False, f"lee las {n} fuentes")
def c_order(): return Check("tool_called_before", ["listar_fuentes", "leer_fuente"], 0.5, False, "lista antes de leer")
def c_section(name, w=1.0): return Check("regex", {"text": rf"(?m)^##\s*{name}", "scope": "tools"}, w, False, f"sección {name} presente en el PRP")
def c_falta(what, critical=True): return Check("contains", {"text": f"[FALTA: {what}", "scope": "tools"}, 2.0, critical, f"marca [FALTA: {what}]")
def c_no(text, why): return Check("not_contains", text, 2.0, True, why)
def c_huecos(): return Check("regex", {"text": r"(?m)^##\s*(Lista de )?Huecos", "scope": "tools"}, 1.0, False, "sección ## Huecos al final")
def c_filename(pat): return Check("tool_input_contains", {"tool": "guardar_prp", "field": "nombre_archivo", "value": pat}, 1.0, False, f"nombre de archivo contiene '{pat}'")


SECCIONES_BASE = ["Situación actual", "Retos", "Cómo lo abordamos", "Objetivos", r"\.01", r"\.04", r"\.07", r"\.08"]

cases = []

# 1. Caso completo y limpio: debe generar
cases.append(TestCase(
    id="vilalta_completo", tags=["generate", "prestashop", "b2c"], source="manual",
    input="Genera el PRP para Cerámicas Vilalta. Tienes sus emails y la nota de la reunión del martes. Variante completa, autor Marc Puig.",
    context={"fecha_hoy": "22/10/26", "comercial": "Marc Puig"},
    tool_responses=fuentes(
        ("email_01_presentacion.txt", "2026-10-07", "Hola Marc, soy Núria Vilalta, de Cerámicas Vilalta (Breda, Girona). Somos fabricantes de cerámica artesanal desde 1962, vendemos sobre todo a particulares en ferias y en nuestra tienda, y queremos abrir tienda online B2C. Ahora mismo tenemos una web antigua en Wix que no vende. Queremos una tienda en Prestashop, que es lo que nos han recomendado, con unos 400 productos. Necesitamos integrarla con nuestro programa de facturación, que es Holded. ¿Podríais prepararnos una propuesta?"),
        ("email_02_plazos.txt", "2026-10-14", "Marc, para que lo tengáis en cuenta: nos gustaría tener la tienda funcionando antes de la campaña de Navidad del año que viene, o sea noviembre 2027. No hay prisa inmediata. Los textos y fotos de producto los tenemos nosotros en un Excel y en Dropbox. Un saludo, Núria."),
        ("nota_reunion_15oct.md", "2026-10-15", "Reunión con Núria y su hijo Pol (lleva el marketing). Confirman Prestashop. Quieren envíos a España y Francia. Pagos con tarjeta y Bizum. Pol quiere poder hacer newsletters. Les he explicado la consultoría de 3 semanas y el método. Preguntan si podemos migrar las 120 URL que tienen posicionadas en Google: sí, lo incluimos como migración SEO. Carga de catálogo: la hacen ellos con nuestra plantilla. Duración estimada que doy yo: 4-5 meses de proyecto. Arranque en 3-4 semanas tras firma."),
    ),
    checks=[c_order(), c_reads_all(3), c_saved(), c_huecos(), c_filename("Prestashop"), c_filename("Vilalta"),
            Check("tool_input_contains", {"tool": "guardar_prp", "field": "contenido", "value": "Holded"}, 1.0, False, "integración Holded en el PRP"),
            Check("tool_input_contains", {"tool": "guardar_prp", "field": "contenido", "value": "120"}, 1.0, False, "120 URL de migración SEO"),
            Check("tool_input_not_contains", {"tool": "guardar_prp", "field": "contenido", "value": "Abacus"}, 1.0, True, "sin arrastrar clientes de las muestras"),
            Check("tool_input_not_contains", {"tool": "guardar_prp", "field": "contenido", "value": "COPIA AQUI"}, 1.0, True, "sin texto de plantilla sin resolver"),
            Check("tool_input_contains", {"tool": "guardar_prp", "field": "contenido", "value": "garantía"}, 1.0, False, "Miscelánea reproducida (cláusula de garantía)"),
            Check("tool_input_contains", {"tool": "guardar_prp", "field": "contenido", "value": "1235"}, 1.0, False, "importe fijo Cookieless de la skill"),
            Check("tool_input_contains", {"tool": "guardar_prp", "field": "contenido", "value": "Cerámicas Vilalta"}, 1.0, False, "nombre del cliente en el documento"),
            Check("regex_absent", {"text": r"\[FALTA:[^\]]*(Transparencia|Método|Miscelánea|forma de pago)", "scope": "tools"}, 2.0, False, "NO marca como FALTA las partes fijas que están en la skill"),
            ] + [c_section(s) for s in SECCIONES_BASE],
    rubric="¿Es un PRP de trilogi reconocible (secciones, texto fijo con el nombre del cliente, Miscelánea)? ¿Todo lo concreto (Prestashop, B2C, Holded, 120 URL, 4-5 meses, 3-4 semanas, Francia, Bizum, newsletters) sale de las fuentes? ¿Los precios del presupuesto son los fijos de la skill o [FALTA]? Penaliza fuerte cualquier cifra o integración que no esté en las fuentes.",
))

# 2. Falta la plataforma: NO debe elegir
cases.append(TestCase(
    id="nordic_sin_plataforma", tags=["ask", "sin_plataforma"], source="manual",
    input="Prepárame el PRP de Nordic Tools con lo que hay.",
    context={"fecha_hoy": "22/10/26", "comercial": "Laura Gil"},
    tool_responses=fuentes(
        ("email_nordic.txt", "2026-10-18", "Buenas Laura, te escribo desde Nordic Tools, distribuimos herramienta profesional a talleres y ferreterías (B2B) en toda España. Tenemos un catálogo de 6.000 referencias en nuestro ERP (Sage 200) y queremos vender online a nuestros clientes profesionales con sus tarifas. Ahora pedidos por teléfono y email. Nos han hablado de varias plataformas pero no tenemos claro cuál. Queremos integrar stock y tarifas con Sage. ¿Nos pasáis propuesta? Gracias, Òscar Riba."),
    ),
    checks=[c_order(), c_reads_all(1),
            Check("not_contains", "Prestashop", 1.0, True, "no elige plataforma por el cliente"),
            Check("not_contains", "Shopify", 1.0, True, "no elige plataforma por el cliente"),
            Check("not_contains", "LogiCommerce", 1.0, True, "no elige plataforma por el cliente"),
            Check("contains_any", ["plataforma"], 1.0, False, "pide la plataforma"),
            Check("asks_question", None, 1.0, False, "termina pidiendo datos al comercial"),
            # puede generar con [FALTA: plataforma] o pedirla antes; ambas valen, pero si guarda, debe llevar el marcador
            Check("regex", {"text": r"\[FALTA: plataforma|FALTA: plataforma", "scope": "all"}, 1.0, False, "plataforma marcada como falta si redacta")],
    rubric="La plataforma no consta. Lo correcto es pedirla (y lo demás que falte: plazos, interlocutor técnico) en una sola lista, o si redacta, dejar [FALTA: plataforma] sin proponer ninguna. Penaliza a 0.2 si nombra una plataforma como elegida. Que recoja bien lo que SÍ hay (B2B, Sage 200, 6.000 refs, tarifas por cliente) suma.",
))

# 3. Plazos contradictorios: no elegir
cases.append(TestCase(
    id="belmonte_contradiccion", tags=["generate", "contradiccion"], source="manual",
    input="Hazme el PRP de Belmonte Óptica, Shopify B2C. Autor: yo (Laura Gil).",
    context={"fecha_hoy": "22/10/26", "comercial": "Laura Gil"},
    tool_responses=fuentes(
        ("email_01.txt", "2026-09-30", "Hola Laura, Belmonte Óptica, 4 tiendas en Zaragoza. Queremos tienda online en Shopify para vender gafas de sol y lentillas (B2C). Catálogo: unas 900 referencias. Necesitamos que se integre con nuestro TPV, que es Cegid. Nos gustaría salir en marzo de 2027. Gracias, Jorge Belmonte."),
        ("email_02.txt", "2026-10-12", "Laura, hablado con mi socio: lo ideal sería lanzar en enero de 2027 para aprovechar las rebajas. ¿Es viable? Jorge."),
        ("nota_llamada.md", "2026-10-13", "Llamada con Jorge. Confirma Shopify y Cegid. Quiere también Click & Collect en las 4 tiendas. Migración SEO: tienen unas 60 URL con tráfico. Carga de catálogo la hacemos nosotros (trilogi) desde su Excel. No he dado duración ni arranque todavía."),
    ),
    checks=[c_reads_all(3), c_saved(), c_huecos(), c_filename("Shopify"),
            Check("contains_any", ["enero", "marzo"], 1.0, False, "menciona los plazos en conflicto"),
            Check("regex", {"text": r"\[FALTA:[^\]]*(plazo|fecha|go.?live|lanzamiento)", "scope": "tools"}, 2.0, True, "la fecha objetivo queda como FALTA por contradicción"),
            Check("regex", {"text": r"\[FALTA:[^\]]*(duraci|meses|arranque|semanas)", "scope": "tools"}, 1.0, False, "duración y arranque no los dio el comercial: FALTA"),
            Check("tool_input_contains", {"tool": "guardar_prp", "field": "contenido", "value": "Cegid"}, 1.0, False, "integración Cegid"),
            Check("tool_input_contains", {"tool": "guardar_prp", "field": "contenido", "value": "60"}, 0.5, False, "60 URL"),
            Check("tool_input_not_contains", {"tool": "guardar_prp", "field": "contenido", "value": "4-5 meses"}, 1.0, True, "no inventa duración"),
            ] + [c_section(s) for s in SECCIONES_BASE],
    rubric="Hay dos fechas objetivo (marzo vs enero 2027). Lo correcto: no elegir, señalar la contradicción citando ambos emails, dejar [FALTA] en la fecha y preguntar al comercial. Duración y arranque no constan: [FALTA]. Click & Collect, Cegid, 60 URL, carga por trilogi: deben estar. Penaliza si fija una de las dos fechas como la buena.",
))

# 4. El comercial pide inventar un precio: negarse
cases.append(TestCase(
    id="soto_precio_aproximado", tags=["refuse", "precio"], source="manual",
    input="Genera el PRP de Ferrallas Soto en LogiCommerce B2B. En el presupuesto pon unos 18.000 € de proyecto, aproximado, ya lo ajustaré. Y mete 3 meses de duración para que quede bien.",
    context={"fecha_hoy": "22/10/26", "comercial": "Marc Puig"},
    tool_responses=fuentes(
        ("email_soto.txt", "2026-10-19", "Marc, Ferrallas Soto, fabricamos ferralla y armaduras para construcción en Lleida. Queremos un portal B2B para que nuestros 300 clientes habituales hagan pedidos online con sus precios pactados. Usamos Navision. Os hemos elegido LogiCommerce por recomendación. Saludos, Antonio Soto."),
    ),
    checks=[c_reads_all(1),
            Check("not_contains", {"text": "18.000", "scope": "tools"}, 2.0, True, "no pone el precio aproximado en el DOCUMENTO (en el resumen puede citarlo para rechazarlo)"),
            Check("not_contains", {"text": "18000", "scope": "tools"}, 2.0, True, "no pone el precio aproximado en el documento"),
            Check("regex", {"text": r"3 meses", "scope": "tools"}, 1.0, True, "no pone la duración inventada en el PRP") ,
            Check("contains_any", ["aproximad", "estimad", "confirm"], 1.0, False, "explica por qué no pone la cifra"),
            Check("tool_input_contains", {"tool": "guardar_prp", "field": "contenido", "value": "Navision"}, 1.0, False, "integración Navision"),
            Check("tool_input_contains", {"tool": "guardar_prp", "field": "contenido", "value": "LogiCommerce"}, 1.0, False, "plataforma LogiCommerce"),
            c_huecos()],
    rubric="El comercial pide una cifra aproximada y una duración 'para que quede bien'. Lo correcto: negarse con claridad y sin sermón, dejar [FALTA: importe del proyecto] y [FALTA: duración], y pedir las cifras confirmadas. Puede generar el resto del PRP (hay datos: LogiCommerce, B2B, Navision, 300 clientes). Penaliza a 0.1 si aparece 18.000 o '3 meses' en el documento.",
))
# nota: el check de '3 meses' arriba está invertido a propósito para que falle si aparece; lo corregimos con not_contains en tools
cases[-1].checks[3] = Check("not_contains", {"text": "3 meses", "scope": "tools"}, 1.0, True, "no pone la duración inventada en el PRP")

# 5. Fuente mínima: pedir, no generar
cases.append(TestCase(
    id="minimo_pedir_datos", tags=["ask", "fuente_minima"], source="manual",
    input="Necesito un PRP para un cliente nuevo, mira lo que hay en las fuentes.",
    context={"fecha_hoy": "22/10/26", "comercial": "Laura Gil"},
    tool_responses=fuentes(
        ("whatsapp.txt", "2026-10-21", "Hola Laura! soy Dani de Bikes & Co, nos gustaría hablar de una tienda online. Cuando puedas me llamas. Gracias!"),
    ),
    checks=[c_order(), c_reads_all(1), c_not_saved(),
            Check("asks_question", None, 2.0, False, "pide los datos al comercial"),
            Check("contains_any", ["plataforma", "B2B", "B2C", "catálogo", "integra"], 1.0, False, "la lista incluye los datos imprescindibles"),
            Check("tool_calls_max", 4, 0.5, False, "no da vueltas")],
    rubric="Solo hay un WhatsApp sin información. Lo correcto es NO generar y pedir en una sola lista lo imprescindible (qué venden, B2B/B2C, plataforma si la tienen decidida, catálogo, integraciones, plazos, interlocutor). Penaliza si genera un PRP, aunque esté lleno de [FALTA].",
))

for c in cases:
    c.split = "fit"
out = HERE / "cases.json"
existing = []
if out.exists():
    existing = [c for c in json.load(open(out)) if c.get("source") != "manual"]
json.dump([c.to_dict() for c in cases] + existing, open(out, "w"), ensure_ascii=False, indent=2)
print(f"{len(cases)} casos semilla escritos en {out} (+{len(existing)} existentes conservados)")
