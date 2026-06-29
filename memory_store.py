import os
import json
import math
import sqlite3
import string
import urllib.request

DB_DIR = ".proximity_swarm"
DB_PATH = os.path.join(DB_DIR, "memory.db")
DEFAULT_EMBED_MODEL = "nomic-embed-text"


def get_db_connection():
    """Returns a connection to the SQLite database, initializing directory if needed."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initializes the database schema."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS episodic_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal TEXT NOT NULL,
            role TEXT,
            status TEXT,
            steps TEXT,
            errors TEXT,
            deliverable_summary TEXT,
            reflection TEXT,
            embedding TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def tokenize(text):
    """Tokenize and preprocess text into a bag of lowercase words."""
    if not text:
        return []
    translator = str.maketrans('', '', string.punctuation)
    clean_text = text.translate(translator).lower()
    return [word for word in clean_text.split() if len(word) > 2]


def compute_tfidf_similarities(query, db_goals):
    """Computes TF-IDF Cosine Similarity of a query against multiple goal documents."""
    if not db_goals:
        return []
    
    corpus = list(db_goals) + [query]
    all_tokens = [tokenize(doc) for doc in corpus]
    vocab = set()
    for t in all_tokens:
        vocab.update(t)
    vocab = list(vocab)
    if not vocab:
        return [0.0] * len(db_goals)
    
    N = len(all_tokens)
    idf = {}
    for term in vocab:
        df = sum(1 for t in all_tokens if term in t)
        idf[term] = math.log((1 + N) / (1 + df)) + 1
        
    def get_vector(tokens):
        return [tokens.count(term) * idf[term] for term in vocab]
        
    query_vec = get_vector(all_tokens[-1])
    query_mag = math.sqrt(sum(x * x for x in query_vec))
    if query_mag == 0:
        return [0.0] * len(db_goals)
        
    scores = []
    for i in range(len(db_goals)):
        vec = get_vector(all_tokens[i])
        mag = math.sqrt(sum(x * x for x in vec))
        if mag == 0:
            scores.append(0.0)
            continue
        dot = sum(a * b for a, b in zip(vec, query_vec))
        scores.append(dot / (mag * query_mag))
        
    return scores


def is_ollama_running():
    """Checks if the local Ollama instance is running."""
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.0) as response:
            return response.status == 200
    except Exception:
        return False


def get_embedding(text, model=DEFAULT_EMBED_MODEL):
    """Calls Ollama's embeddings API to get the semantic vector for a text."""
    if not is_ollama_running():
        return None
    
    url = "http://localhost:11434/api/embeddings"
    headers = {"Content-Type": "application/json"}
    body = {
        "model": model,
        "prompt": text
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data.get("embedding")
    except Exception as e:
        # Fallback to older model check or log error
        # Let's try /api/embed if embeddings failed, just in case they use newer Ollama
        try:
            url_embed = "http://localhost:11434/api/embed"
            body_embed = {
                "model": model,
                "input": text
            }
            req_embed = urllib.request.Request(
                url_embed,
                data=json.dumps(body_embed).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req_embed, timeout=10) as response_embed:
                res_data_embed = json.loads(response_embed.read().decode("utf-8"))
                embeddings = res_data_embed.get("embeddings")
                if embeddings and len(embeddings) > 0:
                    return embeddings[0]
        except Exception:
            pass
        return None


def cosine_similarity(vec1, vec2):
    """Computes the cosine similarity of two vectors."""
    if not vec1 or not vec2:
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2))
    mag1 = math.sqrt(sum(a * a for a in vec1))
    mag2 = math.sqrt(sum(b * b for b in vec2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


def save_episode(goal, role, status, steps, errors, deliverable_summary, reflection, model=DEFAULT_EMBED_MODEL, max_episodes=500):
    """Saves a new execution episode into the database, generating embeddings, and enforces memory limit."""
    init_db()
    
    # Generate embedding
    embedding = get_embedding(goal, model=model)
    embedding_str = json.dumps(embedding) if embedding else None
    
    # Serialize JSON fields
    steps_str = json.dumps(steps)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO episodic_memories (goal, role, status, steps, errors, deliverable_summary, reflection, embedding)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (goal, role, status, steps_str, errors, deliverable_summary, reflection, embedding_str))
    conn.commit()
    conn.close()
    
    enforce_memory_limit(max_episodes)


def enforce_memory_limit(max_episodes=500):
    """Deletes the oldest episodes if the total count exceeds max_episodes."""
    if max_episodes <= 0:
        return
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM episodic_memories")
    count = cursor.fetchone()[0]
    
    if count > max_episodes:
        to_delete = count - max_episodes
        # Delete the oldest N rows
        cursor.execute(f"""
            DELETE FROM episodic_memories 
            WHERE id IN (
                SELECT id FROM episodic_memories 
                ORDER BY id ASC 
                LIMIT ?
            )
        """, (to_delete,))
        conn.commit()
    conn.close()


def query_similar_episodes(query_goal, top_k=2, model=DEFAULT_EMBED_MODEL):
    """Queries similar past episodes using vector embeddings, falling back to TF-IDF."""
    init_db()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, goal, role, status, steps, errors, deliverable_summary, reflection, embedding FROM episodic_memories")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return []
    
    results = []
    query_embedding = get_embedding(query_goal, model=model)
    
    # Check if we can do vector search
    has_vectors = False
    if query_embedding is not None:
        # Check if any database rows have valid vector embeddings
        row_vectors = []
        for r in rows:
            emb_str = r["embedding"]
            if emb_str:
                try:
                    emb = json.loads(emb_str)
                    if emb:
                        row_vectors.append((r, emb))
                except Exception:
                    pass
        if len(row_vectors) > 0:
            has_vectors = True
            for r, emb in row_vectors:
                sim = cosine_similarity(query_embedding, emb)
                results.append((r, sim))
    
    if not has_vectors:
        # Fallback to TF-IDF
        db_goals = [r["goal"] for r in rows]
        scores = compute_tfidf_similarities(query_goal, db_goals)
        for i, r in enumerate(rows):
            results.append((r, scores[i]))
            
    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)
    
    # Format return list
    top_matches = []
    for r, score in results[:top_k]:
        try:
            steps_list = json.loads(r["steps"]) if r["steps"] else []
        except Exception:
            steps_list = []
            
        top_matches.append({
            "id": r["id"],
            "goal": r["goal"],
            "role": r["role"],
            "status": r["status"],
            "steps": steps_list,
            "errors": r["errors"],
            "deliverable_summary": r["deliverable_summary"],
            "reflection": r["reflection"],
            "score": score
        })
        
    return top_matches


def clean_memories():
    """Purges the episodic memories database."""
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM episodic_memories")
    conn.commit()
    conn.close()
