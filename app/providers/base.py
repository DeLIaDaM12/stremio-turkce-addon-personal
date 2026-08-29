from typing import List, Optional
from app.models import Stream, UserConfig
from app.services.metadata import MediaMeta

class BaseProvider:
    name: str = "BaseProvider"
    is_torrent: bool = False

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        """Searches for media and returns a list of Stremio Stream objects."""
        raise NotImplementedError
