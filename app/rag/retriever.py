"""The contract search as a LangChain retriever.

LangChain chains and agents accept anything that implements `BaseRetriever`.
This class adapts our own `SearchIndex` and `EmbeddingModel` to that interface,
so the search can be plugged into LangChain without tying the rest of the
application to a vendor integration package. The answering code in
`app.rag.answer` uses the same two interfaces directly, because it needs each
passage's clause and page for citations.
"""

from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict

from app.inference.interfaces import EmbeddingModel
from app.rag.interfaces import SearchIndex


class ContractRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    index: Any  # a SearchIndex
    embedder: Any  # an EmbeddingModel
    top: int = 5

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        raise NotImplementedError("Use the async interface: `await retriever.ainvoke(query)`.")

    async def _aget_relevant_documents(self, query: str, **kwargs: Any) -> list[Document]:
        index: SearchIndex = self.index
        embedder: EmbeddingModel = self.embedder
        embedded = await embedder.embed([query])
        passages = await index.search(query, embedded.vectors[0], self.top)
        return [
            Document(
                page_content=passage.text,
                metadata={
                    "id": passage.id,
                    "document_id": passage.document_id,
                    "title": passage.title,
                    "clause_number": passage.clause_number,
                    "heading": passage.heading,
                    "page": passage.page,
                },
            )
            for passage in passages
        ]
