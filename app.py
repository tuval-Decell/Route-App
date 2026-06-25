import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
import xml.etree.ElementTree as ET
from geopy.geocoders import Nominatim
import pandas as pd
import math

# --- הגדרות ---
BASE_URL = "http://routing.decell.com:8080/route"
CSV_FILE_PATH = "database.csv"  # שים לב: הקובץ צריך להיות באותה תיקייה עם הקוד
ID_COLUMN_NAME = "UserID"
COLUMNS_TO_DISPLAY = ["RoadFuncti", "RoadType", "Flag"]

# הגדרת עמוד האפליקציה (שייפתח על כל המסך)
st.set_page_config(page_title="Route Generator", layout="wide")


# --- פונקציות עזר וטעינת נתונים ---
def clean_id(val):
    try:
        if pd.isna(val): return ""
        return str(abs(int(float(val))))
    except (ValueError, TypeError):
        return str(val).strip()


@st.cache_data  # פקודה ששומרת את בסיס הנתונים בזיכרון של השרת
def load_database():
    encodings_to_try = ['utf-8-sig', 'cp1255', 'latin-1']
    for enc in encodings_to_try:
        try:
            # שימוש ב-Pandas שהיא הרבה יותר מהירה ומתאימה לאינטרנט
            df = pd.read_csv(CSV_FILE_PATH, encoding=enc, dtype=str)
            df.columns = df.columns.str.strip()
            if ID_COLUMN_NAME in df.columns:
                df[ID_COLUMN_NAME] = df[ID_COLUMN_NAME].apply(clean_id)
                # הופכים את עמודת ה-ID למפתח החיפוש שלנו
                df.set_index(ID_COLUMN_NAME, inplace=True)
                return df
        except Exception:
            continue
    return pd.DataFrame()


db_data = load_database()

# --- ניהול זיכרון של האפליקציה (Session State) ---
if 'start_coords' not in st.session_state: st.session_state.start_coords = None
if 'end_coords' not in st.session_state: st.session_state.end_coords = None
if 'map_center' not in st.session_state: st.session_state.map_center = [31.5, 34.8]
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 7
if 'paths_to_draw' not in st.session_state: st.session_state.paths_to_draw = []
if 'route_summary' not in st.session_state: st.session_state.route_summary = None

# --- ממשק משתמש (תפריט צד) ---
st.sidebar.title("הגדרות ניווט 🗺️")

# חיפוש כתובת
search_query = st.sidebar.text_input("חפש עיר או כתובת:")
if st.sidebar.button("חפש במפה"):
    geolocator = Nominatim(user_agent="web_route_app")
    location = geolocator.geocode(search_query)
    if location:
        st.session_state.map_center = [location.latitude, location.longitude]
        st.session_state.map_zoom = 14
        st.sidebar.success("הכתובת נמצאה!")
    else:
        st.sidebar.error("הכתובת לא נמצאה.")

st.sidebar.markdown("---")
st.sidebar.markdown("**איך לדקור נקודות?**\nלחץ על המפה, והקואורדינטות יופיעו למטה. העתק אותן למוצא או ליעד.")

start_lat_lon = st.sidebar.text_input("קואורדינטות מוצא (Lat, Lon):",
                                      value=f"{st.session_state.start_coords[0]}, {st.session_state.start_coords[1]}" if st.session_state.start_coords else "")
end_lat_lon = st.sidebar.text_input("קואורדינטות יעד (Lat, Lon):",
                                    value=f"{st.session_state.end_coords[0]}, {st.session_state.end_coords[1]}" if st.session_state.end_coords else "")

# עדכון מקביעי מוצא ויעד מהטקסט
try:
    if start_lat_lon:
        parts = start_lat_lon.split(',')
        st.session_state.start_coords = [float(parts[0].strip()), float(parts[1].strip())]
    if end_lat_lon:
        parts = end_lat_lon.split(',')
        st.session_state.end_coords = [float(parts[0].strip()), float(parts[1].strip())]
except Exception:
    pass

if st.sidebar.button("⇅ החלף כיוון"):
    st.session_state.start_coords, st.session_state.end_coords = st.session_state.end_coords, st.session_state.start_coords
    st.session_state.paths_to_draw = []
    st.session_state.route_summary = None
    st.rerun()

