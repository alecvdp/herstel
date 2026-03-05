import streamlit as st
import pandas as pd
import uuid
import json
import os
import re
from datetime import date, datetime, time
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────

DATA_DIR = Path("data")
LOG_FILE = DATA_DIR / "meetings_log.csv"
CONFIG_FILE = DATA_DIR / "config.json"

LOG_COLUMNS = ["id", "date", "time", "meeting", "fellowship", "location", "notes"]

DEFAULT_CONFIG = {
    "sobriety_date": "2025-05-17",
    "fellowships": [
        "AA",
        "Recovery Dharma",
        "Secular AA",
        "Psychedelics in Recovery",
        "NA",
        "Other",
    ],
}


# ── Data I/O ─────────────────────────────────────────────────────────────────


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_config() -> dict:
    ensure_data_dir()
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    ensure_data_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def load_log() -> pd.DataFrame:
    ensure_data_dir()
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > 0:
        try:
            df = pd.read_csv(LOG_FILE, dtype=str).fillna("")
            for col in LOG_COLUMNS:
                if col not in df.columns:
                    df[col] = ""
            return df[LOG_COLUMNS]
        except Exception:
            return pd.DataFrame(columns=LOG_COLUMNS)
    return pd.DataFrame(columns=LOG_COLUMNS)


def save_log(df: pd.DataFrame):
    ensure_data_dir()
    df[LOG_COLUMNS].to_csv(LOG_FILE, index=False)


# ── Helpers ──────────────────────────────────────────────────────────────────


def compute_day_number(meeting_date: date, sobriety_date: date) -> int:
    return (meeting_date - sobriety_date).days + 1


def generate_id() -> str:
    return str(uuid.uuid4())


def parse_date(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def df_for_display(df: pd.DataFrame, sobriety_date: date) -> pd.DataFrame:
    """Add computed day_number column and sort for display."""
    if df.empty:
        display = df.copy()
        display.insert(1, "day", pd.Series(dtype="int"))
        return display
    display = df.copy()
    display["day"] = display["date"].apply(
        lambda d: compute_day_number(parse_date(d), sobriety_date)
    )
    # Reorder: date, day, time, meeting, fellowship, location, notes (hide id)
    display = display[["date", "day", "time", "meeting", "fellowship", "location", "notes", "id"]]
    display = display.sort_values("date", ascending=False).reset_index(drop=True)
    return display


def df_to_markdown(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False)


def normalize_date(val: str) -> str:
    """Convert various date formats to YYYY-MM-DD."""
    val = val.strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def normalize_time(val: str) -> str:
    """Convert various time formats to HH:MM (24-hour)."""
    val = val.strip()
    # Already 24-hour like "19:00"
    m = re.match(r"^(\d{1,2}:\d{2})\s*$", val)
    if m:
        return m.group(1).zfill(5)
    # 12-hour with AM/PM like "7:00 PM"
    m = re.match(r"^(\d{1,2}:\d{2})\s*(AM|PM)$", val, re.IGNORECASE)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2).upper()}", "%I:%M %p").strftime("%H:%M")
        except ValueError:
            pass
    # Embedded 24-hour time with extra text like "18:00 (Euro time)"
    m = re.match(r"^(\d{1,2}:\d{2})", val)
    if m:
        return m.group(1).zfill(5)
    return ""


def infer_fellowship(meeting_name: str) -> str:
    """Guess fellowship from meeting name keywords."""
    name = meeting_name.lower()
    if "recovery dharma" in name or name.startswith("rd:") or name.startswith("rd ") or "non dukkha" in name or "non dhukka" in name or "cling free rd" in name or "northstar rd" in name or "hollow bones zen" in name:
        return "Recovery Dharma"
    if "pir:" in name or "pir " in name or "psychedelics in recovery" in name:
        return "Psychedelics in Recovery"
    if "lifering" in name:
        return "LifeRing"
    if "aca:" in name or "aca " in name:
        return "ACA"
    if "secular" in name or "agnostic" in name or "freethinker" in name or "humanist" in name or "without a prayer" in name or "omagod" in name or "satanic" in name:
        return "Secular AA"
    return "AA"


