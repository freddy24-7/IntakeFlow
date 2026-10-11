"""Decides what the synthetic set contains. No drawing happens here.

Everything random comes from one seeded generator, so a seed fully determines
the documents, the hard cases and the labels.
"""

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from faker import Faker

from app.common.dutch import format_dutch_date, format_dutch_decimal
from synthetic.catalog import (
    CATALOG,
    LABELS,
    LAYOUTS,
    PLAIN_LAYOUT,
    STAMP_TEXTS,
    Supplier,
)
from synthetic.contracts import make_contract
from synthetic.iban import with_check_digits
from synthetic.render import layout_contract
from synthetic.truth import (
    CONTENT_CASES,
    ContractTruth,
    DocumentTruth,
    DocumentType,
    InvoiceFields,
    LineItem,
    PurchaseOrderTruth,
)

MINIMUM_DOCUMENTS = 30
CENT = Decimal("0.01")
FIRST_INVOICE_DATE = date(2026, 1, 5)
# Made-up bank codes, so no IBAN points at a real bank.
BANK_CODES = ("NZLB", "DELT", "HAVN", "WADB", "POLD")
NUMBER_STYLES = ("F{year}-{n:04d}", "{year}/{n:05d}", "INV-{n:06d}", "RN{yy}{n:05d}", "{n:08d}")

# Share of invoices and credit notes that get each hard case (at least one each).
CONTENT_SHARES = {
    "missing_po": 0.05,
    "unknown_po": 0.02,
    "totals_mismatch": 0.04,
    "wrong_iban": 0.03,
    "invalid_vat_number": 0.02,
    "po_supplier_mismatch": 0.02,
    "po_amount_mismatch": 0.03,
    "due_before_invoice": 0.02,
}
VISUAL_SHARES = {"scanned": 0.08, "scanned_skewed": 0.05, "stamp": 0.05}


@dataclass(frozen=True)
class Counts:
    invoices: int
    credit_notes: int
    duplicates: int
    contracts: int
    others: int


def plan_counts(total: int) -> Counts:
    if total < MINIMUM_DOCUMENTS:
        raise ValueError(f"need at least {MINIMUM_DOCUMENTS} documents to cover every hard case")
    credit_notes = max(2, round(total * 0.10))
    duplicates = max(1, round(total * 0.03))
    contracts = max(3, round(total * 0.04))
    others = max(2, round(total * 0.03))
    invoices = total - credit_notes - duplicates - contracts - others
    return Counts(invoices, credit_notes, duplicates, contracts, others)


@dataclass(eq=False)
class Draft:
    """A document being put together, before it gets its id."""

    doc_type: DocumentType
    supplier: Supplier
    invoice: InvoiceFields | None = None
    contract: ContractTruth | None = None
    purchase_order: PurchaseOrderTruth | None = None
    hard_cases: list[str] = field(default_factory=list)
    scanned: bool = False
    skew_degrees: float | None = None
    stamp_text: str | None = None
    duplicate_of: "Draft | None" = None
    other_kind: str | None = None
    letter: tuple[str, list[str]] | None = None


@dataclass(frozen=True)
class RenderPlan:
    """What the renderer needs besides the ground truth."""

    supplier: Supplier
    stamp_text: str | None = None
    letter: tuple[str, list[str]] | None = None


@dataclass(frozen=True)
class Dataset:
    seed: int
    documents: list[DocumentTruth]
    purchase_orders: list[PurchaseOrderTruth]
    plans: dict[str, RenderPlan]


