
import streamlit as st
import osmnx as ox
import folium
from geopy.distance import geodesic
import itertools
import pandas as pd
from datetime import datetime, time, timedelta
import random
import json
from streamlit_folium import st_folium # For displaying Folium maps in Streamlit

# --- GLOBAL CONFIGURATION (from Part 2 of your notebook) ---
# Define default parameters for different vehicle types
vehicle_type_definitions = {
    "car": {"L_PER_100KM": 7, "AVG_SPEED_KMH": 40, "NETWORK_TYPE": "drive", "departure_time": "09:00"},
    "motorcycle": {"L_PER_100KM": 3, "AVG_SPEED_KMH": 30, "NETWORK_TYPE": "drive", "departure_time": "08:30"},
    "truck": {"L_PER_100KM": 15, "AVG_SPEED_KMH": 35, "NETWORK_TYPE": "drive", "departure_time": "07:00"},
}

# Assign a type to each vehicle and optionally override type defaults
vehicle_parameters = {
    "Vehicle A": {"type": "motorcycle", "departure_time": "01:00"},
    "Vehicle B": {"type": "truck", "L_PER_100KM": 15, "departure_time": "12:30"},
    "Vehicle C": {"type": "car", "AVG_SPEED_KMH": 7, "departure_time": "18:00"},
}

# Default fallback values for vehicles without a specified type or if a type is undefined
DEFAULT_L_PER_100KM = 7  # Liters per 100 km
DEFAULT_AVG_SPEED_KMH = 40  # Average speed in km/h (used for distance-optimized time estimation)
COST_PER_LITER = 25000  # VND per liter

# --- HELPER FUNCTIONS (adapted from Part 2, 4, 5 of your notebook) ---
def get_vehicle_params(vehicle_name):
    params = {}
    vehicle_config = vehicle_parameters.get(vehicle_name, {})
    vehicle_type = vehicle_config.get("type")

    if vehicle_type and vehicle_type in vehicle_type_definitions:
        params.update(vehicle_type_definitions[vehicle_type])
    else:
        params.update({
            "L_PER_100KM": DEFAULT_L_PER_100KM,
            "AVG_SPEED_KMH": DEFAULT_AVG_SPEED_KMH,
            "departure_time": "09:00"
        })

    params.update({
        k: v for k, v in vehicle_config.items() if k != "type"
    })
    return params

def assign_stops_by_stt_values(df, lat_col, lon_col, assignments):
    vehicle_routes = {}
    for vehicle, stt_values in assignments.items():
        filtered_df = df[df['stt'].isin(stt_values)]
        vehicle_stops = list(zip(filtered_df[lat_col], filtered_df[lon_col]))
        vehicle_routes[vehicle] = vehicle_stops
    return vehicle_routes

# Helper function for static traffic multiplier (from Part 4)
def get_traffic_multiplier(departure_time_str):
    dep_time = datetime.strptime(departure_time_str, '%H:%M').time()
    morning_rush_start = time(7, 0)
    morning_rush_end = time(9, 30)
    evening_rush_start = time(16, 30)
    evening_rush_end = time(19, 0)

    if (morning_rush_start <= dep_time <= morning_rush_end) or        (evening_rush_start <= dep_time <= evening_rush_end):
        return 1.5
    else:
        return 1.0

# Helper function to simulate external real-time traffic updates (from Part 5)
def get_simulated_real_time_traffic_multiplier(current_simulated_time):
    current_hour = current_simulated_time.hour
    current_minute = current_simulated_time.minute
    if 7 <= current_hour < 9 or (current_hour == 9 and current_minute <= 30):
        if random.random() < 0.7:
            return random.uniform(1.5, 2.0)
        else:
            return random.uniform(1.0, 1.2)
    elif 16 <= current_hour < 19 or (current_hour == 19 and current_minute <= 0):
        if random.random() < 0.7:
            return random.uniform(1.5, 2.0)
        else:
            return random.uniform(1.0, 1.2)
    elif random.random() < 0.1:
        return random.uniform(1.3, 1.7)
    else:
        return 1.0

