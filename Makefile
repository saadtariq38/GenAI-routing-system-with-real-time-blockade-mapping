.PHONY: setup download-map osrm-prepare up

# 1) Install backend & frontend deps
setup:
	pip install --upgrade pip && \
	pip install -r backend/requirements.txt
	cd frontend && npm install

# 2) Download Pakistan OSM PBF if missing
download-map:
	mkdir -p data
	if [ ! -f data/pakistan-latest.osm.pbf ]; then \
	  wget -c https://download.geofabrik.de/asia/pakistan-latest.osm.pbf -O data/pakistan-latest.osm.pbf; \
	fi

# 3) Prepare OSRM data (extract, partition, customize)
osrm-prepare: download-map
	docker run --rm -v $$(pwd)/data:/data osrm/osrm-backend \
	  osrm-extract -p /opt/car.lua /data/pakistan-latest.osm.pbf
	docker run --rm -v $$(pwd)/data:/data osrm/osrm-backend \
	  osrm-partition /data/pakistan-latest.osrm
	docker run --rm -v $$(pwd)/data:/data osrm/osrm-backend \
	  osrm-customize /data/pakistan-latest.osrm

# 4) Bring up OSRM engine + backend + frontend
up: setup osrm-prepare
	docker-compose up --build
