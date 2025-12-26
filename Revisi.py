import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import io
import math
import re

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Smart Schedule Dashboard", layout="wide")

# --- 2. FUNGSI UTILITY & SMART LOGIC ---

def parse_duration(val):
    """
    Mengambil angka hari dari string format: '14.8 Jam (0.62 Hari)'
    Output: Integer (pembulatan ke atas)
    """
    try:
        if isinstance(val, (int, float)):
            return math.ceil(val)
        # Cari angka di dalam kurung sebelum kata 'Hari'
        match = re.search(r'\(([\d\.]+) Hari\)', str(val))
        if match:
            days = float(match.group(1))
            return math.ceil(days) if days > 0 else 1
        return 1 # Default minimal 1 hari
    except:
        return 1

def determine_tier(bopd):
    """Menentukan Prioritas berdasarkan Nilai BOPD"""
    try:
        val = float(bopd)
        if val > 10: return 'Tier 1'
        elif val > 5: return 'Tier 2'
        else: return 'Tier 3'
    except:
        return 'Tier 3'

def preprocess_uploaded_data(df):
    """
    Mendeteksi apakah ini Format Excel Baru (Kompleks) atau Format Template Lama.
    Lalu mengubahnya menjadi standar kolom: 
    ['Job_ID', 'Rig_Name', 'Activity', 'Duration_Days', 'Priority_Tier', 'Has_Constraint', 'Constraint_Note']
    """
    cols = df.columns
    new_data = []

    # Cek apakah ini Format Excel DATA_FULL (Format Baru)
    if 'HSRIG_NAME' in cols and 'PROG CODE' in cols:
        st.toast("Mendeteksi Format Data: Full Dynamic Equipment", icon="ℹ️")
        for _, row in df.iterrows():
            # Logic Mapping
            duration = parse_duration(row.get('Total Eksekusi (Jam/Hari)', 1))
            tier = determine_tier(row.get('BOPD_RIGDAYS', 0))
            
            # Cek Constraint
            constraint_detail = str(row.get('Rincian Penilaian Constraint', ''))
            has_constraint = 'Yes' if len(constraint_detail) > 3 and constraint_detail != 'nan' else 'No'
            
            new_data.append({
                'Job_ID': row['PROG CODE'],
                'Rig_Name': row['HSRIG_NAME'],
                'Activity': str(row.get('SITE_ACTION_ITEM', 'Activity'))[:50] + "...", # Potong biar gak kepanjangan
                'Duration_Days': duration,
                'Priority_Tier': tier,
                'Has_Constraint': has_constraint,
                'Constraint_Note': constraint_detail if has_constraint == 'Yes' else '-'
            })
        return pd.DataFrame(new_data)
    
    # Jika Format Template Lama (Standard)
    elif 'Job_ID' in cols and 'Rig_Name' in cols:
        st.toast("Mendeteksi Format Data: Template Standard", icon="ℹ️")
        return df
    
    else:
        st.error("Format kolom Excel tidak dikenali. Pastikan ada 'HSRIG_NAME' atau 'Rig_Name'.")
        return pd.DataFrame()

def generate_dummy_data():
    """Data Dummy Default"""
    data = {
        'Job_ID': ['JOB-001', 'JOB-002', 'JOB-003', 'JOB-004', 'JOB-005'],
        'Rig_Name': ['Rig-Alpha', 'Rig-Beta', 'Rig-Alpha', 'Rig-Gamma', 'Rig-Beta'],
        'Activity': ['Well Service', 'Workover', 'Maintenance', 'Drilling', 'Completion'],
        'Duration_Days': [5, 7, 3, 14, 4],
        'Priority_Tier': ['Tier 1', 'Tier 2', 'Tier 1', 'Tier 3', 'Tier 2'],
        'Has_Constraint': ['No', 'No', 'Yes', 'No', 'Yes'],
        'Constraint_Note': ['-', '-', 'Material Delay', '-', 'Waiting on Weather']
    }
    return pd.DataFrame(data)

def run_smart_schedule(df):
    """
    Engine Penjadwalan:
    1. Sort by Constraint (No dulu), lalu Priority (Tier 1 dulu).
    2. Alokasi waktu tanpa overlap per Rig.
    """
    if df.empty: return df

    # Mapping Priority ke Angka
    priority_map = {'Tier 1': 1, 'Tier 2': 2, 'Tier 3': 3}
    df['Priority_Score'] = df['Priority_Tier'].map(priority_map).fillna(3)
    
    # Sorting Smart: Prioritaskan yang Constraint=No, lalu Tier 1
    df = df.sort_values(by=['Has_Constraint', 'Priority_Score'], ascending=[True, True])

    schedule_list = []
    # Start Date besok
    start_date_base = datetime.now().date() + timedelta(days=1)
    rig_availability = {} 

    for index, row in df.iterrows():
        rig = row['Rig_Name']
        duration = int(row['Duration_Days'])
        
        # Cek ketersediaan rig
        current_start = rig_availability.get(rig, start_date_base)
        current_end = current_start + timedelta(days=duration)
        
        # Update ketersediaan
        rig_availability[rig] = current_end
        
        schedule_list.append({
            'Job_ID': row['Job_ID'],
            'Rig_Name': rig,
            'Activity': row['Activity'],
            'Start_Date': current_start,
            'Finish_Date': current_end,
            'Duration_Days': duration,
            'Priority_Tier': row['Priority_Tier'],
            'Has_Constraint': row['Has_Constraint'],
            'Constraint_Note': row['Constraint_Note']
        })
        
    return pd.DataFrame(schedule_list)

