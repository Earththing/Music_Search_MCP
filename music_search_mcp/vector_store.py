"""Vector store for semantic music search using ChromaDB.

Stores song embeddings (from lyrics + metadata) in a local ChromaDB
database. Uses sentence-transformers for embeddings, which automatically
uses GPU (CUDA) if available, otherwise falls back to CPU.
"""

import logging
import os
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from pathlib import Path

# Suppress noisy library output that uses the logging module.
# The noisiest output (HF warnings, safetensors LOAD REPORT, weight progress bars)
# is printed directly to stderr and is handled by redirecting stderr in
# _get_embedding_function() during model loading.
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")  # avoids fork-safety warning

_PROJECT_ROOT = Path(__file__).parent.parent
_CHROMA_DIR = _PROJECT_ROOT / "data" / "chroma_db"
_COLLECTION_NAME = "music_library"

# Default model: fast, runs on CPU, good quality for semantic search
# ~80MB download on first run, cached locally after that
DEFAULT_MODEL = "all-MiniLM-L6-v2"

# Cached embedding functions keyed by model name, so the ~8s model load
# only happens once per process rather than on every search/index call.
_embedding_cache: dict[str, SentenceTransformerEmbeddingFunction] = {}


def _get_embedding_function(model_name: str = DEFAULT_MODEL, progress_callback=None,
                            suppress_stderr: bool = True):
    """Create or return a cached embedding function using sentence-transformers.

    The model automatically uses GPU (CUDA) if available, otherwise CPU.
    Results are cached so the expensive model load only happens once.

    Args:
        model_name: Name of the sentence-transformer model.
        progress_callback: Optional callable(message) for progress reporting.
        suppress_stderr: If True, redirect stderr during model loading to suppress
            noisy library output (safetensors LOAD REPORT, HF Hub warnings).
            Set to False when stderr is needed for diagnostics (e.g. MCP server).
    """
    if model_name in _embedding_cache:
        return _embedding_cache[model_name]

    import sys
    import io

    if progress_callback:
        progress_callback(f"Loading embedding model ({model_name})...")

    if suppress_stderr:
        # Temporarily redirect stderr to suppress noisy library output
        # (safetensors LOAD REPORT, HF Hub warnings, weight loading progress bars)
        # that is printed directly to stderr rather than using the logging module.
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            ef = SentenceTransformerEmbeddingFunction(model_name=model_name)
        finally:
            sys.stderr = old_stderr
    else:
        ef = SentenceTransformerEmbeddingFunction(model_name=model_name)

    if progress_callback:
        progress_callback("Embedding model loaded.")

    _embedding_cache[model_name] = ef
    return ef


def warmup(model_name: str = DEFAULT_MODEL, suppress_stderr: bool = False):
    """Pre-load the embedding model so the first search is fast.

    Call this at server startup to avoid the ~8s model load penalty
    on the first MCP tool call.
    """
    _get_embedding_function(model_name, suppress_stderr=suppress_stderr)


def get_collection(model_name: str = DEFAULT_MODEL, progress_callback=None,
                   suppress_stderr: bool = True):
    """Get or create the ChromaDB collection for music search.

    Args:
        model_name: Sentence-transformer model name to use for embeddings.
        progress_callback: Optional callable(message) for progress reporting.
        suppress_stderr: Passed through to _get_embedding_function().

    Returns:
        ChromaDB collection ready for add/query operations.
    """
    _CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
    embedding_fn = _get_embedding_function(
        model_name, progress_callback=progress_callback, suppress_stderr=suppress_stderr,
    )

    collection = client.get_or_create_collection(
        name=_COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},  # cosine similarity for text
    )

    return collection


def build_document_text(song: dict) -> str:
    """Build the text document to embed for a song.

    Combines lyrics with metadata to create a rich searchable document.
    This allows searching by mood, theme, lyrics fragments, or metadata.

    Args:
        song: Song dict from the lyrics cache with lyrics data.

    Returns:
        A text string to be embedded.
    """
    parts = []

    # Song identity
    track_name = song.get("track_name", song.get("name", ""))
    artist_name = song.get("artist_name", song.get("artist", ""))
    if isinstance(artist_name, list):
        artist_name = ", ".join(artist_name)

    parts.append(f"Song: {track_name} by {artist_name}")

    # Album if available
    album = song.get("album", "")
    if album:
        parts.append(f"Album: {album}")

    # Instrumental flag
    if song.get("instrumental"):
        parts.append("This is an instrumental track with no vocals or lyrics.")

    # Lyrics (the main searchable content)
    lyrics = song.get("plain_lyrics", "")
    if lyrics:
        parts.append(f"Lyrics:\n{lyrics}")

    return "\n".join(parts)


