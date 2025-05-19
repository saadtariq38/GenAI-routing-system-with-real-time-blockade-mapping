import React, { useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import L from 'leaflet';

function App() {
  const [map, setMap] = useState(null);
  const [routeLayer, setRouteLayer] = useState(null);
  const [polyLayers, setPolyLayers] = useState([]);
  const [routeGeo, setRouteGeo] = useState(null);

  useEffect(() => {
    const centerLat = (24.921264 + 24.8413) / 2;
    const centerLon = (67.131119 + 67.0629) / 2;
    const m = L.map('root').setView([centerLat, centerLon], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(m);
    setMap(m);
  }, []);

  const getInitialRoute = async () => {
    const resp = await fetch('http://localhost:8000/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        start: [67.131119, 24.921264],
        end:   [67.0629,   24.8413],
      }),
    });
    const { routes } = await resp.json();
    const geometry = { type: 'LineString', coordinates: routes[0].geometry.coordinates };

    setRouteGeo(geometry);
    if (routeLayer) map.removeLayer(routeLayer);
    const rl = L.geoJSON(geometry).addTo(map);
    setRouteLayer(rl);
  };

  const adjustRoute = async () => {
    if (!routeGeo) { alert('Get initial route first'); return; }
    const promptText = prompt("Describe blockade (e.g. 'Flood on Elm St')");
    const resp = await fetch('http://localhost:8000/adjust', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ route: routeGeo, description: promptText }),
    });
    const { route, blockades } = await resp.json();

    // clear old
    if (routeLayer) map.removeLayer(routeLayer);
    polyLayers.forEach(l => map.removeLayer(l));
    setPolyLayers([]);

    // draw new route
    const rl = L.geoJSON(route).addTo(map);
    setRouteLayer(rl);

    // draw all blockades, color by collided flag
    const newLayers = blockades.map((feature, idx) => {
      const collided = feature.properties.collided;
      const layer = L.geoJSON(feature, {
        style: () => ({
          color: collided ? 'red' : 'gray',
          weight: 2,
          fillOpacity: collided ? 0.4 : 0.1,
        })
      })
      .bindPopup(`<strong>${feature.id}</strong><br/>${feature.properties.reason || ''}`)
      .addTo(map);
      return layer;
    });
    setPolyLayers(newLayers);
  };

  return (
    <div style={{ position:'absolute', top:10, left:10, zIndex:1000 }}>
      <button onClick={getInitialRoute}>Get Initial Route</button>
      <button onClick={adjustRoute}>Adjust Route</button>
    </div>
  );
}

const container = document.getElementById('root');
createRoot(container).render(<App />);