# --- 3. SESSION STATE ---
if 'main_data' not in st.session_state:
    st.session_state['main_data'] = generate_dummy_data()

# --- 4. SIDEBAR INPUT ---
st.sidebar.header("🛠️ Input & Resource Tools")

# Upload Excel
uploaded_file = st.sidebar.file_uploader("1. Import Data Excel (.xlsx)", type=['xlsx', 'xls'])
if uploaded_file is not None:
    try:
        # Baca Excel
        df_raw = pd.read_excel(uploaded_file)
        # Preprocess (Mapping kolom otomatis)
        df_clean = preprocess_uploaded_data(df_raw)
        
        if not df_clean.empty:
            st.session_state['main_data'] = df_clean
            st.sidebar.success(f"Berhasil load {len(df_clean)} pekerjaan!")
            
    except Exception as e:
        st.sidebar.error(f"Error membaca file: {e}")

st.sidebar.markdown("---")

# Manual Input
st.sidebar.subheader("2. Tambah Job Manual")
with st.sidebar.form(key='add_job_form'):
    new_job_id = st.text_input("Job ID", "JOB-NEW-001")
    # Ambil list rig dari data yang ada
    existing_rigs = st.session_state['main_data']['Rig_Name'].unique().tolist()
    if not existing_rigs: existing_rigs = ["Rig-Alpha"]
    
    new_rig = st.selectbox("Pilih Rig / Unit", existing_rigs)
    new_activity = st.text_input("Jenis Aktivitas", "Maintenance")
    new_duration = st.number_input("Durasi (Hari)", min_value=1, value=3)
    new_priority = st.selectbox("Prioritas", ["Tier 1", "Tier 2", "Tier 3"])
    new_constraint = st.selectbox("Ada Constraint?", ["No", "Yes"])
    new_note = st.text_input("Catatan Kendala", "-")
    
    if st.form_submit_button('➕ Tambah'):
        new_row = {
            'Job_ID': new_job_id, 'Rig_Name': new_rig, 'Activity': new_activity,
            'Duration_Days': new_duration, 'Priority_Tier': new_priority,
            'Has_Constraint': new_constraint, 'Constraint_Note': new_note
        }
        st.session_state['main_data'] = pd.concat([st.session_state['main_data'], pd.DataFrame([new_row])], ignore_index=True)
        st.success("Job ditambahkan.")

# --- 5. VISUALISASI UTAMA ---
st.title("🚜 Smart Schedule Dashboard v2.0")

# Run Logic Scheduling
df_scheduled = run_smart_schedule(st.session_state['main_data'])

# Tampilkan Gantt Chart
st.subheader("📅 Timeline Schedule")

color_map = {"Tier 1": "#ff2b2b", "Tier 2": "#ffa500", "Tier 3": "#2bff76"}

fig = px.timeline(
    df_scheduled, 
    x_start="Start_Date", x_end="Finish_Date", y="Rig_Name", 
    color="Priority_Tier", color_discrete_map=color_map,
    hover_data=["Job_ID", "Activity", "Constraint_Note"],
    text="Job_ID",
    title=f"Schedule untuk {len(df_scheduled['Rig_Name'].unique())} Rig Aktif"
)
fig.update_yaxes(categoryorder="total ascending", title="Unit / Rig")
fig.update_layout(height=600, xaxis_title="Tanggal")
st.plotly_chart(fig, use_container_width=True)

# --- 6. INFO & EXPORT ---
c1, c2 = st.columns([2,1])

with c1:
    st.subheader("📋 Detail Data")
    st.dataframe(df_scheduled, height=300)

with c2:
    st.subheader("💡 Insight")
    tier1_ready = len(df_scheduled[(df_scheduled['Priority_Tier']=='Tier 1') & (df_scheduled['Has_Constraint']=='No')])
    constrained = len(df_scheduled[df_scheduled['Has_Constraint']=='Yes'])
    
    st.metric("Tier 1 (Ready to Execute)", f"{tier1_ready} Jobs")
    st.metric("Tertunda (Constraint)", f"{constrained} Jobs", delta_color="inverse")
    
    if constrained > 0:
        st.warning(f"Ada {constrained} pekerjaan pending karena constraint (Material/Cuaca/Izin).")

# Download Button
output = io.BytesIO()
with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df_scheduled.to_excel(writer, index=False)
st.download_button("📥 Download Jadwal (.xlsx)", data=output.getvalue(), file_name='smart_schedule_final.xlsx')