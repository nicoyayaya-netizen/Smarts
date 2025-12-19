import streamlit as st
import pandas as pd
import altair as alt
import requests
from streamlit_lottie import st_lottie

# --- KONFIGURASI HALAMAN ---
st.set_page_config(
    page_title="Smart Schedule - Heavy Oil",
    page_icon="🛢️",
    layout="wide"
)

# --- FUNGSI LOAD LOTTIE ANIMATION ---
def load_lottieurl(url):
    r = requests.get(url)
    if r.status_code != 200:
        return None
    return r.json()

# Load Animasi (Menggunakan URL Lottie Public - Ganti jika punya JSON sendiri)
# Ini adalah animasi machinery/pump generik
lottie_pump = load_lottieurl("https://lottie.host/5a8b7c4d-9e1f-4g2h-3i4j-5k6l7m8n9o0p/example.json") 
# Note: Jika link diatas mati, animasi tidak akan muncul (fallback gracefully).
# Alternatif URL stabil untuk demo machinery:
lottie_machinery = load_lottieurl("https://assets5.lottiefiles.com/packages/lf20_96bovdur.json")

# --- CSS CUSTOM UNTUK HEADER ---
st.markdown("""
    <style>
    .main-title {
        font-size: 3rem;
        font-weight: bold;
        color: #00539C; /* Pertamina Blue approximate */
    }
    .sub-title {
        font-size: 1.2rem;
        color: #555;
    }
    </style>
""", unsafe_allow_html=True)

# --- SIDEBAR (TOOLS & SETTINGS) ---
with st.sidebar:
    st.header("🛠️ Tools & Settings")
    
    # 1. Input Data Excel
    st.subheader("1. Import Data")
    uploaded_file = st.file_uploader("Upload File Excel/CSV", type=['xlsx', 'csv'])
    
    # 2. Setting Parameter
    st.subheader("2. Parameter Filter")
    st.write("Filter data untuk visualisasi:")
    
    # Slider untuk BOPD
    min_bopd = st.slider(
        "Min. BOPD Rig Days",
        min_value=0, max_value=50, value=0, step=1,
        help="Tampilkan Rig dengan BOPD di atas nilai ini"
    )
    
    # Slider untuk Max Hari Eksekusi
    max_days_filter = st.slider(
        "Max. Durasi Eksekusi (Hari)",
        min_value=1, max_value=100, value=90, step=1,
        help="Tampilkan job yang durasinya di bawah nilai ini"
    )

    st.info("💡 Logic: Prioritas tetap diurutkan berdasarkan Waktu Eksekusi Tercepat (Constraint Minimal).")

# --- HEADER LAYOUT (JUDUL, ANIMASI, LOGO) ---
col_header_1, col_header_2, col_header_3 = st.columns([1, 4, 1])

with col_header_1:
    # Menampilkan Animasi Pompa Sucker Rod Pump (SRP)
    if lottie_machinery:
        st_lottie(lottie_machinery, height=100, key="pump_anim")
    else:
        st.write("⚙️") # Fallback icon

with col_header_2:
    st.markdown('<div class="main-title">SMART SCHEDULE</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Site Readiness Heavy Oil - Integrated Dashboard</div>', unsafe_allow_html=True)

with col_header_3:
    # Menampilkan Logo Pertamina (Pastikan file 'logo.png' ada, atau gunakan URL)
    # Ganti "logo.png" dengan path file Anda, atau URL logo online
    try:
        st.image("https://upload.wikimedia.org/wikipedia/commons/b/b2/Pertamina_Logo.svg", width=150)
    except:
        st.warning("Logo not found")

st.divider()

