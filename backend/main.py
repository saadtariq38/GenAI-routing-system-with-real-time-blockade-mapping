import os, json, hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Set

# ────────────────── GeoHash import (python-geohash or geohash2) ────────────────
try:                                # pip install python-geohash
    import geohash
except ImportError:                 # pip install geohash2
    import geohash2 as geohash      # type: ignore

from shapely.geometry import Point, Polygon, LineString, shape
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

# ───────────────────────── constants ───────────────────────────────────────────
PREC_ROUTE   = 6          # ~750 m cells  – origin / destination bins
PREC_BLOCK   = 7          # ~150 m cells  – blockade & route sampling
TTL_SECONDS  = 300        # 5-minute cache

# ───────────────────────── spatial helpers ─────────────────────────────────────
def point_to_cell(lat: float, lon: float, prec: int) -> str:
    return geohash.encode(lat, lon, precision=prec)


def polygon_to_cells(poly: Polygon, prec: int = PREC_BLOCK) -> Set[str]:
    """GeoHash-cover a polygon (centre-inclusion)."""
    _, _, lat_err, lon_err = geohash.decode_exactly(geohash.encode(0, 0, prec))
    lat_step, lon_step = lat_err * 2, lon_err * 2
    minx, miny, maxx, maxy = poly.bounds

    cells: Set[str] = set()
    y = miny
    while y <= maxy:
        x = minx
        while x <= maxx:
            p = Point(x, y)
            if poly.contains(p):
                cells.add(point_to_cell(p.y, p.x, prec))
            x += lon_step
        y += lat_step

    if not cells:  # degenerate tiny polygon → hash its centroid
        c = poly.centroid
        cells.add(point_to_cell(c.y, c.x, prec))
    return cells


def densify(coords: List[List[float]], step: float = 0.0009) -> List[List[float]]:
    """Insert points so no segment exceeds ~100 m (~0.0009°)."""
    out: List[List[float]] = []
    for (lon0, lat0), (lon1, lat1) in zip(coords[:-1], coords[1:]):
        out.append([lon0, lat0])
        dist = max(abs(lon1 - lon0), abs(lat1 - lat0))
        n = max(1, int(dist / step))              # always ≥ 1
        for i in range(1, n):
            f = i / n
            out.append([lon0 + (lon1 - lon0) * f, lat0 + (lat1 - lat0) * f])
    out.append(coords[-1])
    return out


def line_to_cells(line: LineString) -> Set[str]:
    return {
        point_to_cell(lat, lon, PREC_BLOCK) for lon, lat in densify(list(line.coords))
    }

# ───────────────────────── blockade index ──────────────────────────────────────
CELL_INDEX: Dict[str, Set[str]]   = {}      # cell7 → {blkID}
BLOCKADE_GEOMS: Dict[str, Polygon] = {}     # blkID → Polygon
BLOCKADE_META: Dict[str, dict]    = {}      # blkID → properties/reason


def register_blockade(bid: str, poly: Polygon, meta: dict | None = None) -> None:
    """Add a blockade polygon to the in-memory index (idempotent)."""
    if bid in BLOCKADE_GEOMS:
        return
    for c in polygon_to_cells(poly):
        CELL_INDEX.setdefault(c, set()).add(bid)
    BLOCKADE_GEOMS[bid] = poly
    BLOCKADE_META[bid]  = meta or {}

# ───────────────────────── Precompute blockades ───────────────────────────────
def precompute_blockades():
    """
    Register all demo blockades at startup, separated from /adjust logic.
    """
    CENTER = (67.1000, 24.8770)
    def square(cx, cy, d=0.0025):
        return [
            [cx - d, cy - d], [cx + d, cy - d],
            [cx + d, cy + d], [cx - d, cy + d], [cx - d, cy - d],
        ]
    demo = [
        ("blk-west",   (-0.01,  0.00), {"reason":"west protest"}),
        ("blk-center",( 0.00,  0.00), {"reason":"construction"}),
        ("blk-east",  ( 0.01,  0.00), {"reason":"east flood"}),
        ("blk-north", ( 0.00,  0.01), {"reason":"accident"}),
    ]
    for bid, offset, meta in demo:
        poly = Polygon(square(CENTER[0] + offset[0], CENTER[1] + offset[1]))
        register_blockade(bid, poly, meta)

