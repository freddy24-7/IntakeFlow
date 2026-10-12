"""Dutch interface text for field names, review reasons, flags and statuses."""

FIELD_LABELS = {
    "supplier_name": "Leverancier",
    "supplier_vat_number": "Btw-nummer",
    "iban": "IBAN",
    "invoice_number": "Factuurnummer",
    "invoice_date": "Factuurdatum",
    "due_date": "Vervaldatum",
    "currency": "Valuta",
    "subtotal": "Subtotaal",
    "vat": "Btw-bedrag",
    "total": "Totaal",
    "purchase_order_reference": "Inkoopordernummer",
}

REASON_LABELS = {
    "totals_mismatch": "Totalen kloppen niet met de regels en de btw",
    "invoice_date_implausible": "Factuurdatum is onwaarschijnlijk",
    "due_date_before_invoice_date": "Vervaldatum ligt vóór de factuurdatum",
    "vat_number_format": "Btw-nummer heeft een ongeldig formaat",
    "iban_checksum": "IBAN is ongeldig (controlegetal)",
    "po_missing": "Geen inkoopordernummer op de factuur",
    "po_not_found": "Inkooporder is onbekend",
    "po_supplier_mismatch": "Inkooporder hoort bij een andere leverancier",
    "po_amount_out_of_tolerance": "Bedrag wijkt af van de inkooporder",
    "duplicate_invoice": "Dubbele factuur (zelfde leverancier en nummer)",
    "score_below_threshold": "Score onder de drempel",
    "classification_uncertain": "Documentsoort is onzeker",
    "not_an_invoice": "Geen factuur of creditnota",
    "already_in_erp": "Deze factuur is al geboekt",
}

FLAG_LABELS = {
    "di_disagrees": "Twee bronnen lezen iets anders",
    "unparseable": "Waarde kon niet worden gelezen",
    "normalisation_mismatch": "Omrekening klopt niet met de afgedrukte tekst",
}

STATUS_LABELS = {
    "received": "Ontvangen",
    "processing": "In verwerking",
    "in_review": "Wacht op beoordeling",
    "approved": "Goedgekeurd",
    "auto_approved": "Automatisch goedgekeurd",
    "rejected": "Afgewezen",
    "failed": "Mislukt",
    "indexed": "Doorzoekbaar",
}

TYPE_LABELS = {
    "invoice": "Factuur",
    "credit_note": "Creditnota",
    "contract": "Contract",
    "other": "Overig",
}


def reason_label(reason: str) -> str:
    """Reasons like `missing_iban` and `flagged_total` are built from a field name."""
    if reason in REASON_LABELS:
        return REASON_LABELS[reason]
    for prefix, text in (("missing_", "ontbreekt"), ("flagged_", "is gemarkeerd")):
        field = reason.removeprefix(prefix)
        if reason.startswith(prefix) and field in FIELD_LABELS:
            return f"{FIELD_LABELS[field]} {text}"
    return reason