def parse_import_csv(uploaded_file) -> tuple[pd.DataFrame | None, list[str]]:
    """Parse an uploaded CSV and return (mapped_df, warnings)."""
    warnings = []
    try:
        raw = pd.read_csv(uploaded_file, dtype=str).fillna("")
    except Exception as e:
        return None, [f"Failed to read CSV: {e}"]

    # Clean column names
    raw.columns = [c.strip() for c in raw.columns]

    # Map columns by common names
    col_map = {}
    for col in raw.columns:
        cl = col.lower().strip()
        if cl in ("date",):
            col_map["date"] = col
        elif cl in ("meeting name", "meeting", "name"):
            col_map["meeting"] = col
        elif cl in ("time",):
            col_map["time"] = col
        elif cl in ("location", "place", "venue"):
            col_map["location"] = col
        elif cl in ("notes", "note", "comments"):
            col_map["notes"] = col
        elif cl in ("fellowship", "program", "type"):
            col_map["fellowship"] = col

    if "date" not in col_map:
        return None, ["Could not find a 'Date' column in the CSV."]
    if "meeting" not in col_map:
        return None, ["Could not find a 'Meeting Name' or 'Meeting' column in the CSV."]

    rows = []
    for i, row in raw.iterrows():
        # Clean embedded newlines from all fields
        cleaned = {k: str(row[v]).replace("\n", "").strip() if v else "" for k, v in col_map.items()}

        d = normalize_date(cleaned.get("date", ""))
        if not d:
            warnings.append(f"Row {i + 2}: Could not parse date '{cleaned.get('date', '')}'")
            continue

        t = normalize_time(cleaned.get("time", ""))
        if not t:
            warnings.append(f"Row {i + 2}: Could not parse time '{cleaned.get('time', '')}', using 00:00")
            t = "00:00"

        meeting = cleaned.get("meeting", "").strip()
        if not meeting:
            warnings.append(f"Row {i + 2}: Empty meeting name, skipping")
            continue

        fellowship = cleaned.get("fellowship", "").strip()
        if not fellowship:
            fellowship = infer_fellowship(meeting)

        rows.append({
            "id": generate_id(),
            "date": d,
            "time": t,
            "meeting": meeting,
            "fellowship": fellowship,
            "location": cleaned.get("location", ""),
            "notes": cleaned.get("notes", ""),
        })

    if not rows:
        return None, warnings + ["No valid rows found in CSV."]

    return pd.DataFrame(rows, columns=LOG_COLUMNS), warnings


# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Herstel",
    page_icon="\U0001f331",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state init ───────────────────────────────────────────────────────

if "log_df" not in st.session_state:
    st.session_state.log_df = load_log()
if "config" not in st.session_state:
    st.session_state.config = load_config()


def refresh_log():
    st.session_state.log_df = load_log()


def refresh_config():
    st.session_state.config = load_config()


# ── Sidebar ──────────────────────────────────────────────────────────────────

config = st.session_state.config
sobriety_date = date.fromisoformat(config["sobriety_date"])
days_sober = compute_day_number(date.today(), sobriety_date)

st.sidebar.title("Herstel")
st.sidebar.caption("Recovery Meetings Tracker")
st.sidebar.metric("Days of Recovery", days_sober)

page = st.sidebar.radio(
    "Navigate",
    ["Meeting Log", "Meeting Catalog", "Settings"],
    label_visibility="collapsed",
)


# ── Meeting Log View ─────────────────────────────────────────────────────────


