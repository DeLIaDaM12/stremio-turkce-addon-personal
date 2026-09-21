 (cd "$(git rev-parse --show-toplevel)" && printf '%s' 'diff --git a/tests/test_provider_utils.py b/tests/test_provider_utils.py
new file mode 100644
index 0000000000000000000000000000000000000000..43183d27b304c997ff191c76e5c89f0b381c4b4f
--- /dev/null
+++ b/tests/test_provider_utils.py
@@ -0,0 +1,26 @@
+import unittest
+
+import httpx
+
+from app.providers.utils import is_cloudflare_challenge, movie_match_score
+from app.services.metadata import MediaMeta
+
+
+class ProviderUtilsTests(unittest.TestCase):
+    def setUp(self):
+        self.meta = MediaMeta(
+            imdb_id="tt0000001", media_type="movie", original_title="The Batman",
+            turkish_title="Batman", year=2022,
+        )
+
+    def test_cloudflare_200_interstitial_is_not_usable_content(self):
+        response = httpx.Response(200, text="<title>Just a moment...</title> cf-chl-opt")
+        self.assertTrue(is_cloudflare_challenge(response))
+
+    def test_normal_page_is_not_a_cloudflare_challenge(self):
+        response = httpx.Response(200, text="<html><title>The Batman</title></html>")
+        self.assertFalse(is_cloudflare_challenge(response))
+
+    def test_movie_selection_rejects_same_year_with_a_different_title(self):
+        self.assertIsNone(movie_match_score("Everything Everywhere All at Once (2022)", self.meta))
+        self.assertGreater(movie_match_score("The Batman (2022) izle", self.meta) or 0, 0)
' | git apply --3way)
