import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import io
import math
import re

# --- 1. CONFIG ---
st.set_page_config(page_title="Smart Scheduler - Fix Calculation", layout="wide")

# --- 2. UTILITY FUNCTIONS ---
def parse_duration(val):
    try:
        if isinstance(val, (int, float)): return math.ceil(val)
        match = re.search(r'\(([\d\.]+) Hari\)', str(val))
        if match: return math.ceil(float(match.group(1)))
        return 1
    except: return 1

def determine_category(duration):
    return 'MAJOR' if duration > 1 else 'MINOR'

def determine_tier_label(bopd):
    if bopd > 10: return "Tier 1"
    elif bopd >= 5: return "Tier 2"
    else: return "Tier 3"

def generate_major_minor_color(category, bopd, max_bopd):
    if max_bopd == 0: max_bopd = 1
    ratio = bopd / max_bopd
    ratio = max(0.2, min(ratio, 1)) 
    white_mix = int(255 * (1 - ratio))
    
    if category == 'MAJOR':
        return f'rgb(255, {white_mix}, {white_mix})' # MERAH
    else: 
        green_base = 180 + int(75 * (1-ratio))
        mix = int(255 * (1 - ratio))
        return f'rgb({mix}, {green_base}, {mix})' # HIJAU

def preprocess_data(df):
    new_data = []
    df.columns = [c.strip() for c in df.columns]

    df['Original_Index'] = df.index 

    # READ EXCEL (LOGIC MURNI DARI DATA)
    if 'HSRIG_NAME' in df.columns:
        for _, row in df.iterrows():
            dur = parse_duration(row.get('Total Eksekusi (Jam/Hari)', 1))
            
            # Logic BOPD
            raw_bopd = row.get('BOPD_RIGDAYS', 0)
            try:
                bopd = float(raw_bopd)
            except:
                bopd = 0.0

            const_txt = str(row.get('Rincian Penilaian Constraint', ''))
            has_cons = 'Yes' if len(const_txt) > 3 and const_txt.lower() != 'nan' else 'No'
            
            new_data.append({
                'Job_ID': row.get('PROG CODE', 'UNK'),
                'Rig_Name': row.get('HSRIG_NAME', 'Unknown-Rig'),
                'Activity': str(row.get('SITE_ACTION_ITEM', 'Activity'))[:50],
                'Duration_Days': dur,
                'Original_Duration': dur,
                'Unit_Count': 1,
                'BOPD_Value': bopd, 
                'Tier_Label': determine_tier_label(bopd),
                'Job_Category': determine_category(dur),
                'Has_Constraint': has_cons,
                'Constraint_Note': const_txt if has_cons == 'Yes' else '-',
                'Original_Index': row['Original_Index'], 
                'Source': 'Excel' 
            })
            
    # READ MANUAL
    elif 'Rig_Name' in df.columns:
        if 'Rig Name' in df.columns: df['Rig_Name'] = df['Rig Name']
        if 'Job ID' in df.columns: df['Job_ID'] = df['Job ID']
        if 'Duration' in df.columns: df['Duration_Days'] = df['Duration']
        
        for idx, row in df.iterrows():
            eff_dur = int(row.get('Duration_Days', 1)) 
            raw_dur = int(row.get('Original_Duration', eff_dur))
            bopd = float(row.get('BOPD_Value', 0))
            
            new_data.append({
                'Job_ID': row.get('Job_ID', '-'),
                'Rig_Name': row.get('Rig_Name', '-'),
                'Activity': row.get('Activity', 'Manual Job'),
                'Duration_Days': eff_dur,
                'Original_Duration': raw_dur, 
                'Unit_Count': int(row.get('Unit_Count', 1)),
                'BOPD_Value': bopd,
                'Tier_Label': determine_tier_label(bopd),
                'Job_Category': determine_category(eff_dur),
                'Has_Constraint': row.get('Has_Constraint', 'No'),
                'Constraint_Note': row.get('Constraint_Note', '-'),
                'Original_Index': 9999 + idx, 
                'Source': 'Manual'
            })

    return pd.DataFrame(new_data)

