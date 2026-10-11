"""Synthetic supplier contracts in Dutch, with the facts in each clause recorded."""

import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.common.dutch import format_dutch_date_long, format_dutch_decimal
from synthetic.catalog import BUYER_NAME, Supplier
from synthetic.truth import Clause, ContractTruth

SERVICES = (
    "het vervoer van gepalletiseerde goederen binnen de Benelux",
    "de opslag en het voorraadbeheer van goederen in het distributiecentrum",
    "het periodiek onderhoud van de koel- en vriesinstallaties",
    "het ter beschikking stellen van uitzendkrachten voor magazijnwerkzaamheden",
    "de levering en het onderhoud van het warehouse management systeem",
    "de dagelijkse schoonmaak van de bedrijfshallen en kantoren",
    "de verhuur en het onderhoud van interne transportmiddelen",
    "de afhandeling van douaneformaliteiten voor in- en uitvoer",
)
COURTS = ("Rotterdam", "Amsterdam", "Den Haag", "Midden-Nederland", "Oost-Brabant")
# Clauses that some contracts leave out, so questions about them have no answer.
OPTIONAL_TOPICS = ("price_indexation", "liability", "confidentiality")


@dataclass(frozen=True)
class ClauseTemplate:
    topic: str
    heading: str
    text: str


TEMPLATES = (
    ClauseTemplate(
        "subject",
        "Onderwerp van de overeenkomst",
        "Leverancier verricht voor Opdrachtgever de volgende diensten: {service}. De diensten"
        " worden uitgevoerd op de locatie van Opdrachtgever te Rotterdam, tenzij partijen"
        " schriftelijk anders overeenkomen.\n"
        "Leverancier voert de diensten uit met de zorg die van een goed opdrachtnemer mag worden"
        " verwacht en houdt zich daarbij aan de redelijke aanwijzingen van Opdrachtgever."
        " Wijzigingen in de omvang van de dienstverlening worden vooraf schriftelijk vastgelegd.",
    ),
    ClauseTemplate(
        "term",
        "Looptijd",
        "Deze overeenkomst gaat in op {start_date} en wordt aangegaan voor een initiële looptijd"
        " van {initial_term_months} maanden. Na afloop van de initiële looptijd wordt de"
        " overeenkomst telkens stilzwijgend verlengd met een periode van {renewal_months}"
        " maanden.\n"
        "Verlenging vindt plaats onder dezelfde voorwaarden, tenzij partijen uiterlijk bij de"
        " verlenging schriftelijk andere voorwaarden zijn overeengekomen.",
    ),
    ClauseTemplate(
        "notice_period",
        "Opzegging",
        "Elk der partijen kan de overeenkomst tegen het einde van de lopende periode opzeggen"
        " met inachtneming van een opzegtermijn van {notice_period_months} maanden. Opzegging"
        " geschiedt schriftelijk per aangetekende brief.\n"
        "Een opzegging die niet tijdig is ontvangen geldt als opzegging tegen het einde van de"
        " eerstvolgende periode. Opzegging laat reeds ontstane betalingsverplichtingen onverlet.",
    ),
    ClauseTemplate(
        "price_indexation",
        "Prijzen en prijsindexatie",
        "De tarieven zijn opgenomen in bijlage 1 en luiden in euro, exclusief btw. Leverancier"
        " is gerechtigd de tarieven jaarlijks per 1 januari aan te passen op basis van de"
        " consumentenprijsindex (CPI) van het CBS, met een maximum van"
        " {indexation_cap_percent} procent per jaar.\n"
        "Leverancier deelt een tariefwijziging uiterlijk twee maanden voor de ingangsdatum"
        " schriftelijk mee. Andere prijsverhogingen zijn alleen mogelijk met schriftelijke"
        " instemming van Opdrachtgever.",
    ),
    ClauseTemplate(
        "payment",
        "Facturering en betaling",
        "Leverancier factureert maandelijks achteraf. Opdrachtgever betaalt facturen binnen"
        " {payment_term_days} dagen na factuurdatum. Op iedere factuur wordt het"
        " inkoopordernummer van Opdrachtgever vermeld.\n"
        "Bij niet-tijdige betaling is Opdrachtgever na schriftelijke aanmaning de wettelijke"
        " handelsrente verschuldigd. Opdrachtgever mag betwiste factuurbedragen opschorten"
        " tot het geschil is opgelost.",
    ),
    ClauseTemplate(
        "liability",
        "Aansprakelijkheid",
        "De aansprakelijkheid van Leverancier is per gebeurtenis beperkt tot een bedrag van"
        " € {liability_cap_eur}. Deze beperking geldt niet in geval van opzet of bewuste"
        " roekeloosheid van Leverancier.\n"
        "Leverancier is niet aansprakelijk voor indirecte schade, waaronder gevolgschade,"
        " gederfde winst en gemiste besparingen. Leverancier houdt gedurende de looptijd een"
        " passende aansprakelijkheidsverzekering in stand.",
    ),
    ClauseTemplate(
        "confidentiality",
        "Vertrouwelijkheid",
        "Partijen houden alle informatie geheim die zij in het kader van deze overeenkomst van"
        " elkaar ontvangen en waarvan zij het vertrouwelijke karakter kennen of behoren te"
        " kennen. Deze verplichting blijft gelden tot {confidentiality_years} jaar na het"
        " einde van de overeenkomst.\n"
        "De geheimhoudingsplicht geldt niet voor informatie die openbaar is of die op grond"
        " van een wettelijke verplichting moet worden verstrekt.",
    ),
    ClauseTemplate(
        "termination",
        "Tussentijdse beëindiging",
        "Elk der partijen kan de overeenkomst met onmiddellijke ingang ontbinden indien de"
        " andere partij in staat van faillissement wordt verklaard of surseance van betaling"
        " aanvraagt. Hetzelfde geldt indien een partij na schriftelijke ingebrekestelling met"
        " een hersteltermijn van {cure_period_days} dagen blijft tekortschieten.\n"
        "Bij beëindiging draagt Leverancier zorg voor een ordelijke overdracht van de"
        " werkzaamheden aan Opdrachtgever of aan een door Opdrachtgever aangewezen derde.",
    ),
    ClauseTemplate(
        "governing_law",
        "Toepasselijk recht en geschillen",
        "Op deze overeenkomst is Nederlands recht van toepassing. Geschillen die niet in"
        " onderling overleg kunnen worden opgelost, worden voorgelegd aan de bevoegde rechter"
        " van de rechtbank {court}.",
    ),
)
# Which facts each clause states.
TOPIC_FACTS = {
    "subject": ("service",),
    "term": ("start_date", "initial_term_months", "renewal_months"),
    "notice_period": ("notice_period_months",),
    "price_indexation": ("indexation_cap_percent",),
    "payment": ("payment_term_days",),
    "liability": ("liability_cap_eur",),
    "confidentiality": ("confidentiality_years",),
    "termination": ("cure_period_days",),
    "governing_law": ("court",),
}


