"""Gemini embeddings, one funnel (test-patchable)."""

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.config import EMBED_DIM, EMBED_MODEL, get_api_key


def _embedder() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=EMBED_MODEL,
        google_api_key=get_api_key(),
        output_dimensionality=EMBED_DIM,
    )


async def embed_texts(texts: list[str]) -> list[list[float]]:
    return await _embedder().aembed_documents(texts)