# --- SIMULASI ORIGINAL ---
def run_original_simulation(df):
    if df.empty: return df
    df_orig = df.sort_values(by=['Rig_Name', 'Original_Index']) 
    schedule = []
    rig_timeline = {}
    base_start = datetime.now().date() + timedelta(days=1)
    
    for _, row in df_orig.iterrows():
        rig = row['Rig_Name']
        duration = int(row['Duration_Days'])
        curr_start = rig_timeline.get(rig, base_start)
        curr_end = curr_start + timedelta(days=duration)
        rig_timeline[rig] = curr_end
        schedule.append({'Job_ID': row['Job_ID'], 'Finish_Date_Original': curr_end})
    return pd.DataFrame(schedule)

def run_smart_engine(df, oil_price):
    if df.empty: return df, pd.DataFrame()

    df_original_sim = run_original_simulation(df)

    df['Constraint_Score'] = df['Has_Constraint'].apply(lambda x: 1 if x == 'Yes' else 0)
    
    df_sorted = df.sort_values(
        by=['Rig_Name', 'Constraint_Score', 'BOPD_Value', 'Duration_Days'], 
        ascending=[True, True, False, True] 
    )

    max_bopd = df['BOPD_Value'].max()
    if max_bopd == 0: max_bopd = 10 

    schedule_list = []
    rig_timeline = {}
    base_start = datetime.now().date() + timedelta(days=1)

    for _, row in df_sorted.iterrows():
        rig = row['Rig_Name']
        duration = int(row['Duration_Days'])
        
        curr_start = rig_timeline.get(rig, base_start)
        curr_end = curr_start + timedelta(days=duration)
        rig_timeline[rig] = curr_end
        
        unit_mk = f"⚡{row['Unit_Count']}" if row['Unit_Count'] > 1 else ""
        label = f"{row['Job_ID']} | BOPD:{row['BOPD_Value']:.1f} {unit_mk}" 
        reason = f"1.[{'✅' if row['Constraint_Score']==0 else '❌'}] 2.[BOPD:{row['BOPD_Value']}] 3.[Dur:{duration}d]"

        schedule_list.append({
            'Rig_Name': rig,
            'Job_ID': row['Job_ID'],
            'Start_Date': curr_start,
            'Finish_Date': curr_end,
            'Duration_Days': duration,
            'Original_Duration': row['Original_Duration'],
            'BOPD_Value': row['BOPD_Value'],
            'Tier_Label': row['Tier_Label'],
            'Unit_Count': row['Unit_Count'],
            'Has_Constraint': row['Has_Constraint'],
            'Constraint_Note': row['Constraint_Note'],
            'Job_Category': row['Job_Category'],
            'Activity': row['Activity'],
            'Source': row['Source'],
            'Display_Text': label,
            'Bar_Color': generate_major_minor_color(row['Job_Category'], row['BOPD_Value'], max_bopd),
            'Sorting_Reason': reason
        })
        
    df_smart = pd.DataFrame(schedule_list)
    
    if not df_smart.empty and not df_original_sim.empty:
        df_comparison = pd.merge(df_smart, df_original_sim, on='Job_ID', how='left')
        
        df_comparison['Finish_Date_Original'] = pd.to_datetime(df_comparison['Finish_Date_Original'])
        df_comparison['Finish_Date'] = pd.to_datetime(df_comparison['Finish_Date'])
        
        def calculate_delay_cut(row):
            if row['Source'] == 'Manual':
                return max(0, row['Original_Duration'] - row['Duration_Days'])
            else:
                try:
                    delta = (row['Finish_Date_Original'] - row['Finish_Date']).days
                    return delta
                except:
                    return 0

        df_comparison['Delay_Cut_Days'] = df_comparison.apply(calculate_delay_cut, axis=1)
        
        # Hitung Gain
        df_comparison['Production_Gain_Bbls'] = df_comparison['Delay_Cut_Days'] * df_comparison['BOPD_Value']
        df_comparison['Revenue_Gain_USD'] = df_comparison['Production_Gain_Bbls'] * oil_price
        
        return df_comparison
    else:
        return df_smart

