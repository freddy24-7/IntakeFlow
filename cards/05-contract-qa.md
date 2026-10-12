# Card 5: Contract Q&A

Stage 5 of the PRD. Contracts are split per clause, embedded and indexed in Azure AI Search. A contract manager asks a question and gets an answer with the contract, clause and page it came from, or "Niet gevonden in de documenten". Measured on 12 October 2026 on two sets of 8 synthetic contracts with 120 labelled questions each. Reports: `reports/qa-2026-10-12.md` and `reports/qa-holdout-2026-10-12.md`.

## What was decided and why

**A clause is the unit.** It is what a contract manager asks about and what a citation points to, so it is also what gets embedded and indexed. Each passage carries the contract title (with the supplier's name), clause number, heading and start page. The title and heading are part of the embedded text, because the supplier's name is often only in the title.

**Citations are resolved by code (rule 6).** The model sees numbered passages and answers with numbers. The code looks up title, clause and page. A number that was not offered is dropped and reported, and an answer left without a valid source is replaced by "Niet gevonden in de documenten". Tests feed it invented numbers on purpose.

**Our own search interface, wrapped as a LangChain retriever.** `SearchIndex` has two methods and two implementations: Azure AI Search and an in-memory one for tests. `ContractRetriever` adapts it to LangChain's retriever interface. The ready-made LangChain integration was not used: it is a large package for about fifty lines of code, and it hides the clause and page that citations need. The search itself is a managed service with keyword, vector and re-ranking built in, and the code that remains is the index definition and the mapping to passages.

**Hybrid search, semantic ranker as a switch.** The service runs a keyword search with a Dutch analyser and a vector search and merges them. The semantic ranker re-ranks the merged list. It is off by default and was measured both ways.

**Keyless, free tier.** Azure AI Search runs on the free tier with sign-in through `az login` and key access switched off. Hybrid search, the semantic ranker's free allowance and keyless access all worked on the free tier, which the documentation did not make clear beforehand.

**Questions come from the labels.** Each question is generated from a contract's labelled facts, so the right clause, page and value are known. Every contract also gets the questions for clauses it lacks, where the right behaviour is to decline, and a few questions are about subjects no contract covers. Some questions avoid the contract's own wording, and some are in English.

**The model stays out of unrelated contracts by instruction.** The prompt says to use only passages from the contract with the supplier named in the question. There is no filter on supplier in the search itself.

## What was seen in practice

Hybrid search without the semantic ranker, which is the configured setting:

| Measure | First set (seed 42) | Hold-out set (seed 43) |
| --- | --- | --- |
| Right clause among the 5 passages | 100% (98/98) | 100% (101/101) |
| Right clause ranked first | 80.6% (79/98) | 79.2% (80/101) |
| Right answer | 100% (98/98) | 100% (101/101) |
| Citation points to the labelled clause and page | 100% (98/98) | 100% (101/101) |
| Cites a clause of another contract | 0 | 0 |
| Declined: this contract lacks the clause, others have it | 100% (14/14) | 100% (11/11) |
| Declined: no contract covers the subject | 75% (6/8) | 87.5% (7/8) |

- **These numbers are too good to mean much.** All 16 contracts are built from the same nine clause templates, in clean Dutch, and each fact sits in exactly one sentence. Real contracts have varied wording, cross-references, annexes and exceptions. What the result does show is that the pipeline is wired correctly and that the citation and declining behaviour work on easy material.
- **The failures are all one question.** "Voor welk bedrag moet {leverancier} verzekerd zijn?" The liability clause says the supplier keeps "een passende aansprakelijkheidsverzekering" and names no insured amount. In two of the three wrong cases the model presented the liability cap as the insured amount, which is a wrong answer with a correct-looking citation. In the third it said no exact amount is stated and then quoted the clause, which is arguably a fair answer that the label counts as wrong. This is the failure to watch for: a nearby clause on a related subject, answered confidently.
- **The semantic ranker made things slightly worse.** With it on, the right clause fell out of the five passages for 1 of 98 and 3 of 101 questions, all paraphrases, and those were then declined. On 72 passages there is little for a re-ranker to do. It stays off.
- **Paraphrases and English questions worked.** "Hoe lang van tevoren moeten we het contract beëindigen?" found the "opzegtermijn" clause, and English questions found Dutch clauses, 16 of 16 on both sets. The fake index in the tests, which only matches words, gets 50% and 19% on the same kinds of question, so this is the embeddings at work.
- **The citation guard never fired.** The model did not invent a single passage number in 480 real answers. The guard is tested with fakes only.
- **Rate limits again.** The first full run lost 15 of 240 questions to rate limits. Answers are not stored, so the evaluation now pauses and asks again.
- **A wrapped title cut off the supplier's name.** Found with the fakes before any Azure run: long titles wrap over two lines and the chunker took only the first. The title now runs until the first line that starts something else.
- **Two regions refused the search service.** Sweden Central was out of capacity and West Europe does not accept new customers. It runs in North Europe, the models stay in Sweden Central.
- **Through the running application:** a contract uploaded on the upload page was indexed and a question on the contract page was answered with clause and page, and a question about a penalty clause was declined.
- **Cost and latency:** about € 0.0025 per question and under a second median for the answering call. All stage 5 runs together cost about € 1.80 by token counts at list prices.

## What is still open

- **No test on contracts with varied wording.** The honest next step is contracts written differently from each other, or real public contracts, which this project does not allow.
- **"Not stated" is not the same as "not found".** The system has two outcomes. A third, "the contract mentions this but gives no figure", would have handled the insurance question correctly.
- **No filter on supplier.** Keeping answers within the right contract rests on the prompt and worked on this data. A filter in the search would make it a guarantee.
- **Answers and questions are not stored**, so the dashboard has no figures for Q&A and an evaluation cannot be re-scored without paying again.
- **Embedding token counts are estimated**, because LangChain's embeddings interface does not return usage.
- **The free search tier allows three indexes**, and all three are in use: the application's and one per evaluation set.
- **A re-indexed contract with fewer clauses would leave old passages behind.** Passage ids are derived from document and clause, so repeats replace, but nothing deletes.
