"""Azure AI Search behind the SearchIndex interface: hybrid search over contract clauses.

Hybrid means the service runs a keyword search (with a Dutch analyser) and a
vector search and merges the two rankings. The semantic ranker can re-rank the
merged list. It is a switch, so its effect can be measured.
"""

from collections.abc import Sequence
from typing import Any

from azure.identity.aio import DefaultAzureCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

from app.rag.interfaces import Passage

SEMANTIC_CONFIGURATION = "clauses"
VECTOR_PROFILE = "clauses-hnsw"
DUTCH_ANALYSER = "nl.microsoft"
PASSAGE_FIELDS = ("id", "document_id", "title", "clause_number", "heading", "page", "text")


def index_definition(name: str, dimensions: int) -> SearchIndex:
    return SearchIndex(
        name=name,
        fields=[
            SimpleField(name="id", type="Edm.String", key=True),
            SimpleField(name="document_id", type="Edm.String", filterable=True),
            SearchableField(name="title", analyzer_name=DUTCH_ANALYSER),
            SimpleField(name="clause_number", type="Edm.Int32"),
            SearchableField(name="heading", analyzer_name=DUTCH_ANALYSER),
            SimpleField(name="page", type="Edm.Int32"),
            SearchableField(name="text", analyzer_name=DUTCH_ANALYSER),
            SearchField(
                name="vector",
                type="Collection(Edm.Single)",
                searchable=True,
                vector_search_dimensions=dimensions,
                vector_search_profile_name=VECTOR_PROFILE,
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
            profiles=[
                VectorSearchProfile(name=VECTOR_PROFILE, algorithm_configuration_name="hnsw")
            ],
        ),
        semantic_search=SemanticSearch(
            configurations=[
                SemanticConfiguration(
                    name=SEMANTIC_CONFIGURATION,
                    prioritized_fields=SemanticPrioritizedFields(
                        title_field=SemanticField(field_name="title"),
                        content_fields=[SemanticField(field_name="text")],
                        keywords_fields=[SemanticField(field_name="heading")],
                    ),
                )
            ]
        ),
    )


def to_document(passage: Passage, vector: list[float]) -> dict[str, Any]:
    return {**{name: getattr(passage, name) for name in PASSAGE_FIELDS}, "vector": vector}


def to_passage(document: dict[str, Any]) -> Passage:
    return Passage(**{name: document[name] for name in PASSAGE_FIELDS})


class AzureSearchIndex:
    def __init__(
        self, client: Any, index_client: Any, *, name: str, dimensions: int, semantic: bool
    ) -> None:
        self._client = client
        self._index_client = index_client
        self._name = name
        self._dimensions = dimensions
        self._semantic = semantic
        self._ready = False
        self._credential: Any = None

    @classmethod
    def connect(
        cls, *, endpoint: str, name: str, dimensions: int, semantic: bool
    ) -> "AzureSearchIndex":
        """Keyless sign-in, like the other Azure services."""
        credential = DefaultAzureCredential()
        index = cls(
            SearchClient(endpoint, name, credential),
            SearchIndexClient(endpoint, credential),
            name=name,
            dimensions=dimensions,
            semantic=semantic,
        )
        index._credential = credential
        return index

    async def _ensure_index(self) -> None:
        if not self._ready:
            await self._index_client.create_or_update_index(
                index_definition(self._name, self._dimensions)
            )
            self._ready = True

    async def upsert(self, passages: Sequence[Passage], vectors: Sequence[list[float]]) -> None:
        await self._ensure_index()
        documents = [
            to_document(passage, vector) for passage, vector in zip(passages, vectors, strict=True)
        ]
        if documents:
            await self._client.merge_or_upload_documents(documents)

    async def search(self, query: str, vector: list[float], top: int) -> list[Passage]:
        options: dict[str, Any] = {}
        if self._semantic:
            options = {
                "query_type": "semantic",
                "semantic_configuration_name": SEMANTIC_CONFIGURATION,
            }
        results = await self._client.search(
            search_text=query,
            vector_queries=[
                VectorizedQuery(vector=vector, k_nearest_neighbors=max(top, 10), fields="vector")
            ],
            select=list(PASSAGE_FIELDS),
            top=top,
            **options,
        )
        return [to_passage(document) async for document in results]

    async def close(self) -> None:
        await self._client.close()
        await self._index_client.close()
        if self._credential is not None:
            await self._credential.close()