def simulate_dynamic_re_routing(vehicle_name, initial_stops, G_graph, total_sim_duration_minutes=60, check_interval_minutes=10):
    st.write(f"--- Starting dynamic simulation for {vehicle_name} ---")

    current_stops_sequence = list(initial_stops)
    params = get_vehicle_params(vehicle_name)
    initial_departure_time_str = params.get('departure_time', '09:00')

    current_simulated_time = datetime.strptime(initial_departure_time_str, '%H:%M').replace(year=2023, month=1, day=1)

    completed_segments = []
    current_location = current_stops_sequence[0]
    remaining_stops = current_stops_sequence[1:]

    total_journey_time_taken_sec = 0
    total_journey_distance_km = 0

    def calculate_current_optimal_path(start_point, end_points, G, current_sim_time, initial_dep_time_str):
        if not end_points:
            return None, 0, 0

        next_dest_point = end_points[0]

        current_traffic_mult = get_simulated_real_time_traffic_multiplier(current_sim_time)

        def get_edge_travel_time_with_dynamic_traffic(u, v, data):
            return data.get('travel_time', float('inf')) * current_traffic_mult

        orig_node = ox.distance.nearest_nodes(G, start_point[1], start_point[0])
        dest_node = ox.distance.nearest_nodes(G, next_dest_point[1], next_dest_point[0])

        route = ox.shortest_path(G, orig_node, dest_node, weight=get_edge_travel_time_with_dynamic_traffic)

        if route:
            segment_travel_time = 0
            segment_distance = 0
            for u_edge, v_edge in zip(route[:-1], route[1:]):
                edge_data = G.get_edge_data(u_edge, v_edge, key=0)
                if edge_data:
                    segment_travel_time += edge_data.get('travel_time', 0) * current_traffic_mult
                    segment_distance += edge_data.get('length', 0)
            return route, segment_travel_time, segment_distance / 1000
        return None, float('inf'), float('inf')

    while remaining_stops and total_journey_time_taken_sec < total_sim_duration_minutes * 60:
        if total_journey_time_taken_sec % (check_interval_minutes * 60) == 0 or total_journey_time_taken_sec == 0:
            current_route_segment, estimated_segment_time, estimated_segment_distance =                 calculate_current_optimal_path(current_location, remaining_stops, G_graph, current_simulated_time, initial_departure_time_str)

            if current_route_segment is None:
                st.warning(f"No path found from {current_location} to next stop {remaining_stops[0]}. Ending simulation.")
                break

        travel_time_this_interval_sec = min(estimated_segment_time, check_interval_minutes * 60)

        total_journey_time_taken_sec += travel_time_this_interval_sec
        current_simulated_time += timedelta(seconds=travel_time_this_interval_sec)

        if travel_time_this_interval_sec == estimated_segment_time:
            completed_segments.append((current_location, remaining_stops[0]))
            total_journey_distance_km += estimated_segment_distance
            current_location = remaining_stops.pop(0)
            if not remaining_stops:
                break
        else:
            pass


    return {
        "Vehicle": vehicle_name,
        "Simulated Travel Time (minutes)": total_journey_time_taken_sec / 60,
        "Simulated Distance (km)": total_journey_distance_km,
        "Stops Completed": len(completed_segments),
        "All Stops Reached": not bool(remaining_stops)
    }

