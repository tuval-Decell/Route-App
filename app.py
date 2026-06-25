import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
import xml.etree.ElementTree as ET
from geopy.geocoders import Nominatim
import pandas as pd

# --- הגדרות ---
BASE_URL = "http://routing.decell.com:8080/route"
CSV_FILE_PATH = "database.csv"
ID_COLUMN_NAME = "UserID"
COLUMNS_TO_DISPLAY = ["RoadFuncti", "RoadType", "Flag"]

st.set_page_config(page_title="Route Generator", layout="wide")


# --- פונקציות עזר וטעינת נתונים ---
def clean_id(val):
    try:
        if pd.isna(val): return ""
        return str(abs(int(float(val))))
    except (ValueError, TypeError):
        return str(val).strip()


@st.cache_data
def load_database():
    encodings_to_try = ['utf-8-sig', 'cp1255', 'latin-1']
    for enc in encodings_to_try:
        try:
            df = pd.read_csv(CSV_FILE_PATH, encoding=enc, dtype=str)
            df.columns = df.columns.str.strip()
            if ID_COLUMN_NAME in df.columns:
                df[ID_COLUMN_NAME] = df[ID_COLUMN_NAME].apply(clean_id)
                # מניעת כפילויות במזהים כדי למנוע שגיאות שליפה
                df.drop_duplicates(subset=[ID_COLUMN_NAME], keep='first', inplace=True)
                df.set_index(ID_COLUMN_NAME, inplace=True)
                return df
        except Exception:
            continue
    return pd.DataFrame()


db_data = load_database()

# --- ניהול זיכרון של האפליקציה (Session State) ---
if 'start_coords' not in st.session_state: st.session_state.start_coords = None
if 'end_coords' not in st.session_state: st.session_state.end_coords = None
if 'search_coords' not in st.session_state: st.session_state.search_coords = None  # סמן החיפוש חזר!
if 'map_center' not in st.session_state: st.session_state.map_center = [31.5, 34.8]
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 7
if 'paths_to_draw' not in st.session_state: st.session_state.paths_to_draw = []
if 'route_summary' not in st.session_state: st.session_state.route_summary = None
if 'last_clicked' not in st.session_state: st.session_state.last_clicked = None

# --- ממשק משתמש (תפריט צד) ---
st.sidebar.title("הגדרות ניווט 🗺️")

# חיווי סטטוס מסד הנתונים
if not db_data.empty:
    st.sidebar.success(f"✅ מסד נתונים מחובר ({len(db_data)} רשומות)")
else:
    st.sidebar.error("❌ לא נמצאו נתונים בקובץ ה-CSV")

# חיפוש כתובת
search_query = st.sidebar.text_input("חפש עיר או כתובת:")
if st.sidebar.button("חפש במפה"):
    geolocator = Nominatim(user_agent="web_route_app")
    try:
        location = geolocator.geocode(search_query)
        if location:
            st.session_state.map_center = [location.latitude, location.longitude]
            st.session_state.map_zoom = 15
            st.session_state.search_coords = [location.latitude, location.longitude]  # שמירת מיקום החיפוש
            st.sidebar.success("הכתובת נמצאה!")
        else:
            st.sidebar.error("הכתובת לא נמצאה.")
    except Exception as e:
        st.sidebar.error(f"שגיאת חיפוש: {e}")

st.sidebar.markdown("---")
st.sidebar.markdown("**📍 בחירת נקודות מהמפה**")

click_mode = st.sidebar.radio(
    "בחר מה ברצונך לדקור:",
    ["צפייה בלבד", "🟢 קבע נקודת מוצא", "🔴 קבע נקודת יעד"]
)

start_text = f"{st.session_state.start_coords[0]:.4f}, {st.session_state.start_coords[1]:.4f}" if st.session_state.start_coords else "לא נבחר"
end_text = f"{st.session_state.end_coords[0]:.4f}, {st.session_state.end_coords[1]:.4f}" if st.session_state.end_coords else "לא נבחר"

st.sidebar.success(f"מוצא: {start_text}")
st.sidebar.error(f"יעד: {end_text}")

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
        st.session_state.search_coords = None  # העלמת סמן החיפוש ברגע יצירת מסלול

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
                                    lat, lon = float(p_parts[1]), float(p_parts[0])
                                    path_coords.append((lat, lon))
                                    all_lats.append(lat)
                                    all_lons.append(lon)

                            if path_coords:
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

m = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)

# הצגת סמן חיפוש אפור אם קיים
if st.session_state.search_coords:
    folium.Marker(
        st.session_state.search_coords,
        tooltip="תוצאת חיפוש",
        icon=folium.Icon(color="gray", icon="info-sign")
    ).add_to(m)

if st.session_state.start_coords:
    folium.Marker(st.session_state.start_coords, tooltip="מוצא", icon=folium.Icon(color="green")).add_to(m)
if st.session_state.end_coords:
    folium.Marker(st.session_state.end_coords, tooltip="יעד", icon=folium.Icon(color="red")).add_to(m)

for p in st.session_state.paths_to_draw:
    folium.PolyLine(p["coords"], color="purple", weight=5, tooltip=p["tooltip"]).add_to(m)

map_data = st_folium(m, height=500, width=1000)

if map_data and map_data.get("last_clicked"):
    current_click = map_data["last_clicked"]

    if current_click != st.session_state.last_clicked:
        st.session_state.last_clicked = current_click
        lat = current_click["lat"]
        lon = current_click["lng"]

        if click_mode == "🟢 קבע נקודת מוצא":
            st.session_state.start_coords = [lat, lon]
            st.rerun()
        elif click_mode == "🔴 קבע נקודת יעד":
            st.session_state.end_coords = [lat, lon]
            st.rerun()