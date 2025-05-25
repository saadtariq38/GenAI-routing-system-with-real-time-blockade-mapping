# GenAI Blockade-Aware Routing Service

_A demo application that wraps OSRM (Open Source Routing Machine) to provide dynamic blockade avoidance with hierarchical caching._

---

![Architecture Diagram](image.png)

## Project Overview

This project demonstrates a high-throughput routing service using GenAI that:

- **Indexes** road blockades (e.g. floods, construction) on a 150 m GeoHash grid  
- **Caches** adjusted routes by origin/destination (750 m grid) + blockade collision fingerprint  
- **Detours** around blockades in real time with minimal latency  
- **Exposes** a FastAPI backend and a React/Leaflet frontend  

---

## Purpose

- We want a routing demo that can instantly change its directions when a road is blocked (by a flood, protest, construction, etc.). That means:
“Know” where the blockades are.
- Detect if a new route touches any of them.
- Either reuse a cached detour or call the OSRM engine to skirt around the trouble spots.
  
### How the Gen-AI piece helps
- You type a natural-language description like “There’s a flood on Shahrah-e-Faisal between XYZ and ABC.”
- We pass that text to an LLM (OpenAI GPT-4o).
- The model replies with a raw GeoJSON polygon that outlines the flooded area.
  
![Architecture Diagram](image(2).png)

![Architecture Diagram](image(2).png)

## Architecture
[Browser UI] ↔︎ [API Gateway] ↔︎ [FastAPI Routing Wrapper] ↔︎ [OSRM Cluster]

↑
[In-Memory Cache]

↑
[Blockade Index]
---

## 🔧 Automated Setup & Launch

All steps can be run together:

```bash
git clone https://github.com/your-org/your-repo.git
cd your-repo

# This will:
# 1. Install backend & frontend dependencies
# 2. Download Pakistan OSM data
# 3. Prepare OSRM files
# 4. Launch OSRM, backend, and frontend
make up

```


## If you prefer to run each component by hand:

```bash

cd backend
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cd ../frontend
npm install
Download & prepare map


mkdir -p data
wget -c https://download.geofabrik.de/asia/pakistan-latest.osm.pbf -O data/pakistan-latest.osm.pbf

# Extract & customize OSRM data
docker run --rm -v $(pwd)/data:/data osrm/osrm-backend osrm-extract -p /opt/car.lua /data/pakistan-latest.osm.pbf
docker run --rm -v $(pwd)/data:/data osrm/osrm-backend osrm-partition /data/pakistan-latest.osrm
docker run --rm -v $(pwd)/data:/data osrm/osrm-backend osrm-customize /data/pakistan-latest.osrm
Start OSRM server

docker run --rm -p 5000:5000 -v $(pwd)/data:/data osrm/osrm-backend \
  osrm-routed --algorithm mld /data/pakistan-latest.osrm
Run FastAPI backend

cd backend
source .venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
Run React frontend

bash
Copy
Edit
cd frontend
npm start

```
