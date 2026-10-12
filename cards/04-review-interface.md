# Card 4: Review interface

Stage 4 of the PRD. Server-rendered pages with Jinja2 and HTMX: role picker, upload, review queue, review page and dashboard. Interface text is Dutch.

## What was decided and why

**Corrections live in their own record.** A review stores only the fields the reviewer changed, next to the id of the extraction it was based on. The extraction is never written to again, so "approved unchanged" is one boolean and the model's original answer stays available for measuring (rule 5). A test corrects an IBAN and then checks the stored extraction still holds the wrong one.

**The reviewer is in charge.** Corrected values go through the same checks as the model's values. Failures are shown and recorded on the review, but they do not block an approval. The alternative, blocking until every check passes, would put the system above the person on cases the system cannot judge, such as an invoice that really has no purchase order.

**Reviewer input uses the pipeline's normalisation.** A clerk can type `1.234,56` or `31-12-2026`. It goes through the same code that reads the model's output, so there is one definition of a valid amount or date.

**Approval still goes through the one ERP path.** The review sets the status to approved and calls the same gateway function as the automatic route. An invoice that is already booked is refused there with a message for the reviewer.

**Pages of the document are shown as images.** The first version embedded the PDF. The browser test showed an empty frame in headless Chromium, so each page is now rendered to PNG on the server. It works without a PDF viewer and can be checked in a test.

**HTMX for three small things:** the queue refreshes itself while documents are being processed, the upload form shows its result without a page reload, and "Controleren" validates the form without saving. Everything else is plain forms and redirects. Compared with Muni Mailbox, where the same stack was used, nothing new was needed here.

**The dashboard counts uploads only.** Documents registered by the evaluation scripts are marked as such and left out, so the dashboard shows use of the application, not test runs. Field accuracy is the exception and is labelled as coming from the evaluation.

**Demo role picker, not authentication.** A cookie holds the chosen role. Anyone can pick any role.

## What was seen in practice

- **First run of the whole workflow against Azure.** Two synthetic invoices uploaded through the upload page of the running application on 12 October 2026: the clean one was auto-approved and booked, the one with the wrong IBAN appeared in the queue with "IBAN is ongeldig (controlegetal)". Before this, the graph had only run on fakes.
- **Time to result was about a minute** for those two (the dashboard showed a median of 63.9 seconds). That is far above the sum of the step latencies measured in stage 2 (about 14 seconds). Two documents on a freshly started application is not a measurement of normal operation, but it is the only end-to-end timing there is so far.
- **Old test data showed up on the dashboard.** Forty documents from the very first harness run in stage 2, made before evaluation runs were kept apart, counted as uploads. They were re-labelled in the local database. A fresh database does not have this problem.
- **The rule 3 source check was too broad.** It fired on the Dutch label for the auto-approved status and on the dashboard reading it. It now looks for places that set a status, which is what the rule is about.
- **Tests:** 223 unit and integration tests and one browser test pass. The browser test starts the application with fake services on its own database and goes through upload, queue, review with a correction, approval and the dashboard.

## What is still open

- **Line items cannot be edited.** A reviewer can correct the eleven fields, not the lines. An invoice whose lines were misread can be approved with the totals check still failing, or rejected.
- **No protection against two reviewers on one document** beyond "a document is reviewed once": the second one gets a message.
- **No CSRF protection and no real sign-in.** Acceptable for a local demo, not for anything deployed with real access. Stage 6 has Entra ID as an option.
- **Documents in flight are lost on a restart.** Processing runs as a task inside the web process. A document that was being processed when the application stops stays "in verwerking" and is not picked up again. The queue in stage 6 is meant to fix this.
- **Failed documents are listed in the queue but cannot be retried from the page.**
- **The rule 3 source check can be evaded** by putting the status in a variable first. It catches the direct ways of setting it.
- **The interface was checked by tests and by reading screenshots**, not by a person using it.
