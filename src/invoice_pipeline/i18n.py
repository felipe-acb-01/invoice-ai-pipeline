"""The screen in English or Spanish. English is the key; ES holds the Spanish (Chile) of every visible sentence.

The language comes from `?lang=` (the portfolio's Spanish page links with `?lang=es`), then from the cookie that
`?lang=` leaves, and is English otherwise. tests/test_i18n.py fails if a sentence on screen has no Spanish.
"""

from __future__ import annotations

from datetime import date

LANGS = ("en", "es")
COOKIE = "lang"

ES = {
    # header and demo bar
    "Invoice approvals": "Aprobación de facturas",
    "Invoice status": "Estado de las facturas",
    "To approve": "Por aprobar",
    "Approved": "Aprobadas",
    "Rejected": "Rechazadas",
    "Set aside": "Apartadas",
    "Approving as a demo visitor": "Apruebas como visitante de la demo",
    "Signed in as {who}": "Sesión de {who}",
    "Export approved (.xlsx)": "Exportar aprobadas (.xlsx)",
    "Language": "Idioma",
    "Live demo.": "Demo en vivo.",
    "How it works ↗": "Cómo funciona ↗",
    "Sample invoices, already read by Claude Haiku. Approve them, reject them, export them, or try one of your own.":
        "Facturas de ejemplo, ya leídas por Claude Haiku. Apruébalas, recházalas, expórtalas o prueba con una tuya.",
    "No personal data, please: everything is deleted after 24 hours.":
        "Sin datos personales, por favor: todo se borra a las 24 horas.",
    "Invoices read by AI, checked by rules and approved by a person. A live demo with sample invoices: approve, reject, export or upload your own.":
        "Facturas leídas con IA, revisadas con reglas y aprobadas por una persona. Una demo en vivo con facturas de ejemplo: aprueba, rechaza, exporta o sube una tuya.",
    "Invoice approvals · live demo": "Aprobación de facturas · demo en vivo",
    "Approved: {vendor}. This is the next one waiting.": "Aprobada: {vendor}. Ésta es la siguiente por aprobar.",
    "Rejected: {vendor}. This is the next one waiting.": "Rechazada: {vendor}. Ésta es la siguiente por aprobar.",
    "Approved: {vendor}. Nothing else is waiting.": "Aprobada: {vendor}. No queda nada por aprobar.",
    "Rejected: {vendor}. Nothing else is waiting.": "Rechazada: {vendor}. No queda nada por aprobar.",
    "The reading service returned an error. Open it to see the details.":
        "El servicio de lectura devolvió un error. Ábrela para ver el detalle.",
    "The reading service returned an error, so nothing was taken from this file.":
        "El servicio de lectura devolvió un error, así que no se tomó nada de este archivo.",
    "This page does not exist": "Esta página no existe",
    "The invoice may belong to another visitor, or the demo was started over. Your invoices are in the queue.":
        "Puede que la factura sea de otro visitante o que la demo se haya reiniciado. Tus facturas están en la cola.",
    "Back to the queue": "Volver a la cola",
    "Start over": "Empezar de nuevo",
    "Started a fresh demo with the sample invoices.": "Empezaste una demo nueva con las facturas de ejemplo.",
    # queue
    "Try it with your own invoice": "Pruébala con tu propia factura",
    "Drop it here or choose a file · PDF, JPG or PNG, up to 5 MB and 3 pages.":
        "Suéltala aquí o elige un archivo · PDF, JPG o PNG, hasta 5 MB y 3 páginas.",
    "1 upload left today.": "Te queda 1 subida hoy.",
    "{n} uploads left today.": "Te quedan {n} subidas hoy.",
    "Read it": "Leerla",
    "Reading…": "Leyendo…",
    "{flagged} of {total} need a closer look": "{flagged} de {total} merecen una segunda mirada",
    "Vendor": "Proveedor",
    "Invoice": "Factura",
    "Issued": "Emitida",
    "Due": "Vence",
    "Total": "Total",
    "Checks": "Revisión",
    "Decided": "Decidida",
    "On receipt": "Al recibir",
    "All checks passed": "Todo cuadra",
    "{n} to review": "{n} por revisar",
    "Not an invoice": "No es factura",
    "Not read": "No se leyó",
    "Nothing waiting for approval": "Nada esperando aprobación",
    "New invoices appear here as soon as they are read.": "Las facturas nuevas aparecen aquí apenas se leen.",
    "Nothing set aside": "Nada apartado",
    "Files that cannot be read, or that are not invoices, land here with the reason.":
        "Aquí llegan, con el motivo, los archivos que no se pueden leer o que no son facturas.",
    "No approved invoices yet": "Todavía no hay facturas aprobadas",
    "No rejected invoices yet": "Todavía no hay facturas rechazadas",
    "Reading cost so far: US$ {cost}": "Costo de lectura hasta ahora: US$ {cost}",
    # detail
    "Original document": "Documento original",
    "{n} pages": "{n} páginas",
    "Open original": "Abrir original",
    "Page {n} of the original invoice": "Página {n} de la factura original",
    "Photo of the original invoice": "Foto de la factura original",
    "Invoice {number} · issued {date}": "Factura {number} · emitida el {date}",
    "Due {date}": "Vence el {date}",
    "Due on receipt": "Se paga al recibir",
    "Claude read it and it is not a bill to pay (it looks like a quote, a receipt, a contract or another kind of "
    "document), so there is nothing to approve. It stays here in case someone needs it.":
        "Claude lo leyó y no es una cuenta por pagar (parece una cotización, una boleta, un contrato u otro tipo de "
        "documento), así que no hay nada que aprobar. Queda aquí por si alguien lo necesita.",
    "This document could not be read": "Este documento no se pudo leer",
    "Open the original on the left. If it is an invoice, enter it by hand; if it is not, it can be ignored.":
        "Abre el original a la izquierda. Si es una factura, ingrésala a mano; si no, se puede ignorar.",
    "Review before approving": "Revisar antes de aprobar",
    "Compare with:": "Compárala con:",
    "same number": "mismo número",
    "same date and total": "misma fecha y total",
    "The lines add up, the tax matches, the dates are in order and no earlier invoice looks like this one.":
        "Las líneas suman, el impuesto calza, las fechas están en orden y ninguna factura anterior se parece a ésta.",
    "Note (optional, saved with your decision)": "Nota (opcional, se guarda con tu decisión)",
    "Why you approve it anyway, or why it is rejected": "Por qué la apruebas igual, o por qué la rechazas",
    "e.g. cost center": "p. ej., centro de costo",
    "Approve": "Aprobar",
    "Reject": "Rechazar",
    "approved": "Aprobada",
    "rejected": "Rechazada",
    "By {who} on {date}": "Por {who} el {date}",
    "Demo visitor": "Visitante de la demo",
    "Vendor tax ID": "ID tributario del proveedor",
    "Billed to": "Facturada a",
    "Currency": "Moneda",
    "Source file": "Archivo",
    "Read by": "Leída por",
    "{model} in {seconds} s · US$ {cost}": "{model} en {seconds} s · US$ {cost}",
    "Description": "Descripción",
    "Qty": "Cant.",
    "Unit price": "Precio unitario",
    "Amount": "Monto",
    "Subtotal": "Subtotal",
    "Tax": "Impuesto",
    "Exempt": "Exento",
    "Other taxes": "Otros impuestos",
    # alerts (web.explain and validate.FLAGS)
    "{amount} too much": "{amount} de más",
    "{amount} too little": "{amount} de menos",
    "The IVA should be {expected} (19 % of {net}); the invoice says {tax}, {off}.":
        "El IVA debería ser {expected} (19 % de {net}); la factura dice {tax}, {off}.",
    "Subtotal {subtotal} plus tax {tax} is {expected}; the invoice says {total}, {off}.":
        "Subtotal {subtotal} más impuesto {tax} da {expected}; la factura dice {total}, {off}.",
    "The lines add up to {lines}; the subtotal says {subtotal}, {off}.":
        "Las líneas suman {lines}; el subtotal dice {subtotal}, {off}.",
    "Net {subtotal} + exempt {exempt} + IVA {tax} + other taxes {other} is {expected}; the invoice says {total}, {off}.":
        "Neto {subtotal} + exento {exempt} + IVA {tax} + otros impuestos {other} da {expected}; la factura dice {total}, {off}.",
    "The lines add up to {lines}; net {subtotal} plus exempt {exempt} is {printed}, {off}.":
        "Las líneas suman {lines}; neto {subtotal} más exento {exempt} da {printed}, {off}.",
    "“{description}”: {quantity} × {price} = {product}, but the line says {amount}.":
        "«{description}»: {quantity} × {price} = {product}, pero la línea dice {amount}.",
    "Due {due}, before the issue date {issued}.": "Vence el {due}, antes de la fecha de emisión ({issued}).",
    "The invoice is in {currency}, not in the currency the books are kept in.":
        "La factura está en {currency}, no en la moneda en que se lleva la contabilidad.",
    "A line's quantity × unit price does not match its amount.":
        "En una línea, cantidad × precio unitario no da el monto.",
    "The lines do not add up to the subtotal.": "Las líneas no suman el subtotal.",
    "Subtotal plus tax does not equal the total.": "Subtotal más impuesto no da el total.",
    "The due date is before the issue date.": "El vencimiento es anterior a la emisión.",
    "A date could not be read as YYYY-MM-DD.": "Una fecha no se pudo leer como AAAA-MM-DD.",
    "The invoice is not in the base currency.": "La factura no está en la moneda base.",
    "This vendor already sent an invoice with this number.": "Este proveedor ya mandó una factura con este número.",
    "Same vendor, date and total as an earlier invoice, with a different number.":
        "Mismo proveedor, fecha y total que una factura anterior, con otro número.",
    "Chilean IVA is not 19 % of the net amount.": "El IVA no es el 19 % del neto.",
    "This does not look like an invoice.": "Esto no parece una factura.",
    "This file type cannot be read: only PDF, JPG and PNG. Open it and enter it by hand if it is an invoice.":
        "Este tipo de archivo no se puede leer: sólo PDF, JPG y PNG. Ábrelo e ingrésalo a mano si es una factura.",
    "A file type that cannot be read": "Un tipo de archivo que no se puede leer",
    "This file cannot be shown here.": "Este archivo no se puede mostrar aquí.",
    "Download it": "Descárgalo",
    "Not a PDF or image": "No es PDF ni imagen",
    # upload limits (demo.DemoLimit)
    "This demo reads {limit} uploads per visitor per day. Try again tomorrow.":
        "La demo lee {limit} subidas por visitante al día. Vuelve a intentarlo mañana.",
    "The demo reached today's upload limit. Try again tomorrow, or open a sample invoice.":
        "La demo llegó al límite de subidas de hoy. Vuelve mañana o abre una factura de ejemplo.",
    "The file is empty.": "El archivo está vacío.",
    "The file is larger than 5 MB.": "El archivo pesa más de 5 MB.",
    "Upload a PDF, JPG or PNG.": "Sube un PDF, JPG o PNG.",
    "That PDF could not be opened.": "Ese PDF no se pudo abrir.",
    "The demo reads documents of up to {most} pages; this one has {pages}.":
        "La demo lee documentos de hasta {most} páginas; éste tiene {pages}.",
}

MONTHS_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sept", "oct", "nov", "dic")


def tr(text: str, lang: str, **values) -> str:
    """The sentence in `lang`, with its values filled in. A sentence without Spanish stays in English."""
    out = ES.get(text, text) if lang == "es" else text
    return out.format(**values) if values else out


def nice_date(value: str | None, lang: str = "en") -> str:
    if not value:
        return "—"
    try:
        d = date.fromisoformat(value[:10])
    except ValueError:
        return value
    if lang == "es":
        return f"{d.day} {MONTHS_ES[d.month - 1]} {d.year}"
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def decimal(value: float, places: int, lang: str) -> str:
    """Seconds and reading costs: a decimal comma in Spanish."""
    text = f"{value:.{places}f}"
    return text.replace(".", ",") if lang == "es" else text