# --- לוגיקת יצירת מסלול ---
if st.sidebar.button("🚀 הצג מסלול", type="primary"):
    if not st.session_state.start_coords or not st.session_state.end_coords:
        st.sidebar.warning("חסר מוצא או יעד!")
    else:
        params = {
            "fromLat": st.session_state.start_coords[0], "fromLon": st.session_state.start_coords[1],
            "toLat": st.session_state.end_coords[0], "toLon": st.session_state.end_coords[1],
            "format": "kml"
        }
        try:
            response = requests.get(BASE_URL, params=params)
            response.raise_for_status()
            root_xml = ET.fromstring(response.content)

            paths = []
            all_lats, all_lons = [], []

            # חילוץ סיכום מסלול
            for elem in root_xml.iter():
                if 'description' in elem.tag and elem.text and "distanceMeters" in elem.text:
                    parts = elem.text.split(',')
                    meters, seconds = 0, 0
                    for p in parts:
                        if "distanceMeters" in p:
                            meters = float(p.split(':')[1].strip())
                        elif "ettInSeconds" in p:
                            seconds = float(p.split(':')[1].strip())
                    st.session_state.route_summary = {
                        "km": round(meters / 1000, 2),
                        "mins": round(seconds / 60)
                    }
                    break

            # חילוץ המסלול וחיבור לבסיס הנתונים
            for placemark in root_xml.iter():
                if 'Placemark' in placemark.tag:
                    segment_name = "ללא שם"
                    for child in placemark.iter():
                        if 'name' in child.tag and child.text:
                            segment_name = child.text.strip()
                            break

                    segment_name_clean = clean_id(segment_name)

                    for child in placemark.iter():
                        if 'coordinates' in child.tag and child.text:
                            coords_text = child.text.strip().split()
                            path_coords = []
                            for point in coords_text:
                                p_parts = point.split(',')
                                if len(p_parts) >= 2:
                                    lat, lon = float(p_parts[1]), float(p_parts[0])  # Folium uses (Lat, Lon)
                                    path_coords.append((lat, lon))
                                    all_lats.append(lat)
                                    all_lons.append(lon)

                            if path_coords:
                                # בניית טקסט קופצת (Tooltip)
                                tooltip_html = f"<b>מזהה:</b> {segment_name}<br>"
                                if not db_data.empty and segment_name_clean in db_data.index:
                                    row = db_data.loc[segment_name_clean]
                                    for col in COLUMNS_TO_DISPLAY:
                                        tooltip_html += f"<b>{col}:</b> {row.get(col, 'N/A')}<br>"
                                else:
                                    tooltip_html += "<i>אין מידע נוסף ב-CSV</i>"

                                paths.append({"coords": path_coords, "tooltip": tooltip_html})

            st.session_state.paths_to_draw = paths
            if all_lats and all_lons:
                st.session_state.map_center = [(min(all_lats) + max(all_lats)) / 2, (min(all_lons) + max(all_lons)) / 2]
                st.session_state.map_zoom = 11

        except Exception as e:
            st.sidebar.error(f"שגיאה בתקשורת או בעיבוד: {e}")

# --- תצוגת אזור מרכזי ---
st.title("מערכת ניווט ומידע GIS 🌍")

if st.session_state.route_summary:
    st.success(
        f"🏁 **מרחק מסלול:** {st.session_state.route_summary['km']} ק\"מ &nbsp; | &nbsp; ⏱️ **זמן משוער:** {st.session_state.route_summary['mins']} דקות")

# יצירת המפה
m = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)

# סמני מוצא ויעד
if st.session_state.start_coords:
    folium.Marker(st.session_state.start_coords, tooltip="מוצא", icon=folium.Icon(color="green")).add_to(m)
if st.session_state.end_coords:
    folium.Marker(st.session_state.end_coords, tooltip="יעד", icon=folium.Icon(color="red")).add_to(m)

# ציור המסלולים והוספת המידע המרחף
for p in st.session_state.paths_to_draw:
    folium.PolyLine(p["coords"], color="purple", weight=5, tooltip=p["tooltip"]).add_to(m)

# הצגת המפה באתר ותפיסת לחיצות
map_data = st_folium(m, height=500, width=1000)

if map_data and map_data.get("last_clicked"):
    clicked_lat = map_data["last_clicked"]["lat"]
    clicked_lon = map_data["last_clicked"]["lng"]
    st.info(f"📍 קליק אחרון במפה: `{clicked_lat}, {clicked_lon}` (אפשר להעתיק לתפריט בצד)")