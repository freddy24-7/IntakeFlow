"""Fixed building blocks for the synthetic documents: buyer, goods, layouts and labels."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Supplier:
    name: str
    street: str
    postcode_city: str
    kvk: str
    vat_number: str
    iban: str
    language: str  # "nl" or "en"
    layout: str
    label_variant: int
    number_style: int
    date_style: str  # nl: "numeric" or "long". en: "long" or "iso"
    iban_grouped: bool
    payment_term_days: int


BUYER_NAME = "Noordzee Logistiek B.V."
BUYER_LINES = (BUYER_NAME, "Afd. Crediteurenadministratie", "Havenkade 12", "3011 AB Rotterdam")


@dataclass(frozen=True)
class CatalogItem:
    nl: str
    en: str
    min_price: int  # euros
    max_price: int
    vat_rate: Decimal
    half_units: bool = False  # quantities like 2,5 (hours)


_HIGH, _LOW, _ZERO = Decimal("21"), Decimal("9"), Decimal("0")

CATALOG = (
    CatalogItem(
        "Palletvervoer Rotterdam - Venlo", "Pallet transport Rotterdam - Venlo", 45, 95, _HIGH
    ),
    CatalogItem("Containeroverslag 40ft", "Container handling 40ft", 180, 420, _HIGH),
    CatalogItem(
        "Opslag per palletplaats per maand", "Storage per pallet space per month", 6, 14, _HIGH
    ),
    CatalogItem("Douaneafhandeling", "Customs clearance", 60, 140, _HIGH),
    CatalogItem("Heftruckhuur per dag", "Forklift rental per day", 85, 160, _HIGH),
    CatalogItem("Onderhoud koelinstallatie", "Cooling unit maintenance", 250, 1800, _HIGH),
    CatalogItem("Brandstoftoeslag", "Fuel surcharge", 15, 220, _HIGH),
    CatalogItem("Verpakkingsmateriaal doos 60x40x40", "Packaging box 60x40x40", 2, 6, _HIGH),
    CatalogItem("Stretchfolie rol 500 mm", "Stretch film roll 500 mm", 8, 19, _HIGH),
    CatalogItem(
        "Uitzendkracht magazijn (uur)", "Temporary warehouse staff (hour)", 28, 42, _HIGH, True
    ),
    CatalogItem("Schoonmaak bedrijfshal", "Warehouse cleaning", 150, 650, _HIGH),
    CatalogItem("Bandenwissel vrachtwagen", "Truck tyre change", 90, 240, _HIGH),
    CatalogItem(
        "Softwarelicentie WMS per maand", "WMS software licence per month", 300, 1250, _HIGH
    ),
    CatalogItem("Veiligheidsschoenen S3", "Safety shoes S3", 55, 110, _HIGH),
    CatalogItem("Europallets gebruikt", "Used euro pallets", 7, 13, _HIGH),
    CatalogItem("Keuring hefmiddelen", "Lifting equipment inspection", 120, 480, _HIGH),
    CatalogItem("Advieswerkzaamheden (uur)", "Consultancy (hour)", 85, 145, _HIGH, True),
    CatalogItem("Lunch personeelsbijeenkomst", "Staff meeting lunch", 9, 18, _LOW),
    CatalogItem("Drinkwater flessen 18 liter", "Drinking water bottles 18 litre", 6, 11, _LOW),
    CatalogItem(
        "Internationaal transport (btw verlegd)",
        "International transport (reverse charge)",
        400,
        2400,
        _ZERO,
    ),
)


@dataclass(frozen=True)
class Layout:
    name: str
    font: str
    bold_font: str
    supplier_left: bool
    band: bool  # coloured band across the top
    table_fill: bool  # shaded table header instead of a rule
    details_in_footer: bool  # VAT number and IBAN at the bottom instead of the top
    accent: tuple[float, float, float]


LAYOUTS = {
    layout.name: layout
    for layout in (
        Layout(
            "classic", "Helvetica", "Helvetica-Bold", True, False, False, False, (0.1, 0.1, 0.1)
        ),
        Layout("modern", "Helvetica", "Helvetica-Bold", False, True, True, True, (0.05, 0.3, 0.5)),
        Layout("serif", "Times-Roman", "Times-Bold", True, False, True, True, (0.45, 0.1, 0.1)),
        Layout(
            "typewriter", "Courier", "Courier-Bold", False, False, False, False, (0.0, 0.0, 0.0)
        ),
    )
}
# Contracts and letters are not laid out like invoices.
PLAIN_LAYOUT = "plain"


@dataclass(frozen=True)
class Labels:
    invoice_title: str
    credit_title: str
    number: str
    date: str
    due: str
    po: str
    bill_to: str
    description: str
    quantity: str
    unit_price: str
    vat_rate: str
    amount: str
    subtotal: str
    vat: str
    total: str
    vat_number: str
    iban: str
    chamber: str
    payment: str  # template with {days}, {iban} and {number}


LABELS: dict[str, tuple[Labels, ...]] = {
    "nl": (
        Labels(
            "FACTUUR",
            "CREDITNOTA",
            "Factuurnummer",
            "Factuurdatum",
            "Vervaldatum",
            "Uw referentie",
            "Factuur aan",
            "Omschrijving",
            "Aantal",
            "Prijs",
            "Btw",
            "Bedrag",
            "Subtotaal",
            "Btw",
            "Totaal te betalen",
            "Btw-nummer",
            "IBAN",
            "KvK",
            "Gelieve het totaalbedrag binnen {days} dagen over te maken op {iban} onder"
            " vermelding van {number}.",
        ),
        Labels(
            "Factuur",
            "Creditfactuur",
            "Factuurnr.",
            "Datum",
            "Uiterste betaaldatum",
            "Inkoopordernummer",
            "Geadresseerde",
            "Artikel",
            "Aantal",
            "Stukprijs",
            "Btw %",
            "Totaal",
            "Totaal excl. btw",
            "Btw-bedrag",
            "Totaal incl. btw",
            "BTW-nr.",
            "Bankrekening",
            "KvK-nr.",
            "Betaling binnen {days} dagen na factuurdatum op rekening {iban}. Vermeld bij uw"
            " betaling {number}.",
        ),
        Labels(
            "NOTA",
            "CREDITNOTA",
            "Notanummer",
            "Notadatum",
            "Te betalen voor",
            "PO-nummer",
            "Aan",
            "Omschrijving",
            "Aantal",
            "Tarief",
            "Btw",
            "Bedrag",
            "Netto",
            "Btw",
            "Totaal",
            "BTW-id",
            "IBAN",
            "Handelsregister",
            "Wij verzoeken u het bedrag binnen {days} dagen te voldoen op {iban}, kenmerk"
            " {number}.",
        ),
    ),
    "en": (
        Labels(
            "INVOICE",
            "CREDIT NOTE",
            "Invoice number",
            "Invoice date",
            "Due date",
            "PO number",
            "Bill to",
            "Description",
            "Qty",
            "Unit price",
            "VAT",
            "Amount",
            "Subtotal",
            "VAT",
            "Total due",
            "VAT number",
            "IBAN",
            "Chamber of Commerce",
            "Please transfer the total amount within {days} days to {iban}, quoting {number}.",
        ),
    ),
}

STAMP_TEXTS = ("ONTVANGEN", "BETAALD", "AKKOORD", "GEBOEKT")