# ───────────────────────── FastAPI setup ───────────────────────────────────────
load_dotenv()
OSRM_URL = os.getenv("OSRM_URL", "http://localhost:5000")
USE_STUB = os.getenv("USE_STUB_LLM", "true").lower() == "true"

if not USE_STUB:
    import openai                # type: ignore
    openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Register stub blockades on startup if using stub
@app.on_event("startup")
def load_blockades():
    if USE_STUB:
        precompute_blockades()

# ───────────────────────── Pydantic models & cache ────────────────────────────
class RouteReq(BaseModel):
    start: List[float]       # [lon, lat]
    end:   List[float]

class AdjustReq(BaseModel):
    route: dict              # GeoJSON LineString geometry
    description: str

class CacheEntry:
    __slots__ = ("route", "expires")
    def __init__(self, route: dict):
        self.route   = route
        self.expires = datetime.utcnow() + timedelta(seconds=TTL_SECONDS)

CACHE: Dict[tuple[str, str, str], CacheEntry] = {}

def od_bins(line_geom: dict) -> tuple[str, str]:
    (lon0, lat0) = line_geom["coordinates"][0]
    (lon1, lat1) = line_geom["coordinates"][-1]
    return (
        point_to_cell(lat0, lon0, PREC_ROUTE),
        point_to_cell(lat1, lon1, PREC_ROUTE),
    )

def _feature(bid: str) -> dict:
    """Convert stored blockade to a GeoJSON Feature."""
    return {
        "type":       "Feature",
        "id":         bid,
        "properties": BLOCKADE_META.get(bid, {}),
        "geometry":   BLOCKADE_GEOMS[bid].__geo_interface__,
    }

# ───────────────────────── endpoints ──────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/route")
async def route(r: RouteReq):
    coords = f"{r.start[0]},{r.start[1]};{r.end[0]},{r.end[1]}"
    url = f"{OSRM_URL}/route/v1/driving/{coords}?overview=full&geometries=geojson"
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as cli:
        resp = await cli.get(url); resp.raise_for_status()
    return resp.json()

@app.post("/adjust")
async def adjust(req: AdjustReq):
    """
    Return an adjusted route and all blockades (with collided flags).
    Response: { route, blockades[], collisionSignature }
    """
    # 1️⃣  Compute collisions
    line        = LineString(req.route["coordinates"])
    route_cells = line_to_cells(line)
    cand_ids    = {bid for c in route_cells for bid in CELL_INDEX.get(c, set())}

    collision_sig = (
        hashlib.md5(",".join(sorted(cand_ids)).encode(), usedforsecurity=False).hexdigest()
        if cand_ids else ""
    )

    # 2️⃣  Build full blockade list with collided flag
    all_blockades = []
    for bid, poly in BLOCKADE_GEOMS.items():
        feature = {
            "type": "Feature",
            "id": bid,
            "properties": {**BLOCKADE_META[bid], "collided": bid in cand_ids},
            "geometry": poly.__geo_interface__,
        }
        all_blockades.append(feature)

    # 3️⃣  Cache lookup
    cache_key = (*od_bins(req.route), collision_sig)
    entry = CACHE.get(cache_key)
    if entry and entry.expires > datetime.utcnow():
        return {"route": entry.route, "blockades": all_blockades, "collisionSignature": collision_sig}

    # 4️⃣  No collision → original route
    if not cand_ids:
        CACHE[cache_key] = CacheEntry(req.route)
        return {"route": req.route, "blockades": all_blockades, "collisionSignature": collision_sig}

    # 5️⃣  Collision → simple waypoint detour
    first_poly = BLOCKADE_GEOMS[next(iter(sorted(cand_ids)))]
    minx, _, maxx, maxy = first_poly.bounds
    waypoint = [(minx + maxx) / 2, maxy + 0.02]
    seq = [req.route["coordinates"][0], waypoint, req.route["coordinates"][-1]]
    coords = ";".join(f"{lon},{lat}" for lon, lat in seq)
    url = f"{OSRM_URL}/route/v1/driving/{coords}?overview=full&geometries=geojson"
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as cli:
        resp = await cli.get(url); resp.raise_for_status()
    detour = resp.json()["routes"][0]["geometry"]

    CACHE[cache_key] = CacheEntry(detour)
    return {"route": detour, "blockades": all_blockades, "collisionSignature": collision_sig}
