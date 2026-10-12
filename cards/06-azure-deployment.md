# Card 6: Azure deployment

Stage 6 of the PRD. The application itself now runs in Azure: a web application and a worker on Container Apps, with Postgres, Blob and Queue Storage, Key Vault, a container registry and monitoring, all from Bicep. Deployed on 12 October 2026 in North Europe.

## What was decided and why

**Two container apps from one image.** The web application takes uploads and serves the pages. The worker runs the workflow. Both scale to zero. The worker scales on the length of the queue, so it only runs while there are documents waiting.

**A queue between them.** An upload puts the document's id on Azure Queue Storage. The worker deletes the message when the document has a result. A message that is not deleted comes back after ten minutes, so a worker that dies in the middle of a document does not lose it. After three failed runs the document is parked as failed and the message is deleted: the document's status is the dead letter. This closes the gap from stage 4, where a document in flight was lost on restart. In Muni Mailbox this was a Redis Streams consumer group written by hand. Here it is a managed queue and about a hundred lines.

**One managed identity, no keys.** Both apps sign in to Document Intelligence, Azure OpenAI, AI Search, Blob, Queue, the registry and Key Vault with one user-assigned identity. Each role is assigned on a single resource. Account keys are switched off on storage and local authentication on the AI resources.

**One secret, in Key Vault.** The database URL with its password. The deploy script generates a new 48-character password on every deploy and passes it straight to the template. It is never printed or written to disk.

**Sign-in in front of the application.** The role picker inside the application is a demo and protects nothing, and every upload costs money. Container Apps' built-in Microsoft sign-in sits in front, limited to one account. `/health` is the only open path.

**Deploys are started by hand.** `deploy/up-app.sh` from a laptop, or the "Deploy" workflow in GitHub Actions, which signs in with OpenID Connect and has rights on this one resource group only. Nothing deploys on a push.

**The application can be removed on its own.** Everything that costs money while idle is tagged `part=app`. `deploy/down-app.sh` removes exactly that and leaves the AI resources, which cost nothing while idle.

**Purchase orders come with the image in the demo environment.** There is no accounting system to get them from, so the web application loads the synthetic ones at start.

## What was seen in practice

- **It works end to end.** Signed in with the Microsoft account, ten synthetic documents uploaded through the browser: six invoices auto-approved (five digital, one scanned), one contract indexed and searchable, three sent to review. The three were from before the purchase orders were loaded and were flagged for exactly the expected reasons: unknown purchase order, an invalid IBAN, and the duplicate of a file uploaded twice.
- **Time from upload to result: a median of 88 seconds over those ten.** Seven were uploaded at once and one worker handles one document at a time, starting from zero, so most of that is waiting in the queue and the worker's start. The steps of one document add up to about 14 seconds (stage 2). No measurement was made that separates the two.
- **Cost per document: € 0.0193** as shown on the dashboard, computed from page and token counts at list prices.
- **The Azure invoice does not confirm the cost figures yet.** Cost Management showed € 2.00 for the month on 12 October, all Azure OpenAI, against about € 15 by the project's own counts. Nearly all usage was on that day and billing data lags, and Document Intelligence was not on it at all yet. The comparison has to be repeated.
- **Regions decided by capacity, not by choice.** Sweden Central had no capacity for the Postgres server ("RegionalAllocationFailed") after the dry run had passed. The whole application moved to North Europe, next to the search service. The models and Document Intelligence stay in Sweden Central. A dry run checks the template, not capacity.
- **Deleting a Container Apps environment took about twenty minutes.** The rest of the teardown took seconds.
- **The teardown script was wrong and the failed deployment showed it.** `az resource list` does not accept a resource group together with `--tag`. Found while cleaning up the partial deployment, before it mattered.
- **The libraries logged every request with all headers.** No document content, but it buried the application's own lines and is billed per gigabyte. Turned down to warnings.
- **Worker bug found by a test.** A queue message for a document that does not exist crashed the failure handling.
- **The upload page hid earlier results.** Each upload replaced the result of the one before, which looked as if a document had been removed. Found by the first real user in the first five minutes. Results now add up.
- **Scale to zero works both ways.** The worker went to zero replicas with an empty queue and started when documents arrived.

## What is still open

- **The GitHub deploy workflow has never run.** It needs three repository variables and the current code on GitHub.
- **Cost against the real invoice**, see above.
- **Processing time in Azure, separate from queue time**, was not measured.
- **The database accepts connections from any Azure service.** It is protected by the password and TLS. A private network would be the stricter choice.
- **The image is about 1 GB**, which slows cold starts. Nothing was done to slim it.
- **Telemetry arrives in Application Insights** (the exporter reports accepted items), but nobody has looked at it there or built a view on it.
- **No alerting** beyond the budget alert.
- **One worker, one document at a time.** More replicas would cut queue time. Rate limits on the model deployments would then be the next limit.
- **Checkpoint tables and old container images are never cleaned up.**
