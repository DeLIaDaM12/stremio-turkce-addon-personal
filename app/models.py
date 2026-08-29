from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field

class BehaviorHints(BaseModel):
    notWebReady: Optional[bool] = None
    bingeGroup: Optional[str] = None
    proxyHeaders: Optional[Dict[str, Dict[str, str]]] = None

class Subtitle(BaseModel):
    id: str
    url: str
    lang: str = "tur"

class Stream(BaseModel):
    name: str = "[TR Dublaj] HD"
    title: str
    url: Optional[str] = None
    infoHash: Optional[str] = None
    fileIdx: Optional[int] = None
    behaviorHints: Optional[BehaviorHints] = None
    subtitles: Optional[List[Subtitle]] = None

class StreamResponse(BaseModel):
    streams: List[Stream] = Field(default_factory=list)

class ManifestResource(BaseModel):
    name: str
    types: List[str]
    idPrefixes: Optional[List[str]] = None

class Manifest(BaseModel):
    id: str
    name: str
    version: str
    description: str
    resources: List[Union[str, ManifestResource]]
    types: List[str]
    catalogs: List[Dict[str, Any]] = Field(default_factory=list)
    background: Optional[str] = None
    logo: Optional[str] = None
    contactEmail: Optional[str] = None
    behaviorHints: Optional[Dict[str, Any]] = None

class UserConfig(BaseModel):
    enable_direct: bool = True
    enable_torrents: bool = True
    prefer_dubbed: bool = True
    enable_subbed: bool = True
    max_streams_per_provider: int = 4
    enabled_providers: List[str] = Field(
        default_factory=lambda: [
            "hdfilmcehennemi",
            "dizipal",
            "fullhdfilmizlesene",
            "diziwatch",
            "turktorrent"
        ]
    )
    qualities: List[str] = Field(default_factory=lambda: ["1080p", "720p", "4k"])
