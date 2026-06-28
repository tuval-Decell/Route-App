import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
import xml.etree.ElementTree as ET
from geopy.geocoders import Nominatim
import pandas as pd

# --- הגדרת עמוד האפליקציה (חייבת להיות פקודת ה-Streamlit הראשונה) ---
st.set_page_config(page_title="Decell Route Generator", page_icon="🚗", layout="wide")


# ==========================================
# --- מנגנון התחברות (Login) ---
# ==========================================
def check_password():
    """מחזיר True אם המשתמש הזין סיסמה נכונה."""

    def password_entered():
        """בודק את הסיסמה שהוזנה."""
        username = st.session_state["username"].strip().lower()
        password = st.session_state["password"]

        if "passwords" in st.secrets and username in st.secrets["passwords"] and str(
                st.secrets["passwords"][username]) == str(password):
            st.session_state["password_correct"] = True
            st.session_state["logged_in_user"] = username
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("התחברות למערכת הניווט 🔒")
        st.text_input("שם משתמש", key="username")
        st.text_input("סיסמה", type="password", key="password")
        st.button("הכנס", on_click=password_entered)
        return False

    elif not st.session_state["password_correct"]:
        st.title("התחברות למערכת הניווט 🔒")
        st.text_input("שם משתמש", key="username")
        st.text_input("סיסמה", type="password", key="password")
        st.button("הכנס", on_click=password_entered)
        st.error("שם משתמש או סיסמה שגויים. נסה שוב או פנה למנהל המערכת.")
        return False

    else:
        return True


if not check_password():
    st.stop()

# ==========================================
# --- הגדרות האפליקציה הראשיות ---
# ==========================================
BASE_URL = "http://routing.decell.com:8080/route"
CSV_FILE_PATH = "database.csv"
ID_COLUMN_NAME = "UserID"
COLUMNS_TO_DISPLAY = ["RoadFuncti", "RoadType", "Flag"]


# --- פונקציות עזר וטעינת נתונים ---
def clean_id(val):
    try:
        if pd.isna(val): return ""
        return str(abs(int(float(val))))
    except (ValueError, TypeError):
        return str(val).strip()


@st.cache_data
def load_database():
    import os
    if not os.path.exists(CSV_FILE_PATH):
        return pd.DataFrame()

    encodings_to_try = ['utf-8-sig', 'cp1255', 'latin-1']
    for enc in encodings_to_try:
        try:
            df = pd.read_csv(CSV_FILE_PATH, encoding=enc, dtype=str)
            df.columns = df.columns.str.strip()
            if ID_COLUMN_NAME in df.columns:
                df[ID_COLUMN_NAME] = df[ID_COLUMN_NAME].apply(clean_id)
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
if 'search_coords' not in st.session_state: st.session_state.search_coords = None
if 'map_center' not in st.session_state: st.session_state.map_center = [31.5, 34.8]
if 'map_zoom' not in st.session_state: st.session_state.map_zoom = 7
if 'paths_to_draw' not in st.session_state: st.session_state.paths_to_draw = []
if 'route_summary' not in st.session_state: st.session_state.route_summary = None
if 'last_clicked' not in st.session_state: st.session_state.last_clicked = None
if 'route_history' not in st.session_state: st.session_state.route_history = []
if 'route_error' not in st.session_state: st.session_state.route_error = None
if 'click_mode_state' not in st.session_state: st.session_state.click_mode_state = "צפייה בלבד"


# --- פונקציות Callback (לפני ריצת הממשק) ---
def add_to_history(start, end, summary, paths, center, zoom):
    new_route = {
        "start": start,
        "end": end,
        "summary": summary,
        "paths": paths,
        "center": center,
        "zoom": zoom
    }
    if st.session_state.route_history and st.session_state.route_history[0]["summary"] == summary:
        return

    st.session_state.route_history.insert(0, new_route)
    if len(st.session_state.route_history) > 5:
        st.session_state.route_history.pop()


def reset_radio_to_view():
    """פונקציה שנקראת רגע לפני שהכפתור מופעל ומאפסת את הרדיו"""
    st.session_state.click_mode_state = "צפייה בלבד"


# --- ממשק משתמש (תפריט צד) ---
st.sidebar.title("הגדרות ניווט 🗺️")

current_user = st.session_state.get("logged_in_user", "אורח")
st.sidebar.markdown(f"👋 שלום, **{current_user.capitalize()}**")

# חיפוש כתובת
search_query = st.sidebar.text_input("חפש עיר או כתובת:")
if st.sidebar.button("חפש במפה"):
    geolocator = Nominatim(user_agent="web_route_app")
    try:
        location = geolocator.geocode(search_query)
        if location:
            st.session_state.map_center = [location.latitude, location.longitude]
            st.session_state.map_zoom = 15
            st.session_state.search_coords = [location.latitude, location.longitude]
            st.sidebar.success("הכתובת נמצאה!")
        else:
            st.sidebar.error("הכתובת לא נמצאה.")
    except Exception as e:
        st.sidebar.error(f"שגיאת חיפוש: {e}")

st.sidebar.markdown("---")
st.sidebar.markdown("**📍 בחירת נקודות מהמפה**")

# חיבור הרדיו לזיכרון באמצעות key
st.sidebar.radio(
    "בחר מה ברצונך לדקור:",
    ["צפייה בלבד", "🟢 קבע נקודת מוצא", "🔴 קבע נקודת יעד"],
    key="click_mode_state"
)

start_text = f"{st.session_state.start_coords[0]:.4f}, {st.session_state.start_coords[1]:.4f}" if st.session_state.start_coords else "לא נבחר"
end_text = f"{st.session_state.end_coords[0]:.4f}, {st.session_state.end_coords[1]:.4f}" if st.session_state.end_coords else "לא נבחר"