# --- Main Streamlit App Logic ---
def main():
    st.set_page_config(layout="wide")
    st.title("Real-time Route Optimization Web App")
    st.markdown("This application demonstrates dynamic route optimization with traffic simulation.")

    # --- Sidebar for Inputs ---
    st.sidebar.header("Configuration")

    uploaded_file = st.sidebar.file_uploader("Upload Route Data (Excel)", type=["xlsx"])
    df = None
    lat_col = None
    lon_col = None
    if uploaded_file is not None:
        df = pd.read_excel(uploaded_file)
        st.sidebar.success("RouteData.xlsx loaded successfully!")

        # Standardize column names
        df.columns = df.columns.str.lower()

        # Identify potential combined coordinate columns
        combined_coord_cols = [c for c in df.columns if "lat" in c and "long" in c]

        if combined_coord_cols:
            combined_col = combined_coord_cols[0]
            df[['latitude_parsed', 'longitude_parsed']] = (
                df[combined_col]
                .astype(str)
                .str.strip('()')
                .str.split(', ', expand=True)
                .astype(float)
            )
            lat_col = 'latitude_parsed'
            lon_col = 'longitude_parsed'
        else:
            # Fallback: separate latitude and longitude columns
            lat_candidates = [c for c in df.columns if "lat" in c or "vi" in c]
            lon_candidates = [c for c in df.columns if "long" in c or "can" in c]

            if lat_candidates and lon_candidates:
                lat_col = lat_candidates[0]
                lon_col = lon_candidates[0]
            else:
                st.error("Could not identify suitable latitude and longitude columns. Please check your Excel file.")
                st.stop()

        # Fix swapped coordinates if needed
        if df[lat_col].mean() > 90:
            lat_col, lon_col = lon_col, lat_col

    st.sidebar.subheader("Vehicle Assignments (STT values)")
    vehicle_assignments_str = st.sidebar.text_area("Enter vehicle assignments as JSON (e.g., {'Vehicle A': [1, 2, 19]}) ")
    vehicle_routes = {}
    if vehicle_assignments_str:
        try:
            raw_assignments = json.loads(vehicle_assignments_str)
            if df is not None and lat_col and lon_col:
                vehicle_routes = assign_stops_by_stt_values(df, lat_col, lon_col, raw_assignments)
                st.sidebar.success("Vehicle assignments parsed and applied.")
            else:
                st.sidebar.warning("Please upload Route Data first.")
        except json.JSONDecodeError:
            st.sidebar.error("Invalid JSON for vehicle assignments.")

    # --- Main Content Area ---
    st.header("1. Visualizing Stops")
    if vehicle_routes and df is not None:
        all_lats = [coord[0] for stops_list in vehicle_routes.values() for coord in stops_list]
        all_lons = [coord[1] for stops_list in vehicle_routes.values() for coord in stops_list]

        map_center_lat = sum(all_lats) / len(all_lats) if all_lats else df[lat_col].mean()
        map_center_lon = sum(all_lons) / len(all_lons) if all_lons else df[lon_col].mean()

        m = folium.Map(location=[map_center_lat, map_center_lon], zoom_start=12)

        colors = itertools.cycle([
            'red', 'blue', 'green', 'purple', 'orange', 'darkred', 'lightred', 'beige',
            'darkblue', 'darkgreen', 'cadetblue', 'darkpurple', 'white', 'pink', 'lightblue',
            'lightgreen', 'gray', 'black', 'lightgray'
        ])
        vehicle_colors = {}

        for vehicle, stops in vehicle_routes.items():
            color = next(colors)
            vehicle_colors[vehicle] = color
            for i, stop in enumerate(stops):
                folium.Marker(
                    location=[stop[0], stop[1]],
                    popup=f"Vehicle: {vehicle}<br>Stop {i+1}<br>Lat: {stop[0]:.4f}<br>Lon: {stop[1]:.4f}",
                    icon=folium.Icon(color=color)
                ).add_to(m)

        legend_html = '<div style="position: fixed; bottom: 50px; left: 50px; width: 120px; height: auto; z-index:9999; font-size:14px; background-color:white; border:2px solid grey; border-radius:5px; padding: 10px;"><b>Vehicles</b><br>'
        for vehicle, color in vehicle_colors.items():
            legend_html += f'<i class="fa fa-map-marker fa-1x" style="color:{color}"></i> {vehicle}<br>'
        legend_html += '</div>'
        m.get_root().html.add_child(folium.Element(legend_html))

        st_folium(m, width=700, height=500)

    else:
        st.info("Upload route data and define vehicle assignments to visualize stops.")

    st.header("2. Optimal Route Calculation (Distance & Time)")
    if st.button("Calculate Optimal Routes"):
        if not vehicle_routes or df is None:
            st.warning("Please upload route data and define vehicle assignments first.")
            return

        st.write("Calculating...")

        # --- Distance-Optimized Routes (from Part 3) ---
        optimal_routes_per_vehicle = {}
        G_distance_optimized_cache = {}

        all_stops_coords_for_graph_center = []
        for stops_list in vehicle_routes.values():
            all_stops_coords_for_graph_center.extend(stops_list)

        if all_stops_coords_for_graph_center:
            map_center_lat_dist = sum(p[0] for p in all_stops_coords_for_graph_center) / len(all_stops_coords_for_graph_center)
            map_center_lon_dist = sum(p[1] for p in all_stops_coords_for_graph_center) / len(all_stops_coords_for_graph_center)

            for vehicle, stops in vehicle_routes.items():
                if not stops:
                    continue

                params = get_vehicle_params(vehicle)
                network_type_for_vehicle = params.get("NETWORK_TYPE", 'drive')

                if network_type_for_vehicle in G_distance_optimized_cache:
                    G_distance_optimized = G_distance_optimized_cache[network_type_for_vehicle]
                else:
                    G_distance_optimized = ox.graph_from_point(
                        (map_center_lat_dist, map_center_lon_dist),
                        dist=2000,
                        network_type=network_type_for_vehicle
                    )
                    G_distance_optimized_cache[network_type_for_vehicle] = G_distance_optimized

                min_d_vehicle = float('inf')
                best_route_vehicle = None

                for perm in itertools.permutations(stops):
                    current_permutation_total_distance_km = 0

                    for i in range(len(perm) - 1):
                        orig_point = perm[i]
                        dest_point = perm[i+1]

                        orig_node = ox.distance.nearest_nodes(G_distance_optimized, orig_point[1], orig_point[0])
                        dest_node = ox.distance.nearest_nodes(G_distance_optimized, dest_point[1], dest_point[0])

                        route_segment = ox.shortest_path(G_distance_optimized, orig_node, dest_node, weight='length')

                        if route_segment:
                            segment_distance_meters = 0
                            for u, v in zip(route_segment[:-1], route_segment[1:]):
                                edge_attrs = G_distance_optimized.get_edge_data(u, v, key=0)
                                if edge_attrs:
                                    segment_distance_meters += edge_attrs.get('length', 0)
                            current_permutation_total_distance_km += segment_distance_meters / 1000
                        else:
                            current_permutation_total_distance_km = float('inf')
                            break

                    if current_permutation_total_distance_km < min_d_vehicle:
                        min_d_vehicle = current_permutation_total_distance_km
                        best_route_vehicle = perm

                optimal_routes_per_vehicle[vehicle] = {
                    "min_distance": min_d_vehicle,
                    "best_route": best_route_vehicle
                }
        else:
            st.warning("No stops defined to create a graph for distance-optimized routing.")

        st.subheader("Distance-Optimized Routes")
        # --- Display m_dist map here (from Part 4) ---
        all_optimal_stops_dist = []
        for vehicle, data in optimal_routes_per_vehicle.items():
            if data["best_route"]:
                all_optimal_stops_dist.extend(data["best_route"])

        if all_optimal_stops_dist:
            map_center_lat_dist_map = sum(p[0] for p in all_optimal_stops_dist) / len(all_optimal_stops_dist)
            map_center_lon_dist_map = sum(p[1] for p in all_optimal_stops_dist) / len(all_optimal_stops_dist)
        else:
            map_center_lat_dist_map = map_center_lat_dist # Fallback to graph center
            map_center_lon_dist_map = map_center_lon_dist

        m_dist = folium.Map(location=[map_center_lat_dist_map, map_center_lon_dist_map], zoom_start=12)

        colors_dist = itertools.cycle([
            'red', 'blue', 'green', 'purple', 'orange', 'darkred', 'lightred', 'beige',
            'darkblue', 'darkgreen', 'cadetblue', 'darkpurple', 'white', 'pink', 'lightblue',
            'lightgreen', 'gray', 'black', 'lightgray'
        ])
        vehicle_route_colors_dist = {}

        G_map_dist = None
        if 'drive' in G_distance_optimized_cache:
            G_map_dist = G_distance_optimized_cache['drive']
        elif all_optimal_stops_dist:
            min_lat = min(s[0] for s in all_optimal_stops_dist)
            max_lat = max(s[0] for s in all_optimal_stops_dist)
            min_lon = min(s[1] for s in all_optimal_stops_dist)
            max_lon = max(s[1] for s in all_optimal_stops_dist)
            bbox = (max_lat, min_lon, min_lat, max_lon)
            north, south, east, west = bbox
            margin = 0.01
            try:
                G_map_dist = ox.graph_from_bbox(north + margin, south - margin, east + margin, west - margin, network_type='drive')
            except Exception as e:
                st.warning(f"Could not create graph for distance map: {e}")

        if G_map_dist:
            for vehicle, data in optimal_routes_per_vehicle.items():
                best_route = data["best_route"]
                if not best_route:
                    continue

                route_color = next(colors_dist)
                vehicle_route_colors_dist[vehicle] = route_color

                for i in range(len(best_route) - 1):
                    orig_point = best_route[i]
                    dest_point = best_route[i+1]

                    orig_node = ox.distance.nearest_nodes(G_map_dist, orig_point[1], orig_point[0])
                    dest_node = ox.distance.nearest_nodes(G_map_dist, dest_point[1], dest_point[0])

                    route = ox.shortest_path(G_map_dist, orig_node, dest_node, weight='length')

                    if route:
                        route_coords = [(G_map_dist.nodes[n]['y'], G_map_dist.nodes[n]['x']) for n in route]
                        folium.PolyLine(route_coords, color=route_color, weight=4, opacity=0.8,
                                        popup=f"{vehicle} Dist-Opt Segment {i+1}").add_to(m_dist)

            legend_html_dist = '<div style="position: fixed; bottom: 50px; left: 50px; width: 150px; height: auto; z-index:9999; font-size:14px; background-color:white; border:2px solid grey; border-radius:5px; padding: 10px;"><b>Distance-Opt Routes</b><br>'
            for vehicle, color in vehicle_route_colors_dist.items():
                legend_html_dist += f'<i class="fa fa-map-marker fa-1x" style="color:{color}"></i> {vehicle}<br>'
            legend_html_dist += '</div>'
            m_dist.get_root().html.add_child(folium.Element(legend_html_dist))

            st_folium(m_dist, width=700, height=500)
        else:
            st.warning("Cannot display distance-optimized map as graph was not successfully generated.")


        # --- Time-Optimized Routes (from Part 4) ---
        st.subheader("Time-Optimized Routes")
        optimal_time_routes_per_vehicle = {}
        G_time_optimized = None

        if all_stops_coords_for_graph_center:
            G_time_optimized = ox.graph_from_point(
                (map_center_lat_dist, map_center_lon_dist),
                dist=2000,
                network_type='drive'
            )
            G_time_optimized = ox.add_edge_speeds(G_time_optimized)
            G_time_optimized = ox.add_edge_travel_times(G_time_optimized)

            for vehicle, stops in vehicle_routes.items():
                if not stops:
                    continue

                min_time_vehicle = float('inf')
                best_time_route_sequence_vehicle = None

                params = get_vehicle_params(vehicle)
                vehicle_departure_time = params.get('departure_time', '09:00')
                initial_traffic_multiplier = get_traffic_multiplier(vehicle_departure_time)

                def get_edge_travel_time_with_initial_traffic(u, v, data):
                    return data.get('travel_time', float('inf')) * initial_traffic_multiplier

                for perm in itertools.permutations(stops):
                    current_permutation_total_time_sec = 0

                    for i in range(len(perm) - 1):
                        orig_point = perm[i]
                        dest_point = perm[i+1]

                        orig_node = ox.distance.nearest_nodes(G_time_optimized, orig_point[1], orig_point[0])
                        dest_node = ox.distance.nearest_nodes(G_time_optimized, dest_point[1], dest_point[0])

                        route_segment = ox.shortest_path(G_time_optimized, orig_node, dest_node, weight=get_edge_travel_time_with_initial_traffic)

                        if route_segment:
                            segment_travel_time_sec = 0
                            for u_edge, v_edge in zip(route_segment[:-1], route_segment[1:]):
                                edge_data = G_time_optimized.get_edge_data(u_edge, v_edge, key=0)
                                if edge_data:
                                    segment_travel_time_sec += edge_data.get('travel_time', 0) * initial_traffic_multiplier
                            current_permutation_total_time_sec += segment_travel_time_sec
                        else:
                            current_permutation_total_time_sec = float('inf')
                            break

                    if current_permutation_total_time_sec < min_time_vehicle:
                        min_time_vehicle = current_permutation_total_time_sec
                        best_time_route_sequence_vehicle = perm

                optimal_time_routes_per_vehicle[vehicle] = {
                    "min_time_seconds": min_time_vehicle,
                    "best_time_route_sequence": best_time_route_sequence_vehicle
                }

        all_optimal_stops_time = []
        for vehicle, data in optimal_time_routes_per_vehicle.items():
            if data["best_time_route_sequence"]:
                all_optimal_stops_time.extend(data["best_time_route_sequence"])

        if all_optimal_stops_time:
            map_center_lat_time = sum(p[0] for p in all_optimal_stops_time) / len(all_optimal_stops_time)
            map_center_lon_time = sum(p[1] for p in all_optimal_stops_time) / len(all_optimal_stops_time)
        else:
            map_center_lat_time = map_center_lat_dist # Fallback
            map_center_lon_time = map_center_lon_dist

        m_time = folium.Map(location=[map_center_lat_time, map_center_lon_time], zoom_start=12)

        colors_time = itertools.cycle([
            'darkblue', 'darkgreen', 'purple', 'orange', 'cadetblue', 'red', 'lightred', 'beige',
            'darkred', 'lightred', 'beige', 'white', 'pink', 'lightblue',
            'lightgreen', 'gray', 'black', 'lightgray'
        ])
        vehicle_route_colors_time = {}

        if G_time_optimized:
            for vehicle, data in optimal_time_routes_per_vehicle.items():
                best_time_route_sequence = data["best_time_route_sequence"]
                if not best_time_route_sequence:
                    continue

                route_color_time = next(colors_time)
                vehicle_route_colors_time[vehicle] = route_color_time

                params = get_vehicle_params(vehicle)
                vehicle_departure_time = params.get('departure_time', '09:00')
                traffic_multiplier = get_traffic_multiplier(vehicle_departure_time)

                def get_edge_travel_time_with_traffic_for_map(u, v, data):
                    return data.get('travel_time', float('inf')) * traffic_multiplier

                for i in range(len(best_time_route_sequence) - 1):
                    orig_point = best_time_route_sequence[i]
                    dest_point = best_time_route_sequence[i+1]

                    orig_node = ox.distance.nearest_nodes(G_time_optimized, orig_point[1], orig_point[0])
                    dest_node = ox.distance.nearest_nodes(G_time_optimized, dest_point[1], dest_point[0])

                    route = ox.shortest_path(G_time_optimized, orig_node, dest_node, weight=get_edge_travel_time_with_traffic_for_map)

                    if route:
                        route_coords = [(G_time_optimized.nodes[n]['y'], G_time_optimized.nodes[n]['x']) for n in route]
                        folium.PolyLine(route_coords, color=route_color_time, weight=4, opacity=0.8,
                                        popup=f"{vehicle} Time-Opt Segment {i+1} (Traffic: {traffic_multiplier:.1f}x)").add_to(m_time)

            legend_html_time = '<div style="position: fixed; bottom: 50px; left: 50px; width: 150px; height: auto; z-index:9999; font-size:14px; background-color:white; border:2px solid grey; border-radius:5px; padding: 10px;"><b>Time-Opt Routes</b><br>'
            for vehicle, color in vehicle_route_colors_time.items():
                legend_html_time += f'<i class="fa fa-map-marker fa-1x" style="color:{color}"></i> {vehicle}<br>'
            legend_html_time += '</div>'
            m_time.get_root().html.add_child(folium.Element(legend_html_time))

            st_folium(m_time, width=700, height=500)
        else:
            st.warning("Cannot display time-optimized map as graph was not successfully generated.")


        st.header("3. Insights and Dynamic Simulation")
        # --- Insights calculation (from Part 5) ---
        vehicle_insights = []

        for vehicle, data in optimal_routes_per_vehicle.items():
            min_d_vehicle = data['min_distance']

            params = get_vehicle_params(vehicle)
            vehicle_l_per_100km = params["L_PER_100KM"]
            vehicle_avg_speed_kmh = params["AVG_SPEED_KMH"]
            vehicle_departure_time = params.get('departure_time', '09:00')

            traffic_multiplier = get_traffic_multiplier(vehicle_departure_time)

            fuel_consumption = (min_d_vehicle * vehicle_l_per_100km) / 100
            fuel_cost = fuel_consumption * COST_PER_LITER
            time_hours = (min_d_vehicle / vehicle_avg_speed_kmh) * traffic_multiplier
            time_minutes = time_hours * 60

            vehicle_insights.append({
                "Vehicle": vehicle,
                "Optimal Distance (km)": min_d_vehicle,
                "Fuel (L)": fuel_consumption,
                "Cost (VND)": fuel_cost,
                "Time (hours)": time_hours,
                "Time (minutes)": time_minutes
            })

        insights_df = pd.DataFrame(vehicle_insights)
        insights_df['Fuel Efficiency (km/L)'] = insights_df['Optimal Distance (km)'] / insights_df['Fuel (L)']
        insights_df['Cost per km (VND/km)'] = insights_df['Cost (VND)'] / insights_df['Optimal Distance (km)']
        insights_df['Average Speed (km/h)'] = insights_df['Optimal Distance (km)'] / insights_df['Time (hours)']

        st.subheader("Vehicle Performance Insights")
        st.dataframe(insights_df.round(2))

        # --- Dynamic Re-routing Simulation (from Part 5) ---
        simulation_results = []
        if G_time_optimized:
            for vehicle_name, initial_stops in vehicle_routes.items():
                if initial_stops:
                    result = simulate_dynamic_re_routing(
                        vehicle_name,
                        initial_stops,
                        G_time_optimized,
                        total_sim_duration_minutes=90,
                        check_interval_minutes=15
                    )
                    simulation_results.append(result)
                else:
                    st.warning(f"No stops for {vehicle_name}. Skipping dynamic re-routing simulation.")

            if simulation_results:
                dynamic_simulation_df = pd.DataFrame(simulation_results)
                st.subheader("Dynamic Re-routing Simulation Results")
                st.dataframe(dynamic_simulation_df.round(2))
            else:
                st.info("No dynamic simulation results to display.")
        else:
            st.warning("Cannot proceed with dynamic re-routing simulation as the OSMnx graph (G_time_optimized) was not successfully generated.")

    else:
        st.warning("Please upload route data and define vehicle assignments to proceed.")

if __name__ == '__main__':
    main()