def make_contract(rng: random.Random, supplier: Supplier, number: int) -> ContractTruth:
    """Build a contract. Clause pages are filled in by the caller after layout."""
    start = date(rng.choice((2024, 2025, 2026)), rng.randint(1, 12), 1)
    all_facts = {
        "service": rng.choice(SERVICES),
        "start_date": format_dutch_date_long(start),
        "initial_term_months": str(rng.choice((12, 24, 36, 60))),
        "renewal_months": str(rng.choice((6, 12))),
        "notice_period_months": str(rng.choice((1, 2, 3, 6))),
        "indexation_cap_percent": rng.choice(("2", "2,5", "3", "4", "5")),
        "payment_term_days": str(rng.choice((14, 30, 45, 60))),
        "liability_cap_eur": format_dutch_decimal(
            Decimal(rng.choice((50_000, 100_000, 250_000, 500_000, 1_000_000)))
        ),
        "confidentiality_years": str(rng.choice((2, 3, 5))),
        "cure_period_days": str(rng.choice((14, 30))),
        "court": rng.choice(COURTS),
    }
    # Cycle through one, none and two clauses left out, so even a small set has
    # complete contracts as well as contracts where a question has no answer.
    left_out = set(rng.sample(OPTIONAL_TOPICS, (1, 0, 2)[number % 3]))

    clauses: list[Clause] = []
    facts: dict[str, str] = {}
    for template in TEMPLATES:
        if template.topic in left_out:
            continue
        clauses.append(
            Clause(
                number=len(clauses) + 1,
                heading=template.heading,
                topic=template.topic,
                page=0,
                text=template.text.format(**all_facts),
            )
        )
        facts.update({key: all_facts[key] for key in TOPIC_FACTS[template.topic]})

    return ContractTruth(
        contract_number=f"OVK-{start.year}-{number:03d}",
        title=f"Dienstverleningsovereenkomst {BUYER_NAME} - {supplier.name}",
        supplier_name=supplier.name,
        facts=facts,
        clauses=clauses,
    )