# --- 3. STATE ---
if 'main_data' not in st.session_state:
    st.session_state['main_data'] = pd.DataFrame()
if 'last_updated_job' not in st.session_state:
    st.session_state['last_updated_job'] = None

# --- 4. SIDEBAR ---
st.sidebar.title("🛠️ Control Panel")
if st.sidebar.button("🗑️ Reset Data"):
    st.session_state['main_data'] = pd.DataFrame()
    st.session_state['last_updated_job'] = None
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("💲 Parameter Ekonomi")
oil_price_input = st.sidebar.number_input("Harga Minyak (USD/Barel)", min_value=0.0, value=65.0, step=0.1)

uploaded = st.sidebar.file_uploader("1. Import Excel", type=['xlsx'])
if uploaded:
    df_raw = pd.read_excel(uploaded)
    df_clean = preprocess_data(df_raw)
    if not df_clean.empty:
        st.session_state['main_data'] = pd.concat([st.session_state['main_data'], df_clean], ignore_index=True)

st.sidebar.markdown("---")
st.sidebar.subheader("2. Input / Edit Manual Job")
with st.sidebar.form("manual_form"):
    existing_rigs = sorted(st.session_state['main_data']['Rig_Name'].unique()) if not st.session_state['main_data'].empty else ["Rig-Manual-01"]
    in_rig = st.selectbox("Pilih Rig", existing_rigs)
    
    # Input Job ID (Ini Kuncinya)
    in_job = st.text_input("Job ID (Gunakan ID sama untuk Update)", "JOB-MANUAL-01")
    
    in_bopd = st.number_input("BOPD Rig Day (Edit Disini)", 0.0, 1000.0, 15.0)
    c1, c2 = st.columns(2)
    raw_dur = c1.number_input("Durasi Awal (Hari)", 1, 100, 4)
    n_units = c2.number_input("Jumlah Unit", 1, 10, 4)
    in_cons = st.checkbox("Ada Constraint?", value=False)
    
    if st.form_submit_button("Simulasikan & Hitung"):
        eff_dur = math.ceil(raw_dur / n_units)
        
        new_row = {
            'Rig_Name': in_rig, 'Job_ID': in_job, 
            'Duration_Days': eff_dur, 
            'Original_Duration': raw_dur, 
            'Unit_Count': n_units,
            'BOPD_Value': in_bopd, 'Activity': "Manual Strategy",
            'Has_Constraint': 'Yes' if in_cons else 'No',
            'Constraint_Note': "Manual Input",
            'Source': 'Manual'
        }
        proc = preprocess_data(pd.DataFrame([new_row]))
        
        # --- [BUG FIX DI SINI: LOGIC ANTI-DUPLIKASI] ---
        # 1. Ambil data lama
        current_df = st.session_state['main_data']
        
        # 2. Hapus dulu baris yang punya Job ID sama (biar gak numpuk/double)
        if not current_df.empty and 'Job_ID' in current_df.columns:
            current_df = current_df[current_df['Job_ID'] != in_job]
            
        # 3. Gabungkan Data Bersih + Data Baru
        st.session_state['main_data'] = pd.concat([current_df, proc], ignore_index=True)
        # -----------------------------------------------

        st.session_state['last_updated_job'] = in_job
        st.rerun()

# --- 5. DASHBOARD ---
st.title("🚜 Smart Schedule: Fixed Calculation")

