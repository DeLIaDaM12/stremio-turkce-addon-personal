 (cd "$(git rev-parse --show-toplevel)" && printf '%s' 'diff --git a/app/providers/utils.py b/app/providers/utils.py
new file mode 100644
index 0000000000000000000000000000000000000000..b47b838d78ac9b048fb35146f7498dc18b189639
--- /dev/null
+++ b/app/providers/utils.py
@@ -0,0 +1,75 @@
+"""Shared safeguards for pages returned by streaming-provider web sites."""
+
+import re
+import unicodedata
+from typing import Optional
+
+import httpx
+
+from app.services.metadata import MediaMeta
+
+
+def is_cloudflare_challenge(response: httpx.Response) -> bool:
+    """Return whether *response* is a Cloudflare interstitial rather than content.
+
+    Cloudflare frequently serves its challenge with status 200.  Treating that
+    document as a movie page makes the providers select arbitrary script URLs
+    as players, so status code alone is not a sufficient check.
+    """
+    if response.status_code in (403, 429, 503):
+        return True
+    headers = response.headers
+    if headers.get("cf-mitigated", "").casefold() == "challenge":
+        return True
+    body = response.text[:20_000].casefold()
+    markers = (
+        "just a moment...",
+        "cf-chl-",
+        "challenge-platform",
+        "attention required! | cloudflare",
+        "/cdn-cgi/challenge-platform/",
+    )
+    return any(marker in body for marker in markers)
+
+
+def _normalise_title(value: str) -> str:
+    value = unicodedata.normalize("NFKD", value.casefold())
+    value = "".join(char for char in value if not unicodedata.combining(char))
+    return re.sub(r"[^a-z0-9]+", " ", value).strip()
+
+
+def movie_match_score(label: str, meta: MediaMeta) -> Optional[int]:
+    """Score a search-result label for a movie, or reject an unrelated title.
+
+    A year is only a tie breaker: using it as a match previously allowed the
+    first unrelated release from the same year to be selected.
+    """
+    candidate = _normalise_title(label)
+    if not candidate:
+        return None
+    candidate_tokens = set(candidate.split())
+    best: Optional[int] = None
+    for title in (meta.original_title, meta.turkish_title):
+        if not title:
+            continue
+        expected = _normalise_title(title)
+        if not expected:
+            continue
+        if candidate == expected:
+            score = 1_000
+        elif expected in candidate or candidate in expected:
+            score = 800
+        else:
+            expected_tokens = set(expected.split())
+            overlap = len(candidate_tokens & expected_tokens)
+            # Require a meaningful title overlap, not merely a common word.
+            if overlap < 2 and not (len(expected_tokens) == 1 and overlap == 1):
+                continue
+            ratio = overlap / len(expected_tokens)
+            if ratio < 0.6:
+                continue
+            score = int(ratio * 600)
+        if meta.year and str(meta.year) in label:
+            score += 25
+        best = max(best or score, score)
+    return best
' | git apply --3way)