def generate(documents: int, seed: int) -> Dataset:
    counts = plan_counts(documents)
    rng = random.Random(seed)
    fake = Faker("nl_NL")
    fake.seed_instance(seed)
    suppliers = _make_suppliers(rng, fake)
    used_numbers: set[tuple[str, str]] = set()
    used_po_numbers: set[str] = set()

    money_types: list[DocumentType] = ["invoice"] * counts.invoices
    money_types += ["credit_note"] * counts.credit_notes
    money = [
        _make_money_draft(rng, rng.choice(suppliers), doc_type, used_numbers, used_po_numbers)
        for doc_type in money_types
    ]

    # Content cases never overlap, so each failure has one known cause.
    order = list(range(len(money)))
    rng.shuffle(order)
    for case, share in CONTENT_SHARES.items():
        for _ in range(max(1, round(len(money) * share))):
            _apply_content_case(rng, money[order.pop()], case, suppliers)
    clean = [money[index] for index in order]

    # Visual cases are drawn separately and may land on a document with a content case.
    order = list(range(len(money)))
    rng.shuffle(order)
    for case, share in VISUAL_SHARES.items():
        for _ in range(max(1, round(len(money) * share))):
            _apply_visual_case(rng, money[order.pop()], case)

    duplicates = [_duplicate(original) for original in rng.sample(clean, counts.duplicates)]
    contracts = [
        Draft("contract", supplier, contract=_paginated(make_contract(rng, supplier, number)))
        for number, supplier in enumerate(rng.sample(suppliers, counts.contracts), start=1)
    ]
    others = [_make_other(rng, rng.choice(suppliers)) for _ in range(counts.others)]

    drafts = money + duplicates + contracts + others
    rng.shuffle(drafts)
    # A duplicate is the copy that arrives second, so it must come after its original.
    for duplicate in duplicates:
        assert duplicate.duplicate_of is not None
        first, second = drafts.index(duplicate), drafts.index(duplicate.duplicate_of)
        if first < second:
            drafts[first], drafts[second] = drafts[second], drafts[first]

    doc_ids = {id(draft): f"doc-{number:04d}" for number, draft in enumerate(drafts, start=1)}
    truths = [_to_truth(draft, doc_ids) for draft in drafts]
    purchase_orders = sorted(
        (draft.purchase_order for draft in money if draft.purchase_order is not None),
        key=lambda po: po.po_number,
    )
    plans = {
        doc_ids[id(draft)]: RenderPlan(draft.supplier, draft.stamp_text, draft.letter)
        for draft in drafts
    }
    return Dataset(seed=seed, documents=truths, purchase_orders=purchase_orders, plans=plans)


# Faker's own company names include real Dutch companies, so names are built
# here from a surname and a line of business instead.
COMPANY_PATTERNS = (
    "{a} Transport B.V.",
    "{a} Logistiek B.V.",
    "{a} & {b} Techniek",
    "{a} Verpakkingen B.V.",
    "Schoonmaakbedrijf {a}",
    "{a} Koeltechniek B.V.",
    "Uitzendbureau {a} & {b}",
    "{a} Software B.V.",
    "Bandenservice {a}",
    "{a} & {b} Advies V.O.F.",
    "{a} Intern Transport B.V.",
    "Douanekantoor {a}",
)


def _company_name(rng: random.Random, fake: Faker) -> str:
    return rng.choice(COMPANY_PATTERNS).format(a=fake.last_name(), b=fake.last_name())


def _make_suppliers(rng: random.Random, fake: Faker, count: int = 25) -> list[Supplier]:
    suppliers: list[Supplier] = []
    names: set[str] = set()
    while len(suppliers) < count:
        name = _company_name(rng, fake)
        if name in names:
            continue
        names.add(name)
        language = "en" if len(suppliers) % 6 == 5 else "nl"
        bban = f"{rng.choice(BANK_CODES)}{rng.randrange(10**10):010d}"
        suppliers.append(
            Supplier(
                name=name,
                street=str(fake.street_address()),
                postcode_city=f"{fake.postcode()} {fake.city()}",
                kvk=f"{rng.randrange(10**8):08d}",
                vat_number=f"NL{rng.randrange(10**9):09d}B{rng.randint(1, 99):02d}",
                iban=with_check_digits("NL", bban),
                language=language,
                layout=rng.choice(sorted(LAYOUTS)),
                label_variant=rng.randrange(len(LABELS[language])),
                number_style=rng.randrange(len(NUMBER_STYLES)),
                date_style=rng.choice(("numeric", "long") if language == "nl" else ("long", "iso")),
                iban_grouped=rng.random() < 0.4,
                payment_term_days=rng.choice((14, 30, 30, 60)),
            )
        )
    return suppliers


def totals(lines: list[LineItem]) -> tuple[Decimal, Decimal, Decimal]:
    """Subtotal, VAT and total. VAT is rounded per rate, as on a Dutch invoice."""
    subtotal = sum((line.line_total for line in lines), Decimal(0))
    vat = Decimal(0)
    for rate in {line.vat_rate for line in lines}:
        base = sum((line.line_total for line in lines if line.vat_rate == rate), Decimal(0))
        vat += (base * rate / 100).quantize(CENT, ROUND_HALF_UP)
    return subtotal, vat, subtotal + vat