if not st.session_state['main_data'].empty:
    df_final = run_smart_engine(st.session_state['main_data'], oil_price_input)
    
    if st.session_state['last_updated_job']:
        last_job = st.session_state['last_updated_job']
        job_res = df_final[df_final['Job_ID'] == last_job]
        if not job_res.empty:
            r = job_res.iloc[0]
            st.success(f"✅ Job **{r['Job_ID']}** (BOPD: {r['BOPD_Value']}) berhasil di-update di **{r['Rig_Name']}**.")

    # --- KPI METRICS ---
    st.markdown("### 💰 Analisa Revenue Gain (Real Data)")
    st.info(f"Basis Perhitungan: **(Delay Waktu Tunggu x BOPD Real) x ${oil_price_input}**")
    
    total_gain_bbls = df_final['Production_Gain_Bbls'].sum()
    total_gain_usd = df_final['Revenue_Gain_USD'].sum()
    total_bopd_all = df_final['BOPD_Value'].sum() 

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    kpi1.metric("Total Kapasitas BOPD", f"{total_bopd_all:,.0f} Bbls", help="Total akumulasi BOPD dari semua job yang aktif")
    kpi2.metric("Produksi Terselamatkan", f"{total_gain_bbls:,.0f} Bbls", delta="Volume Saved")
    kpi3.metric("Revenue Gain (USD)", f"${total_gain_usd:,.0f}", delta=f"Price: ${oil_price_input}") 
    kpi4.metric("Total Jobs", f"{len(df_final)}")
    
    st.markdown("---")
    
    # --- PIE CHART ---
    st.subheader("📊 Distribusi Keuntungan")
    rig_revenue = df_final.groupby('Rig_Name')['Revenue_Gain_USD'].sum().reset_index()
    rig_revenue = rig_revenue.sort_values('Revenue_Gain_USD', ascending=False)
    
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("**Top Kontributor Revenue (USD)**")
        st.dataframe(rig_revenue.head(5).style.format({"Revenue_Gain_USD": "${:,.0f}"}), use_container_width=True)
    with c2:
        fig_pie = px.pie(rig_revenue, values='Revenue_Gain_USD', names='Rig_Name', title='Proporsi Revenue Gain per Rig', hole=0.4)
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig_pie, use_container_width=True)

    with st.expander("📄 Lihat Detail Data Perhitungan"):
        cols_map = {'Rig_Name': 'Rig', 'Job_ID': 'Job ID', 'Delay_Cut_Days': 'Hemat Hari', 'BOPD_Value': 'BOPD Real', 'Revenue_Gain_USD': 'Gain (USD)'}
        df_show = df_final[cols_map.keys()].rename(columns=cols_map).sort_values('Gain (USD)', ascending=False)
        st.dataframe(df_show, use_container_width=True)

    st.markdown("---")

    # --- GRAFIK GANTT ---
    st.subheader("📅 Peta Jadwal Rig")
    fig = px.timeline(
        df_final, 
        x_start="Start_Date", x_end="Finish_Date", y="Rig_Name",
        color="Bar_Color", color_discrete_map="identity",
        hover_data=["Job_ID", "BOPD_Value", "Revenue_Gain_USD"], 
        text="Display_Text", height=700
    )
    fig.update_traces(textposition='inside', insidetextanchor='start')
    fig.update_layout(uniformtext_minsize=8, uniformtext_mode='hide')
    fig.update_yaxes(autorange="reversed", showticklabels=True, title="Unit / Rig")
    fig.update_xaxes(title="Timeline", rangeselector=dict(buttons=[dict(count=7, label="1W", step="day", stepmode="backward"), dict(step="all")]))
    fig.add_vline(x=datetime.now(), line_width=1, line_dash="dash", line_color="blue")
    st.plotly_chart(fig, use_container_width=True)

    # --- LOGIC PROVER ---
    st.markdown("---")
    st.header("🔍 Logic Prover")
    rig_list = sorted(df_final['Rig_Name'].unique())
    selected_rig = st.selectbox("Pilih Rig untuk dibedah:", rig_list)
    if selected_rig:
        rig_data = df_final[df_final['Rig_Name'] == selected_rig].sort_values('Start_Date').reset_index(drop=True)
        rig_data.index += 1 
        st.dataframe(rig_data[['Start_Date', 'Job_Category', 'Job_ID', 'Has_Constraint', 'BOPD_Value', 'Sorting_Reason']], use_container_width=True)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer: 
        df_final.to_excel(writer, index=False, sheet_name="Full Schedule")
    st.download_button("📥 Download Excel", buf.getvalue(), "Smart_Schedule_RealData.xlsx")

else:
    st.warning("Silakan Upload Excel terlebih dahulu.")