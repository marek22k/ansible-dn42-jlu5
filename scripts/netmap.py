#!/usr/bin/env python3
"""
Generates a GeoJSON network map of the network.
"""

import argparse
import collections
import os
import time

import geopy
import geojson

from _common import *

class NetmapGeocoder():
    """geopy wrapper that saves geocoding results to disk.
    The underlying backend is lazy-loaded when the API is queried, so an API key is only needed when we query a new location."""
    def __init__(self, db_filename, api_key=None):
        self.db_filename = db_filename
        self.api_key = api_key or os.environ.get('GOOGLEMAPS_API_KEY')
        try:
            self.entries = yaml_load(db_filename)
        except FileNotFoundError:
            self.entries = {}

        self._backend = None

    def _init_backend(self):
        if not self.api_key:
            raise ValueError("No API key given for geocoding. Try setting the GOOGLEMAPS_API_KEY environment variable")
        elif self._backend is None:
            self._backend = geopy.geocoders.GoogleV3(api_key=self.api_key)

    def geocode(self, location, **kwargs):
        if location not in self.entries:
            self._init_backend()
            time.sleep(0.01)  # throttle our API calls slightly
            result = self._backend.geocode(location, **kwargs)
            coords = (result.latitude, result.longitude)
            print(f"Geocode: found coords {coords} for location {location}")
            self.entries[location] = coords
        else:
            print(f"Geocode: using existing coords {self.entries[location]} for location {location}")
        return self.entries[location]

    def save(self):
        with open(self.db_filename, 'w') as f:
            yaml.dump(self.entries, f)

def _sort_feature_by_title(feature):
    return feature['properties']['title']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--outfile", help="output path", default="netmap.geojson")
    parser.add_argument("-H", "--hosts", help="path to hosts configuration / inventory file",
                        type=str, default='hosts.yml')
    parser.add_argument("-t", "--tunnels", help="path to IGP tunnels configuration",
                        type=str, default='global-config/igp-tunnels.yml')
    parser.add_argument("-gc", "--geocode-cache", help="cache filename for geocode entries",
                        type=str, default='netmap-geocode.db')
    parser.add_argument("-dn", "--document-name", help="KML document name",
                        type=str, default="AS4242421080 network map")
    args = parser.parse_args()

    hosts = yaml_load(args.hosts)
    hosts = get_hosts(hosts)
    tunnels = yaml_load(args.tunnels)

    geocoder = NetmapGeocoder(args.geocode_cache)
    node_coords = {}
    node_short_names = {node: data['shortname'] for node, data in hosts.items()}

    node_markers = []
    tunnel_lines = []

    # Create a new point for each node
    for node, nodedata in hosts.items():
        if nodedata.get('private') or not nodedata.get('location'):
            continue
        coords = node_coords[node] = geocoder.geocode(nodedata['location'])
        # GeoJSON uses longitude and then latitude
        point = geojson.Point((coords[1], coords[0]))
        peers = ', '.join(sorted(node_short_names[peer] for peer in tunnels['igp_neighbours'][node]))
        description = f"""{nodedata['location']}<br>
Peers:
{peers}
"""
        feature = geojson.Feature(geometry=point, properties={
            "title": node_short_names[node],
            "description": description,
        })
        node_markers.append(feature)

    # Create a new line for each IGP tunnel
    seen_tunnels = set()
    for node in node_coords:
        for neighbour in tunnels['igp_neighbours'][node]:
            if neighbour not in node_coords:
                continue
            if f'{neighbour},{node}' not in seen_tunnels:  # Only add a connection once
                datapair = f'{node},{neighbour}'
                seen_tunnels.add(datapair)
                line = geojson.LineString(
                    [(node_coords[node][1], node_coords[node][0]),
                     (node_coords[neighbour][1], node_coords[neighbour][0])],
                )
                feature = geojson.Feature(geometry=line, properties={
                    "title": f'{node_short_names[node]} <-> {node_short_names[neighbour]}',
                    "description": '',
                })
                tunnel_lines.append(feature)

    node_markers.sort(key=_sort_feature_by_title)
    tunnel_lines.sort(key=_sort_feature_by_title)
    with open(args.outfile, 'w') as f:
        feature_collection = geojson.FeatureCollection(node_markers + tunnel_lines)
        print("feature_collection errors:", feature_collection.errors())
        geojson.dump(feature_collection, f, indent=4)

    print(f"Wrote map data to {args.outfile}")
    geocoder.save()
    print(f"Wrote geocode cache to {args.geocode_cache}")

if __name__ == "__main__":
    main()