def _make_lines(rng: random.Random, language: str, count: int) -> list[LineItem]:
    lines = []
    for item in rng.sample(CATALOG, count):
        quantity = (
            Decimal(rng.randint(2, 80)) / 2 if item.half_units else Decimal(rng.randint(1, 40))
        )
        unit_price = Decimal(rng.randint(item.min_price * 100, item.max_price * 100)) / 100
        lines.append(
            LineItem(
                description=item.nl if language == "nl" else item.en,
                quantity=quantity,
                unit_price=unit_price,
                vat_rate=item.vat_rate,
                line_total=(quantity * unit_price).quantize(CENT, ROUND_HALF_UP),
            )
        )
    return lines


def _make_money_draft(
    rng: random.Random,
    supplier: Supplier,
    doc_type: DocumentType,
    used_numbers: set[tuple[str, str]],
    used_po_numbers: set[str],
) -> Draft:
    invoice_date = FIRST_INVOICE_DATE + timedelta(days=rng.randrange(270))
    while True:
        number = NUMBER_STYLES[supplier.number_style].format(
            year=invoice_date.year, yy=invoice_date.year % 100, n=rng.randrange(1, 9999)
        )
        if doc_type == "credit_note":
            number = f"C{number}"
        if (supplier.name, number) not in used_numbers:
            used_numbers.add((supplier.name, number))
            break
    while True:
        po_number = f"PO-{invoice_date.year}-{rng.randrange(10**5):05d}"
        if po_number not in used_po_numbers:
            used_po_numbers.add(po_number)
            break

    max_lines = 3 if doc_type == "credit_note" else 8
    lines = _make_lines(rng, supplier.language, rng.randint(1, max_lines))
    subtotal, vat, total = totals(lines)
    invoice = InvoiceFields(
        supplier_name=supplier.name,
        supplier_vat_number=supplier.vat_number,
        iban=supplier.iban,
        invoice_number=number,
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=supplier.payment_term_days),
        currency="EUR",
        line_items=lines,
        subtotal=subtotal,
        vat=vat,
        total=total,
        purchase_order_reference=po_number,
    )
    purchase_order = PurchaseOrderTruth(
        po_number=po_number,
        supplier_name=supplier.name,
        supplier_vat_number=supplier.vat_number,
        amount=total,
        currency="EUR",
    )
    return Draft(doc_type, supplier, invoice=invoice, purchase_order=purchase_order)


def _apply_content_case(
    rng: random.Random, draft: Draft, case: str, suppliers: list[Supplier]
) -> None:
    invoice, purchase_order = draft.invoice, draft.purchase_order
    assert invoice is not None
    assert purchase_order is not None
    draft.hard_cases.append(case)

    if case == "missing_po":
        draft.invoice = invoice.model_copy(update={"purchase_order_reference": None})
        draft.purchase_order = None
    elif case == "unknown_po":
        draft.purchase_order = None
    elif case == "totals_mismatch":
        wrong = invoice.total + Decimal(rng.randint(100, 5000)) / 100
        draft.invoice = invoice.model_copy(update={"total": wrong})
    elif case == "wrong_iban":
        # Changing one digit always breaks the mod 97 check.
        position = rng.randrange(len(invoice.iban) - 10, len(invoice.iban))
        digit = (int(invoice.iban[position]) + rng.randint(1, 9)) % 10
        wrong_iban = f"{invoice.iban[:position]}{digit}{invoice.iban[position + 1 :]}"
        draft.invoice = invoice.model_copy(update={"iban": wrong_iban})
    elif case == "invalid_vat_number":
        # One digit short of the NL format (NL + 9 digits + B + 2 digits).
        vat_number = invoice.supplier_vat_number
        draft.invoice = invoice.model_copy(
            update={"supplier_vat_number": vat_number[:10] + vat_number[11:]}
        )
    elif case == "po_supplier_mismatch":
        other = rng.choice([s for s in suppliers if s.name != draft.supplier.name])
        draft.purchase_order = purchase_order.model_copy(
            update={"supplier_name": other.name, "supplier_vat_number": other.vat_number}
        )
    elif case == "po_amount_mismatch":
        ordered = (invoice.total * rng.randint(55, 85) / 100).quantize(CENT, ROUND_HALF_UP)
        draft.purchase_order = purchase_order.model_copy(update={"amount": ordered})
    elif case == "due_before_invoice":
        early = invoice.invoice_date - timedelta(days=rng.randint(3, 20))
        draft.invoice = invoice.model_copy(update={"due_date": early})
    else:
        raise ValueError(f"unknown content case: {case}")