st.sidebar.success(f"מוצא: {start_text}")
st.sidebar.error(f"יעד: {end_text}")

if st.sidebar.button("⇅ החלף כיוון"):
    st.session_state.start_coords, st.session_state.end_coords = st.session_state.end_coords, st.session_state.start_coords
    st.session_state.paths_to_draw = []
    st.session_state.route_summary = None
    st.session_state.route_error = None
    st.rerun()

# --- תצוגת היסטוריית מסלולים בתפריט הצד ---
if st.session_state.route_history:
    st.sidebar.markdown("---")
    st.sidebar.markdown("⏳ **מסלולים אחרונים (עד 5):**")

    for idx, hist_route in enumerate(st.session_state.route_history):
        col_text, col_btn = st.sidebar.columns([3, 1])
        with col_text:
            sm = hist_route["summary"]
            st.write(f"**מסלול {idx + 1}:** {sm['km']} ק\"מ ({sm['mins']} דק')")
        with col_btn:
            # שימוש ב-Callback כדי לאפס את הרדיו בלחיצה על 'טען'
            if st.button("טען 🔄", key=f"hist_{idx}", on_click=reset_radio_to_view):
                st.session_state.start_coords = hist_route["start"]
                st.session_state.end_coords = hist_route["end"]
                st.session_state.route_summary = hist_route["summary"]
                st.session_state.paths_to_draw = hist_route["paths"]
                st.session_state.map_center = hist_route["center"]
                st.session_state.map_zoom = hist_route["zoom"]
                st.session_state.search_coords = None
                st.session_state.route_error = None
                st.rerun()

# --- לוגיקת יצירת מסלול ---
# שימוש ב-Callback כדי לאפס את הרדיו בלחיצה על 'הצג מסלול'
if st.sidebar.button("🚀 הצג מסלול", type="primary", on_click=reset_radio_to_view):
    if not st.session_state.start_coords or not st.session_state.end_coords:
        st.sidebar.warning("חסר מוצא או יעד!")
    else:
        st.session_state.search_coords = None
        st.session_state.route_error = None

        params = {
            "fromLat": st.session_state.start_coords[0], "fromLon": st.session_state.start_coords[1],
            "toLat": st.session_state.end_coords[0], "toLon": st.session_state.end_coords[1],
            "format": "kml"
        }
        try:
            response = requests.get(BASE_URL, params=params, timeout=8)
            response.raise_for_status()
            root_xml = ET.fromstring(response.content)

            paths = []
            all_lats, all_lons = [], []
            summary_data = None

            for elem in root_xml.iter():
                if 'description' in elem.tag and elem.text and "distanceMeters" in elem.text:
                    parts = elem.text.split(',')
                    meters, seconds = 0, 0
                    for p in parts:
                        if "distanceMeters" in p:
                            meters = float(p.split(':')[1].strip())
                        elif "ettInSeconds" in p:
                            seconds = float(p.split(':')[1].strip())
                    summary_data = {
                        "km": round(meters / 1000, 2),
                        "mins": round(seconds / 60)
                    }
                    st.session_state.route_summary = summary_data
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

            if summary_data:
                add_to_history(
                    st.session_state.start_coords,
                    st.session_state.end_coords,
                    summary_data,
                    st.session_state.paths_to_draw,
                    st.session_state.map_center,
                    st.session_state.map_zoom
                )

            st.rerun()

        except requests.exceptions.ConnectionError:
            st.toast("🚫 שרת הניווט מנותק", icon="🚫")
            st.session_state.route_error = "connection"
        except requests.exceptions.Timeout:
            st.toast("⏳ השרת לא מגיב", icon="⏳")
            st.session_state.route_error = "timeout"
        except Exception as e:
            st.session_state.route_error = f"general_{e}"

# --- תצוגת אזור מרכזי ---
st.image("Decelllogo.jpg", width=200)
st.title("Decell Route Generator")

if st.session_state.route_error:
    if st.session_state.route_error == "connection":
        st.error("**מצטערים, שרת הניווט לא מחובר כרגע.**\n\nאנא ודאו שהשרת של Decell פועל ונסו שוב מאוחר יותר.")
    elif st.session_state.route_error == "timeout":
        st.error(
            "**הבקשה לשרת הניווט לקחה יותר מדי זמן (Timeout).**\n\nייתכן שהשרת עמוס, מנותק, או שהמסלול ארוך מדי לחישוב כרגע.")
    else:
        actual_error = st.session_state.route_error.replace("general_", "")
        st.error(f"❌ שגיאה כללית בעיבוד המסלול: {actual_error}")

if st.session_state.route_summary:
    st.success(
        f"🏁 **מרחק מסלול:** {st.session_state.route_summary['km']} ק\"מ &nbsp; | &nbsp; ⏱️ **זמן משוער:** {st.session_state.route_summary['mins']} דקות")

m = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)

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

# הצגת המפה באתר ותפיסת לחיצות
map_data = st_folium(m, height=500, width=1000)

if map_data and map_data.get("last_clicked"):
    current_click = map_data["last_clicked"]

    if current_click != st.session_state.last_clicked:
        st.session_state.last_clicked = current_click
        lat = current_click["lat"]
        lon = current_click["lng"]

        if st.session_state.click_mode_state == "🟢 קבע נקודת מוצא":
            st.session_state.start_coords = [lat, lon]
            st.session_state.route_error = None
            st.rerun()
        elif st.session_state.click_mode_state == "🔴 קבע נקודת יעד":
            st.session_state.end_coords = [lat, lon]
            st.session_state.route_error = None
            st.rerun()