def index_songs(songs: list[dict], model_name: str = DEFAULT_MODEL) -> dict:
    """Index a list of songs into the vector database.

    Each song is embedded as a combined document of lyrics + metadata.
    Songs already in the index are skipped (upsert behavior).

    Args:
        songs: List of song dicts from the lyrics cache.
        model_name: Embedding model to use.

    Returns:
        Dict with stats: total_indexed, skipped, newly_added, collection_size.
    """
    collection = get_collection(model_name)

    documents = []
    metadatas = []
    ids = []
    skipped = 0

    for song in songs:
        track_name = song.get("track_name", song.get("name", ""))
        artist_name = song.get("artist_name", song.get("artist", ""))
        if isinstance(artist_name, list):
            artist_name = ", ".join(artist_name)

        # Create a stable ID from track + artist
        song_id = f"{track_name.strip().lower()}||{artist_name.strip().lower()}"

        # Build the document text
        doc_text = build_document_text(song)

        # Skip songs with no meaningful content to embed
        if not doc_text.strip() or (not song.get("plain_lyrics") and not song.get("instrumental")):
            skipped += 1
            continue

        documents.append(doc_text)
        metadatas.append({
            "track_name": track_name,
            "artist_name": artist_name,
            "album": song.get("album", ""),
            "instrumental": str(song.get("instrumental", False)),
            "has_lyrics": str(bool(song.get("plain_lyrics"))),
            "spotify_url": song.get("spotify_url", ""),
            "lastfm_url": song.get("lastfm_url", ""),
            # Richer Spotify fields
            "popularity": song.get("popularity", 0),
            "explicit": str(song.get("explicit", False)),
            "release_date": song.get("release_date", ""),
            "duration_ms": song.get("duration_ms", 0),
        })
        ids.append(song_id)

    # Upsert in batches (ChromaDB has a batch size limit)
    batch_size = 100
    newly_added = 0
    for i in range(0, len(documents), batch_size):
        batch_docs = documents[i:i + batch_size]
        batch_meta = metadatas[i:i + batch_size]
        batch_ids = ids[i:i + batch_size]

        collection.upsert(
            documents=batch_docs,
            metadatas=batch_meta,
            ids=batch_ids,
        )
        newly_added += len(batch_docs)

    return {
        "total_processed": len(songs),
        "indexed": newly_added,
        "skipped": skipped,
        "collection_size": collection.count(),
    }


def search(query: str, n_results: int = 5, model_name: str = DEFAULT_MODEL,
           progress_callback=None, suppress_stderr: bool = True) -> list[dict]:
    """Search the music library using a natural language query.

    Args:
        query: Natural language description (e.g. "that sad song about rain").
        n_results: Maximum number of results to return.
        model_name: Embedding model to use (must match what was used for indexing).
        progress_callback: Optional callable(message) for progress reporting.
        suppress_stderr: Passed through to get_collection() / _get_embedding_function().

    Returns:
        List of result dicts with keys:
            - track_name: Song title
            - artist_name: Artist name
            - album: Album name
            - distance: Cosine distance (lower = more similar)
            - score: Similarity score 0-1 (higher = more similar)
            - document_preview: First 200 chars of the indexed document
    """
    collection = get_collection(
        model_name, progress_callback=progress_callback, suppress_stderr=suppress_stderr,
    )

    if collection.count() == 0:
        return []

    if progress_callback:
        progress_callback("Searching vector index...")

    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, collection.count()),
    )

    output = []
    for i in range(len(results["ids"][0])):
        metadata = results["metadatas"][0][i]
        distance = results["distances"][0][i]
        document = results["documents"][0][i] if results["documents"] else ""

        output.append({
            "track_name": metadata.get("track_name", ""),
            "artist_name": metadata.get("artist_name", ""),
            "album": metadata.get("album", ""),
            "distance": distance,
            "score": 1.0 - distance,  # Convert cosine distance to similarity
            "document_preview": document[:200] + "..." if len(document) > 200 else document,
            "spotify_url": metadata.get("spotify_url", ""),
            "lastfm_url": metadata.get("lastfm_url", ""),
        })

    return output


def get_index_stats(model_name: str = DEFAULT_MODEL, lightweight: bool = False) -> dict:
    """Get statistics about the vector index.

    Args:
        model_name: The model used for the collection.
        lightweight: If True, skip loading the embedding model (faster, for status checks).

    Returns:
        Dict with keys: collection_size, model_name.
    """
    if lightweight:
        # Just check the count without loading the embedding model
        _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(_CHROMA_DIR))
        try:
            collection = client.get_collection(name=_COLLECTION_NAME)
            return {
                "collection_size": collection.count(),
                "model_name": model_name,
            }
        except Exception:
            return {"collection_size": 0, "model_name": model_name}
    else:
        collection = get_collection(model_name)
        return {
            "collection_size": collection.count(),
            "model_name": model_name,
        }


def clear_index(model_name: str = DEFAULT_MODEL) -> int:
    """Clear the entire vector index.

    Returns:
        Number of entries that were in the index before clearing.
    """
    _CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(_CHROMA_DIR))

    try:
        collection = client.get_collection(name=_COLLECTION_NAME)
        count = collection.count()
        client.delete_collection(name=_COLLECTION_NAME)
        return count
    except Exception:
        return 0
