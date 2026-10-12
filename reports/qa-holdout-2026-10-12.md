# Contract Q&A evaluation, 2026-10-12

| Setting | Value |
| --- | --- |
| Services | azure |
| Contracts indexed | 8 (72 passages) |
| Questions | 120 |
| Passages offered per question | 5 |
| Embedding model | text-embedding-3-large |
| Answering model | gpt-4.1, prompt answer_contract_v1 |

An answer is right when it contains the labelled value. A citation is right when it points to the labelled clause of the contract the question is about. For a question about a clause the contract does not have, the right behaviour is to decline.

## Hybrid search

### Search

| Measure | Value |
| --- | --- |
| Right clause among the 5 passages | 100.0% (101/101) |
| Right clause ranked first | 79.2% (80/101) |

### Questions the contract answers

| Outcome | Questions |
| --- | --- |
| Right answer | 100.0% (101/101) |
| Answered with another value | 0.0% (0/101) |
| Declined although the answer is there | 0.0% (0/101) |

### Citations on answered questions

| Measure | Value |
| --- | --- |
| Cites the labelled clause | 100.0% (101/101) |
| Cited page equals the labelled page | 100.0% (101/101) |
| Cites a clause of another contract | 0.0% (0/101) |
| Passage numbers that were never offered (dropped by the code) | 0 |

### Questions without an answer in the contract

| Kind | Rightly declined |
| --- | --- |
| This contract has no such clause, others do | 100.0% (11/11) |
| No contract covers the subject | 87.5% (7/8) |

| Answered although it should decline | Cited | Answer given |
| --- | --- | --- |
| doc-0174-insurance_amount-near | doc-0174 art. 6 | Het contract vermeldt geen exact verzekerd bedrag, maar stelt dat de Leverancier gedurende de looptijd een passende aansprakelijkheidsverzekering in stand moet houden. De aansprakelijkheid van de Leverancier is per gebeurtenis beperkt tot € 500.000,00. |

### By phrasing (questions the contract answers)

| Phrasing | Right clause in top 5 | Right answer |
| --- | --- | --- |
| near | 100.0% (56/56) | 100.0% (56/56) |
| paraphrase | 100.0% (29/29) | 100.0% (29/29) |
| english | 100.0% (16/16) | 100.0% (16/16) |

### Latency and cost

| Measure | Value |
| --- | --- |
| Answering call, median | 713 ms |
| Answering call, 95th percentile | 1,385 ms |
| Cost per question | € 0.0025 |
| Cost of this run | € 0.29 |

## Hybrid search with semantic ranker

### Search

| Measure | Value |
| --- | --- |
| Right clause among the 5 passages | 97.0% (98/101) |
| Right clause ranked first | 78.2% (79/101) |

### Questions the contract answers

| Outcome | Questions |
| --- | --- |
| Right answer | 97.0% (98/101) |
| Answered with another value | 0.0% (0/101) |
| Declined although the answer is there | 3.0% (3/101) |

### Citations on answered questions

| Measure | Value |
| --- | --- |
| Cites the labelled clause | 100.0% (98/98) |
| Cited page equals the labelled page | 100.0% (98/98) |
| Cites a clause of another contract | 0.0% (0/98) |
| Passage numbers that were never offered (dropped by the code) | 0 |

### Questions without an answer in the contract

| Kind | Rightly declined |
| --- | --- |
| This contract has no such clause, others do | 100.0% (11/11) |
| No contract covers the subject | 87.5% (7/8) |

| Answered although it should decline | Cited | Answer given |
| --- | --- | --- |
| doc-0174-insurance_amount-near | doc-0174 art. 6 | Schoonmaakbedrijf van Wessex moet verzekerd zijn voor een passend bedrag, maar het exacte bedrag wordt niet genoemd. Wel is de aansprakelijkheid per gebeurtenis beperkt tot € 500.000,00. |

### By phrasing (questions the contract answers)

| Phrasing | Right clause in top 5 | Right answer |
| --- | --- | --- |
| near | 100.0% (56/56) | 100.0% (56/56) |
| paraphrase | 89.7% (26/29) | 89.7% (26/29) |
| english | 100.0% (16/16) | 100.0% (16/16) |

### Latency and cost

| Measure | Value |
| --- | --- |
| Answering call, median | 894 ms |
| Answering call, 95th percentile | 4,659 ms |
| Cost per question | € 0.0025 |
| Cost of this run | € 0.30 |

Cost at the unit prices of 2026-10-11. Embedding tokens are estimated, model tokens are as reported. The search service is on the free tier.

