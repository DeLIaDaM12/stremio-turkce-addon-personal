import re
from typing import Optional, Dict, Any

class BaseExtractor:
    name: str = "GenericExtractor"

    @staticmethod
    def unpack_packer(packed_js: str) -> str:
        """Unpacks Javascript packed with Dean Edwards p,a,c,k,e,d unpacker."""
        try:
            match = re.search(r"}\s*\('(.*)',\s*(\d+),\s*(\d+),\s*'(.*)'\.split\('\|'\)", packed_js)
            if not match:
                match = re.search(r"}\s*\(\"(.*)\",\s*(\d+),\s*(\d+),\s*\"(.*)\"\.split\('\|'\)", packed_js)
            if not match:
                return packed_js

            payload, radix, count, symtab = match.groups()
            radix = int(radix)
            count = int(count)
            symtab = symtab.split('|')

            def unbase(val: str, rad: int) -> int:
                alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                res = 0
                for char in val:
                    res = res * rad + alphabet.index(char)
                return res

            def replace_word(match):
                word = match.group(0)
                try:
                    idx = unbase(word, radix)
                    if idx < len(symtab) and symtab[idx]:
                        return symtab[idx]
                except Exception:
                    pass
                return word

            unpacked = re.sub(r'\b\w+\b', replace_word, payload)
            return unpacked
        except Exception:
            return packed_js

    async def extract(self, embed_url: str, referer: Optional[str] = None) -> Optional[Dict[str, Any]]:
        raise NotImplementedError