def _apply_visual_case(rng: random.Random, draft: Draft, case: str) -> None:
    draft.hard_cases.append(case)
    if case == "stamp":
        draft.stamp_text = rng.choice(STAMP_TEXTS)
        return
    draft.scanned = True
    if case == "scanned_skewed":
        draft.skew_degrees = round(rng.uniform(1.5, 4.0) * rng.choice((-1, 1)), 2)


def _duplicate(original: Draft) -> Draft:
    """The same invoice sent a second time. It shares the original's purchase order."""
    return Draft(
        original.doc_type,
        original.supplier,
        invoice=original.invoice,
        hard_cases=["duplicate"],
        duplicate_of=original,
    )


def _paginated(contract: ContractTruth) -> ContractTruth:
    _, clause_pages = layout_contract(contract)
    clauses = [
        clause.model_copy(update={"page": clause_pages[clause.number]})
        for clause in contract.clauses
    ]
    return contract.model_copy(update={"clauses": clauses})


def _make_other(rng: random.Random, supplier: Supplier) -> Draft:
    """Mail that is not an invoice, credit note or contract. Some of it mentions
    invoice numbers and amounts on purpose, to make classification harder."""
    reference = f"F2026-{rng.randrange(1, 9999):04d}"
    amount = format_dutch_decimal(Decimal(rng.randint(5_000, 900_000)) / 100)
    day = format_dutch_date(FIRST_INVOICE_DATE + timedelta(days=rng.randrange(270)))
    items = rng.sample(CATALOG, 3)
    kinds: dict[str, tuple[str, list[str]]] = {
        "payment_reminder": (
            "Betalingsherinnering",
            [
                "Geachte heer, mevrouw,",
                f"Volgens onze administratie staat factuur {reference} van {day} ten bedrage van"
                f" € {amount} nog open. Wij verzoeken u het bedrag binnen 7 dagen te voldoen.",
                "Heeft u inmiddels betaald, dan kunt u deze herinnering als niet verzonden"
                " beschouwen.",
                "Met vriendelijke groet,",
            ],
        ),
        "delivery_note": (
            f"Pakbon {rng.randrange(10**6):06d}",
            [
                f"Leverdatum: {day}",
                *(f"{rng.randint(1, 40)} x {item.nl}" for item in items),
                "Goederen in goede orde ontvangen. Handtekening ontvanger: ______________",
            ],
        ),
        "order_confirmation": (
            "Orderbevestiging",
            [
                f"Hartelijk dank voor uw order PO-2026-{rng.randrange(10**5):05d}.",
                f"Wij verwachten te leveren op {day}. Het orderbedrag is € {amount} exclusief"
                " btw. U ontvangt de factuur na levering.",
                "Dit document is geen factuur.",
            ],
        ),
        "price_announcement": (
            "Aankondiging tariefwijziging 2027",
            [
                "Geachte relatie,",
                "Met ingang van 1 januari 2027 passen wij onze tarieven aan. De nieuwe"
                " tarievenlijst ontvangt u in december.",
                "Voor lopende overeenkomsten gelden de contractuele afspraken.",
                "Met vriendelijke groet,",
            ],
        ),
    }
    kind = rng.choice(sorted(kinds))
    return Draft("other", supplier, other_kind=kind, letter=kinds[kind])


def _to_truth(draft: Draft, doc_ids: dict[int, str]) -> DocumentTruth:
    doc_id = doc_ids[id(draft)]
    is_money = draft.invoice is not None
    return DocumentTruth(
        doc_id=doc_id,
        filename=f"{doc_id}.pdf",
        doc_type=draft.doc_type,
        language=draft.supplier.language if is_money else "nl",
        layout=draft.supplier.layout if is_money else PLAIN_LAYOUT,
        scanned=draft.scanned,
        skew_degrees=draft.skew_degrees,
        hard_cases=draft.hard_cases,
        expected_failures=[CONTENT_CASES[c] for c in draft.hard_cases if c in CONTENT_CASES],
        duplicate_of=doc_ids[id(draft.duplicate_of)] if draft.duplicate_of else None,
        other_kind=draft.other_kind,
        invoice=draft.invoice,
        contract=draft.contract,
    )
