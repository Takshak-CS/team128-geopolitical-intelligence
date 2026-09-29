"""
cluster_quality.py — validation metrics for the production KMeans clustering
============================================================================
Called from preprocess._cluster_events() right after the production fit,
with the exact scaled feature matrix and labels that production used. It
never changes the clustering — it only measures it:

  - silhouette       how tight / well separated the clusters are (-1..+1)
  - silhouette_null  same score with the labels randomly shuffled (chance)
  - stability_ari    agreement between refits under different random seeds
  - k_sweep/best_k   silhouette for k = 2..6 with the same features/params

Never raises: on any problem the metrics are None and "reason" says why.
"""

import itertools

import numpy as np

_MAX_ROWS = 2000
_SEED = 42


def _label_for(sil):
    if sil is None:
        return "not available"
    if sil >= 0.50:
        return "strong structure"
    if sil >= 0.25:
        return "reasonable structure"
    if sil >= 0.10:
        return "weak structure"
    return "little or no structure"


def compute_cluster_quality(X, labels, kmeans_params) -> dict:
    labels_arr = np.asarray(labels) if labels is not None else np.array([])
    n = int(labels_arr.shape[0])
    k = int(len(np.unique(labels_arr))) if n else 0
    result = {
        "n_events": n,
        "k": k,
        "metric": "euclidean",
        "silhouette": None,
        "silhouette_null": None,
        "stability_ari": None,
        "k_sweep": [],
        "best_k": None,
        "label": "not available",
        "weak": True,
        "reason": None,
    }
    try:
        from sklearn.cluster import KMeans
        from sklearn.metrics import adjusted_rand_score, silhouette_score

        if hasattr(X, "toarray"):          # sparse -> dense (feature count is tiny)
            X = X.toarray()
        X = np.asarray(X, dtype=float)
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        if X.shape[0] != n:
            result["reason"] = "feature/label length mismatch"
            return result
        if n < 10:
            result["reason"] = f"too few events ({n}) to validate"
            return result
        if k < 2:
            result["reason"] = "fewer than 2 clusters"
            return result
        if k >= n:
            result["reason"] = "k >= number of events"
            return result
        if not np.all(np.isfinite(X)):
            X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        if np.all(np.ptp(X, axis=0) == 0):
            result["reason"] = "all features are constant"
            return result

        rng = np.random.RandomState(_SEED)
        sample_size = _MAX_ROWS if n > _MAX_ROWS else None

        # Production silhouette (sampled above 2000 rows).
        sil = float(silhouette_score(X, labels_arr, sample_size=sample_size,
                                     random_state=_SEED))
        result["silhouette"] = sil

        # Chance baseline: shuffled labels keep the same cluster sizes.
        nulls = [
            silhouette_score(X, rng.permutation(labels_arr), sample_size=sample_size,
                             random_state=_SEED)
            for _ in range(5)
        ]
        result["silhouette_null"] = float(np.mean(nulls))

        # For n > 2000 the stability check and k-sweep run on a fixed random
        # subsample of 2000 rows (random_state=42) to keep each run fast.
        if n > _MAX_ROWS:
            idx = np.random.RandomState(_SEED).choice(n, _MAX_ROWS, replace=False)
            Xs = X[idx]
        else:
            Xs = X
        ns = Xs.shape[0]

        params = {p: v for p, v in (kmeans_params or {}).items()
                  if p not in ("n_clusters", "random_state")}

        # Stability: refit with 5 different seeds, mean pairwise ARI.
        fits = [
            KMeans(n_clusters=k, random_state=seed, **params).fit_predict(Xs)
            for seed in (0, 1, 2, 3, 4)
        ]
        aris = [adjusted_rand_score(a, b) for a, b in itertools.combinations(fits, 2)]
        result["stability_ari"] = float(np.mean(aris))

        # k-sweep with the same features/params.
        sweep = []
        for kk in range(2, min(6, ns - 1) + 1):
            try:
                lab = KMeans(n_clusters=kk, random_state=_SEED, **params).fit_predict(Xs)
                if len(np.unique(lab)) < 2:
                    continue
                s = silhouette_score(Xs, lab)
                sweep.append({"k": kk, "silhouette": float(s)})
            except Exception:
                continue
        result["k_sweep"] = sweep
        if sweep:
            result["best_k"] = int(max(sweep, key=lambda d: d["silhouette"])["k"])

        result["label"] = _label_for(sil)
        result["weak"] = bool(sil < 0.10 or sil <= result["silhouette_null"])
        return result
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"[:200]
        print(f"[cluster_quality] failed: {msg}")
        result.update({"silhouette": None, "silhouette_null": None,
                       "stability_ari": None, "k_sweep": [], "best_k": None,
                       "label": "not available", "weak": True, "reason": msg})
        return result