# --- LOGIC PEMROSESAN DATA ---
if uploaded_file is not None:
    try:
        # Baca file
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)

        # 1. Parsing Durasi (Format "1620 Jam" -> 1620)
        # Mengambil angka pertama dari string
        df['Duration_Hours'] = df['Total Eksekusi (Jam/Hari)'].astype(str).str.extract(r'(\d+)').astype(float)
        
        # 2. Parsing Tanggal
        df['Start_Date'] = pd.to_datetime(df['EXECUTION_PLAN_GENERAL'])
        df['End_Date'] = df['Start_Date'] + pd.to_timedelta(df['Duration_Hours'], unit='h')

        # 3. Filter Data Berdasarkan Setting Sidebar
        df_filtered = df[
            (df['BOPD_RIGDAYS'] >= min_bopd) & 
            ((df['Duration_Hours']/24) <= max_days_filter)
        ]

        # 4. Sorting / Logic Prioritas Utama
        # Logic: Durasi Terpendek (Ascending) -> Prioritas Utama
        # Secondary Sort: BOPD Tertinggi (Descending)
        df_filtered = df_filtered.sort_values(by=['Duration_Hours', 'BOPD_RIGDAYS'], ascending=[True, False])

        # --- VISUALISASI DASHBOARD ---

        # Layout Metrik Ringkas
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Jobs Loaded", len(df_filtered))
        m2.metric("Avg Duration (Hours)", f"{df_filtered['Duration_Hours'].mean():.1f}")
        m3.metric("Total Potential BOPD", f"{df_filtered['BOPD_RIGDAYS'].sum():.1f}")

        # CHART 1: GANTT CHART (PLANNING & SCHEDULING)
        st.subheader("📅 Execution Planning & Scheduling")
        
        # Tooltip data
        df_filtered['Duration_Text'] = df_filtered['Total Eksekusi (Jam/Hari)']
        df_filtered['Start_String'] = df_filtered['Start_Date'].dt.strftime('%Y-%m-%d %H:%M')
        
        gantt_chart = alt.Chart(df_filtered).mark_bar(cornerRadius=3).encode(
            x=alt.X('Start_Date', title='Waktu Pelaksanaan'),
            x2='End_Date',
            # Y Axis diurutkan berdasarkan Duration_Hours (Ascending) -> Shortest job on TOP
            y=alt.Y('HSRIG_NAME', 
                    sort=alt.EncodingSortField(field="Duration_Hours", order="ascending"), 
                    title='Rig Name (Prioritas: Cepat -> Lambat)'),
            color=alt.Color('BOPD_RIGDAYS', scale=alt.Scale(scheme='goldorange'), title='BOPD Impact'),
            tooltip=[
                alt.Tooltip('HSRIG_NAME', title='Rig'),
                alt.Tooltip('Duration_Text', title='Durasi'),
                alt.Tooltip('BOPD_RIGDAYS', title='BOPD'),
                alt.Tooltip('Total Well Execution', title='Well Score'),
                alt.Tooltip('Rincian Penilaian Constraint', title='Constraint'),
                alt.Tooltip('Start_String', title='Start Plan')
            ]
        ).properties(
            height=500,
            width='container'
        ).interactive()

        st.altair_chart(gantt_chart, use_container_width=True)

        # CHART 2: STRATEGIC MATRIX
        st.subheader("🎯 Strategic Matrix: Value (BOPD) vs Constraint (Time)")
        
        matrix_chart = alt.Chart(df_filtered).mark_circle(size=120).encode(
            x=alt.X('Duration_Hours', title='Waktu Eksekusi (Jam) - Constraint'),
            y=alt.Y('BOPD_RIGDAYS', title='BOPD Rig Days - Value'),
            color=alt.Color('Total Well Execution', scale=alt.Scale(scheme='viridis'), title='Well Score'),
            tooltip=['HSRIG_NAME', 'Duration_Text', 'BOPD_RIGDAYS', 'Total Well Execution']
        ).properties(
            height=400,
            width='container'
        ).interactive()
        
        # Menambahkan garis rata-rata untuk membagi kuadran
        rule_x = alt.Chart(df_filtered).mark_rule(color='red', strokeDash=[5,5]).encode(x='mean(Duration_Hours)')
        rule_y = alt.Chart(df_filtered).mark_rule(color='red', strokeDash=[5,5]).encode(y='mean(BOPD_RIGDAYS)')

        st.altair_chart(matrix_chart + rule_x + rule_y, use_container_width=True)

        # Tampilkan Data Tabular
        with st.expander("Lihat Data Detail"):
            st.dataframe(df_filtered[['HSRIG_NAME', 'Total Eksekusi (Jam/Hari)', 'BOPD_RIGDAYS', 'Total Well Execution', 'EXECUTION_PLAN_GENERAL', 'Rincian Penilaian Constraint']])

    except Exception as e:
        st.error(f"Terjadi kesalahan saat memproses data: {e}")
        st.warning("Pastikan format kolom Excel sesuai: 'Total Eksekusi (Jam/Hari)', 'BOPD_RIGDAYS', 'HSRIG_NAME', 'EXECUTION_PLAN_GENERAL'")

else:
    # Tampilan awal jika belum upload file
    st.info("👋 Silakan upload file Excel 'Integrated_Minor_Action' melalui panel di sebelah kiri (Sidebar).")
    
    # Placeholder visual agar tidak kosong
    st.markdown("""
    <div style="text-align: center; color: #888; margin-top: 50px;">
        <h3>Menunggu Input Data...</h3>
        <p>Gunakan tools di sidebar untuk memulai analisis Smart Schedule.</p>
    </div>
    """, unsafe_allow_html=True)