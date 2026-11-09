import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


def cv_similarity(texts, cv, method="tfidf"):
    docs = list(texts) + [cv]
    if method == "embed":
        from sentence_transformers import SentenceTransformer
        e = SentenceTransformer("all-MiniLM-L6-v2").encode(docs, normalize_embeddings=True)
        return np.asarray(e[:-1] @ e[-1])
    X = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True).fit_transform(docs)
    return (X[:-1] @ X[-1].T).toarray().ravel()