def render_meeting_log():
    st.header("Meeting Log")

    df = st.session_state.log_df
    fellowships = config["fellowships"]

    # Sobriety banner
    st.markdown(f"**Today is Day {days_sober} of your recovery.**")

    # ── Add new meeting ──────────────────────────────────────────────────
    with st.expander("Add New Meeting"):
        with st.form("add_meeting_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                new_date = st.date_input("Date", value=date.today())
                new_meeting = st.text_input("Meeting Name")
                new_fellowship = st.selectbox("Fellowship", options=fellowships)
            with col2:
                new_time = st.time_input("Time", value=time(19, 0))
                new_location = st.text_input("Location")
                new_notes = st.text_area("Notes", max_chars=500, height=68)

            submitted = st.form_submit_button("Add Meeting")
            if submitted:
                if not new_meeting.strip():
                    st.error("Meeting name is required.")
                else:
                    new_row = pd.DataFrame(
                        [
                            {
                                "id": generate_id(),
                                "date": new_date.strftime("%Y-%m-%d"),
                                "time": new_time.strftime("%H:%M"),
                                "meeting": new_meeting.strip(),
                                "fellowship": new_fellowship,
                                "location": new_location.strip(),
                                "notes": new_notes.strip(),
                            }
                        ]
                    )
                    df = pd.concat([df, new_row], ignore_index=True)
                    save_log(df)
                    refresh_log()
                    st.toast("Meeting added!")
                    st.rerun()

    # ── Filters ──────────────────────────────────────────────────────────
    display_df = df_for_display(df, sobriety_date)

    if not df.empty:
        with st.expander("Filters"):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                unique_fellowships = sorted(df["fellowship"].unique())
                filter_fellowship = st.multiselect(
                    "Fellowship", options=unique_fellowships
                )
            with fc2:
                dates = df["date"].apply(parse_date)
                filter_start = st.date_input(
                    "From", value=dates.min(), min_value=dates.min(), max_value=dates.max()
                )
                filter_end = st.date_input(
                    "To", value=dates.max(), min_value=dates.min(), max_value=dates.max()
                )
            with fc3:
                filter_name = st.text_input("Search meeting name")

            # Apply filters
            if filter_fellowship:
                display_df = display_df[display_df["fellowship"].isin(filter_fellowship)]
            display_df = display_df[
                (display_df["date"] >= filter_start.strftime("%Y-%m-%d"))
                & (display_df["date"] <= filter_end.strftime("%Y-%m-%d"))
            ]
            if filter_name:
                display_df = display_df[
                    display_df["meeting"].str.contains(filter_name, case=False, na=False)
                ]

    # ── Display table ────────────────────────────────────────────────────
    if df.empty:
        st.info("No meetings logged yet. Add your first one above!")
    else:
        st.caption(f"Showing {len(display_df)} meeting(s)")

        edited = st.data_editor(
            display_df,
            use_container_width=True,
            num_rows="fixed",
            column_order=["date", "day", "time", "meeting", "fellowship", "location", "notes"],
            disabled=["day"],
            column_config={
                "date": st.column_config.TextColumn("Date"),
                "day": st.column_config.NumberColumn("Day #", help="Day of recovery"),
                "time": st.column_config.TextColumn("Time"),
                "meeting": st.column_config.TextColumn("Meeting"),
                "fellowship": st.column_config.SelectboxColumn(
                    "Fellowship", options=fellowships
                ),
                "location": st.column_config.TextColumn("Location"),
                "notes": st.column_config.TextColumn("Notes"),
            },
            key="log_editor",
        )

        # Detect edits and save
        if not edited.equals(display_df):
            # Merge edits back into the full df using the id column
            updated = edited[["id", "date", "time", "meeting", "fellowship", "location", "notes"]]
            # Drop rows that were in the original and replace with edited versions
            original_ids = updated["id"].tolist()
            remaining = df[~df["id"].isin(original_ids)]
            merged = pd.concat([remaining, updated], ignore_index=True)
            save_log(merged)
            refresh_log()
            st.toast("Changes saved!")
            st.rerun()

        # ── Delete ───────────────────────────────────────────────────────
        st.markdown("---")
        del_col1, del_col2 = st.columns([3, 1])
        with del_col1:
            if not display_df.empty:
                delete_options = [
                    f"{row['date']} — {row['meeting']}"
                    for _, row in display_df.iterrows()
                ]
                selected_to_delete = st.multiselect(
                    "Select meetings to delete", options=delete_options
                )
        with del_col2:
            st.markdown("")  # spacing
            st.markdown("")
            if st.button("Delete Selected", type="secondary"):
                if selected_to_delete:
                    # Map display labels back to ids
                    idx_map = {
                        f"{row['date']} — {row['meeting']}": row["id"]
                        for _, row in display_df.iterrows()
                    }
                    ids_to_delete = [idx_map[s] for s in selected_to_delete if s in idx_map]
                    df = df[~df["id"].isin(ids_to_delete)]
                    save_log(df)
                    refresh_log()
                    st.toast(f"Deleted {len(ids_to_delete)} meeting(s).")
                    st.rerun()

    # ── Export ───────────────────────────────────────────────────────────
    if not df.empty:
        export_df = df_for_display(df, sobriety_date).drop(columns=["id"])
        with st.expander("Export"):
            ec1, ec2, ec3 = st.columns(3)
            with ec1:
                st.download_button(
                    "Download CSV",
                    data=export_df.to_csv(index=False).encode("utf-8"),
                    file_name="meetings_log.csv",
                    mime="text/csv",
                )
            with ec2:
                st.download_button(
                    "Download JSON",
                    data=export_df.to_json(orient="records", indent=2).encode("utf-8"),
                    file_name="meetings_log.json",
                    mime="application/json",
                )
            with ec3:
                st.download_button(
                    "Download Markdown",
                    data=df_to_markdown(export_df).encode("utf-8"),
                    file_name="meetings_log.md",
                    mime="text/markdown",
                )


# ── Meeting Catalog View ─────────────────────────────────────────────────────


def render_meeting_catalog():
    st.header("Meeting Catalog")

    df = st.session_state.log_df

    if df.empty:
        st.info("No meetings logged yet. Visit the Meeting Log to add some.")
        return

    # Summary metrics
    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        st.metric("Unique Meetings", df["meeting"].nunique())
    with mc2:
        st.metric("Fellowships", df["fellowship"].nunique())
    with mc3:
        st.metric("Total Meetings Attended", len(df))

    # Aggregation
    catalog = (
        df.groupby(["meeting", "fellowship"])
        .agg(
            times_attended=("id", "count"),
            typical_days=(
                "date",
                lambda x: ", ".join(
                    sorted(
                        set(pd.to_datetime(x).dt.day_name()),
                        key=lambda d: [
                            "Monday", "Tuesday", "Wednesday", "Thursday",
                            "Friday", "Saturday", "Sunday",
                        ].index(d),
                    )
                ),
            ),
            typical_times=("time", lambda x: ", ".join(sorted(set(x)))),
            location=("location", "last"),
        )
        .reset_index()
        .sort_values("times_attended", ascending=False)
        .reset_index(drop=True)
    )

    st.dataframe(
        catalog,
        use_container_width=True,
        column_config={
            "meeting": st.column_config.TextColumn("Meeting"),
            "fellowship": st.column_config.TextColumn("Fellowship"),
            "times_attended": st.column_config.NumberColumn("Times Attended"),
            "typical_days": st.column_config.TextColumn("Typical Day(s)"),
            "typical_times": st.column_config.TextColumn("Typical Time(s)"),
            "location": st.column_config.TextColumn("Location"),
        },
        hide_index=True,
    )

    # Export
    with st.expander("Export Catalog"):
        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            st.download_button(
                "Download CSV",
                data=catalog.to_csv(index=False).encode("utf-8"),
                file_name="meeting_catalog.csv",
                mime="text/csv",
            )
        with ec2:
            st.download_button(
                "Download JSON",
                data=catalog.to_json(orient="records", indent=2).encode("utf-8"),
                file_name="meeting_catalog.json",
                mime="application/json",
            )
        with ec3:
            st.download_button(
                "Download Markdown",
                data=df_to_markdown(catalog).encode("utf-8"),
                file_name="meeting_catalog.md",
                mime="text/markdown",
            )


# ── Settings View ────────────────────────────────────────────────────────────


def render_settings():
    st.header("Settings")

    # Sobriety date
    st.subheader("Sobriety Date")
    current_sobriety = date.fromisoformat(config["sobriety_date"])
    new_sobriety = st.date_input(
        "Your sobriety date",
        value=current_sobriety,
        help="Day 1 of your recovery. Day numbers are calculated from this date.",
    )
    if new_sobriety != current_sobriety:
        config["sobriety_date"] = new_sobriety.strftime("%Y-%m-%d")
        save_config(config)
        st.session_state.config = config
        st.toast("Sobriety date updated!")
        st.rerun()

    # Fellowship list
    st.subheader("Fellowships")
    st.caption("Manage the list of recovery fellowships available in dropdown menus.")

    for i, f in enumerate(config["fellowships"]):
        fc1, fc2 = st.columns([4, 1])
        with fc1:
            st.text(f)
        with fc2:
            if st.button("Remove", key=f"remove_{i}"):
                config["fellowships"].pop(i)
                save_config(config)
                st.session_state.config = config
                st.rerun()

    with st.form("add_fellowship_form", clear_on_submit=True):
        new_f = st.text_input("Add a fellowship")
        if st.form_submit_button("Add"):
            if new_f.strip() and new_f.strip() not in config["fellowships"]:
                config["fellowships"].append(new_f.strip())
                save_config(config)
                st.session_state.config = config
                st.toast(f"Added '{new_f.strip()}'")
                st.rerun()
            elif new_f.strip() in config["fellowships"]:
                st.warning("That fellowship already exists.")

    # Import CSV
    st.subheader("Import CSV")
    st.caption("Import meetings from an existing CSV file. The importer will try to map columns automatically.")

    uploaded = st.file_uploader("Choose a CSV file", type="csv", key="csv_import")
    if uploaded is not None:
        import_df, import_warnings = parse_import_csv(uploaded)

        if import_warnings:
            with st.expander(f"{len(import_warnings)} warning(s)"):
                for w in import_warnings:
                    st.warning(w)

        if import_df is not None:
            st.caption(f"Found {len(import_df)} meetings to import")
            preview = df_for_display(import_df, sobriety_date).drop(columns=["id"])
            st.dataframe(preview, use_container_width=True, hide_index=True)

            # Check for new fellowships
            existing_fellowships = set(config["fellowships"])
            imported_fellowships = set(import_df["fellowship"].unique())
            new_fellowships = imported_fellowships - existing_fellowships
            if new_fellowships:
                st.info(f"New fellowships found: {', '.join(sorted(new_fellowships))}. They will be added to your fellowship list.")

            ic1, ic2 = st.columns(2)
            with ic1:
                if st.button("Import (append to existing data)"):
                    df = st.session_state.log_df
                    merged = pd.concat([df, import_df], ignore_index=True)
                    save_log(merged)
                    if new_fellowships:
                        config["fellowships"].extend(sorted(new_fellowships))
                        save_config(config)
                        st.session_state.config = config
                    refresh_log()
                    st.toast(f"Imported {len(import_df)} meetings!")
                    st.rerun()
            with ic2:
                if st.button("Import (replace all data)"):
                    save_log(import_df)
                    if new_fellowships:
                        config["fellowships"].extend(sorted(new_fellowships))
                        save_config(config)
                        st.session_state.config = config
                    refresh_log()
                    st.toast(f"Replaced data with {len(import_df)} imported meetings!")
                    st.rerun()

    # Data management
    st.subheader("Data Management")
    st.warning("This will permanently delete all your meeting log data.")
    confirm = st.checkbox("I understand this will delete all meeting data")
    if st.button("Reset All Data", disabled=not confirm):
        save_log(pd.DataFrame(columns=LOG_COLUMNS))
        refresh_log()
        st.toast("All meeting data has been reset.")
        st.rerun()


# ── Route ────────────────────────────────────────────────────────────────────

if page == "Meeting Log":
    render_meeting_log()
elif page == "Meeting Catalog":
    render_meeting_catalog()
elif page == "Settings":
    render_settings()
