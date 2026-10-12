"""Labelled questions about the synthetic contracts, for the Q&A evaluation.

Every question is built from the contract's own labelled facts, so the right
clause, page and value are known. A contract that leaves a clause out gets the
same question anyway: there the right behaviour is to decline. A few questions
are about subjects no contract covers.

Each subject has a question close to the contract's wording. Some also have a
paraphrase that avoids the contract's key word, and some an English version.
"""

from typing import Literal

from pydantic import BaseModel

from synthetic.truth import DocumentTruth


class QuestionTruth(BaseModel):
    question_id: str
    question: str
    phrasing: Literal["near", "paraphrase", "english"]
    doc_id: str | None  # the contract asked about, None for subjects no contract covers
    topic: str
    answerable: bool
    clause_number: int | None = None
    page: int | None = None
    # The answer counts as right when it contains one of these.
    accepted: list[str] = []


# topic -> (fact that holds the value, questions by phrasing with {s} for the supplier)
TOPICS: dict[str, tuple[str, dict[str, str]]] = {
    "notice_period": (
        "notice_period_months",
        {
            "near": "Wat is de opzegtermijn in het contract met {s}?",
            "paraphrase": "Hoe lang van tevoren moeten we het contract met {s} beëindigen?",
            "english": "What is the notice period in the contract with {s}?",
        },
    ),
    "term": (
        "initial_term_months",
        {"near": "Wat is de initiële looptijd van het contract met {s}?"},
    ),
    "price_indexation": (
        "indexation_cap_percent",
        {
            "near": "Wat is het maximum van de jaarlijkse prijsindexatie in het contract met {s}?",
            "paraphrase": "Met hoeveel procent mag {s} de tarieven per jaar hoogstens verhogen?",
        },
    ),
    "payment": (
        "payment_term_days",
        {
            "near": "Binnen hoeveel dagen betaalt Opdrachtgever de facturen van {s}?",
            "paraphrase": "Hoeveel tijd hebben we om een rekening van {s} te voldoen?",
        },
    ),
    "liability": (
        "liability_cap_eur",
        {
            "near": "Tot welk bedrag is de aansprakelijkheid van {s} per gebeurtenis beperkt?",
            "paraphrase": "Wat kunnen we maximaal op {s} verhalen als er iets misgaat?",
        },
    ),
    "confidentiality": (
        "confidentiality_years",
        {"near": "Hoeveel jaar na het einde van het contract met {s} geldt de geheimhouding nog?"},
    ),
    "termination": (
        "cure_period_days",
        {"near": "Welke hersteltermijn geldt bij een ingebrekestelling in het contract met {s}?"},
    ),
    "governing_law": (
        "court",
        {
            "near": "Aan welke rechtbank worden geschillen met {s} voorgelegd?",
            "english": "Which court handles disputes under the contract with {s}?",
        },
    ),
}
# Subjects none of the contracts has a clause on.
UNCOVERED = (
    ("penalty", "Welke boete geldt bij te late levering door {s}?"),
    ("insurance_amount", "Voor welk bedrag moet {s} verzekerd zijn?"),
)


def accepted_values(fact: str, value: str) -> list[str]:
    """Forms of the labelled value that count as the same answer."""
    if fact == "liability_cap_eur":  # printed as 250.000,00
        whole = value.split(",")[0]
        return [value, whole, whole.replace(".", ""), whole.replace(".", ",")]
    if fact == "indexation_cap_percent" and "," in value:  # printed as 2,5
        return [value, value.replace(",", ".")]
    return [value]


def make_questions(documents: list[DocumentTruth]) -> list[QuestionTruth]:
    questions: list[QuestionTruth] = []
    contracts = [doc for doc in documents if doc.contract is not None]
    for doc in contracts:
        assert doc.contract is not None
        supplier = doc.contract.supplier_name
        clauses = {clause.topic: clause for clause in doc.contract.clauses}
        for topic, (fact, phrasings) in TOPICS.items():
            clause = clauses.get(topic)
            for phrasing, template in phrasings.items():
                questions.append(
                    QuestionTruth(
                        question_id=f"{doc.doc_id}-{topic}-{phrasing}",
                        question=template.format(s=supplier),
                        phrasing=phrasing,
                        doc_id=doc.doc_id,
                        topic=topic,
                        answerable=clause is not None,
                        clause_number=clause.number if clause else None,
                        page=clause.page if clause else None,
                        accepted=(
                            accepted_values(fact, doc.contract.facts[fact]) if clause else []
                        ),
                    )
                )
    # One uncovered subject per contract, alternating, so they stay a minority.
    for index, doc in enumerate(contracts):
        assert doc.contract is not None
        topic, template = UNCOVERED[index % len(UNCOVERED)]
        questions.append(
            QuestionTruth(
                question_id=f"{doc.doc_id}-{topic}-near",
                question=template.format(s=doc.contract.supplier_name),
                phrasing="near",
                doc_id=None,
                topic=topic,
                answerable=False,
            )
        )
    return questions
