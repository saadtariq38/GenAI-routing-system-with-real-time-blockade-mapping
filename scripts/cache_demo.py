"""
Hit /route and /adjust twice and show timing.  Assumes:

  • Uvicorn is already running on http://localhost:8000  (default FastAPI dev)
  • USE_STUB_LLM=true     so /adjust doesn’t call OpenAI
  • The GeoHash edition of backend/main.py is what’s live

A ∆ > 90 % between 1st and 2nd /adjust proves the TTL cache works.
"""
import asyncio, time, httpx, json

BASE = "http://localhost:8000"

# Karachi example: Expo Centre → Quaid-e-Azam’s Mausoleum
START = [67.05824, 24.89651]
END   = [67.04114, 24.87335]

async def run_once(client):
    # 1️⃣ Initial /route
    t0 = time.perf_counter()
    resp = await client.post(f"{BASE}/route", json={"start": START, "end": END})
    route_json = resp.json()["routes"][0]["geometry"]  # LineString
    t_route = time.perf_counter() - t0

    # 2️⃣ /adjust with the hard-coded stub blockade
    adj_payload = {
        "route": route_json,
        "description": "blockade on Shahrah-e-Faisal",   # ignored b/c USE_STUB=true
    }
    t1 = time.perf_counter()
    resp = await client.post(f"{BASE}/adjust", json=adj_payload)
    _ = resp.json()      # we don’t actually need the body here
    t_adjust = time.perf_counter() - t1

    return t_route, t_adjust

async def main():
    async with httpx.AsyncClient(timeout=None) as client:
        print("Round 1 (cold cache)…")
        r1, a1 = await run_once(client)
        print(f"  /route  : {r1*1000:6.1f} ms")
        print(f"  /adjust : {a1*1000:6.1f} ms")

        print("\nRound 2 (warm cache)…")
        r2, a2 = await run_once(client)
        print(f"  /route  : {r2*1000:6.1f} ms  (always live OSRM)")
        print(f"  /adjust : {a2*1000:6.1f} ms  (should be ≪ Round 1)")

        hit_ratio = (1 - a2 / a1) * 100
        print(f"\nCache-speedup for /adjust ≈ {hit_ratio:.0f}%")

if __name__ == "__main__":
    asyncio.run(main())
