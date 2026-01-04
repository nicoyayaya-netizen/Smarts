import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import io
import math
import re

# --- 1. CONFIG ---
st.set_page_config(page_title="Smart Scheduler - Duration Logic", layout="wide")

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

    # READ EXCEL
    if 'HSRIG_NAME' in df.columns:
        for _, row in df.iterrows():
            dur = parse_duration(row.get('Total Eksekusi (Jam/Hari)', 1))
            
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
                'Unit_Count': 1,
                'BOPD_Value': bopd, 
                'Tier_Label': determine_tier_label(bopd),
                'Job_Category': determine_category(dur),
                'Has_Constraint': has_cons,
                'Constraint_Note': const_txt if has_cons == 'Yes' else '-',
                'Source': 'Excel' 
            })
            
    # READ MANUAL
    elif 'Rig_Name' in df.columns:
        if 'Rig Name' in df.columns: df['Rig_Name'] = df['Rig Name']
        if 'Job ID' in df.columns: df['Job_ID'] = df['Job ID']
        if 'Duration' in df.columns: df['Duration_Days'] = df['Duration']
        
        for idx, row in df.iterrows():
            eff_dur = int(row.get('Duration_Days', 1)) 
            bopd = float(row.get('BOPD_Value', 0))
            
            new_data.append({
                'Job_ID': row.get('Job_ID', '-'),
                'Rig_Name': row.get('Rig_Name', '-'),
                'Activity': row.get('Activity', 'Manual Job'),
                'Duration_Days': eff_dur,
                'Unit_Count': int(row.get('Unit_Count', 1)),
                'BOPD_Value': bopd,
                'Tier_Label': determine_tier_label(bopd),
                'Job_Category': determine_category(eff_dur),
                'Has_Constraint': row.get('Has_Constraint', 'No'),
                'Constraint_Note': row.get('Constraint_Note', '-'),
                'Source': 'Manual'
            })

    return pd.DataFrame(new_data)

# --- 3. SMART ENGINE (LOGIC BARU) ---
def run_smart_engine(df, oil_price):
    if df.empty: return pd.DataFrame()

    df['Constraint_Score'] = df['Has_Constraint'].apply(lambda x: 1 if x == 'Yes' else 0)
    
    # Sorting (Tetap dilakukan untuk penjadwalan visual)
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
        
        # Penjadwalan Waktu
        curr_start = rig_timeline.get(rig, base_start)
        curr_end = curr_start + timedelta(days=duration)
        rig_timeline[rig] = curr_end
        
        unit_mk = f"⚡{row['Unit_Count']}" if row['Unit_Count'] > 1 else ""
        label = f"{row['Job_ID']} | BOPD:{row['BOPD_Value']:.1f} {unit_mk}" 
        reason = f"1.[{'✅' if row['Constraint_Score']==0 else '❌'}] 2.[BOPD:{row['BOPD_Value']}]"

        # --- LOGIC PERHITUNGAN BARU (Duration Based) ---
        # Value = Durasi Pekerjaan x BOPD x Harga
        # Ini menghitung "Nilai Minyak" selama durasi pekerjaan tersebut.
        prod_value_bbls = duration * row['BOPD_Value']
        revenue_value_usd = prod_value_bbls * oil_price

        schedule_list.append({
            'Rig_Name': rig,
            'Job_ID': row['Job_ID'],
            'Start_Date': curr_start,
            'Finish_Date': curr_end,
            'Duration_Days': duration,
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
            'Sorting_Reason': reason,
            # KPI BARU
            'Production_Val_Bbls': prod_value_bbls,
            'Revenue_Val_USD': revenue_value_usd
        })
        
    return pd.DataFrame(schedule_list)

# --- 4. STATE ---
if 'main_data' not in st.session_state:
    st.session_state['main_data'] = pd.DataFrame()
if 'last_updated_job' not in st.session_state:
    st.session_state['last_updated_job'] = None

# --- 5. SIDEBAR ---
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
    in_job = st.text_input("Job ID (Gunakan ID sama untuk Update)", "JOB-MANUAL-01")
    in_bopd = st.number_input("BOPD Rig Day", 0.0, 1000.0, 15.0)
    c1, c2 = st.columns(2)
    raw_dur = c1.number_input("Durasi Pekerjaan (Hari)", 1, 100, 4)
    n_units = c2.number_input("Jumlah Unit", 1, 10, 4)
    in_cons = st.checkbox("Ada Constraint?", value=False)
    
    if st.form_submit_button("Simulasikan & Hitung"):
        eff_dur = math.ceil(raw_dur / n_units)
        
        new_row = {
            'Rig_Name': in_rig, 'Job_ID': in_job, 
            'Duration_Days': eff_dur, 
            'Unit_Count': n_units,
            'BOPD_Value': in_bopd, 'Activity': "Manual Strategy",
            'Has_Constraint': 'Yes' if in_cons else 'No',
            'Constraint_Note': "Manual Input",
            'Source': 'Manual'
        }
        proc = preprocess_data(pd.DataFrame([new_row]))
        
        current_df = st.session_state['main_data']
        if not current_df.empty and 'Job_ID' in current_df.columns:
            current_df = current_df[current_df['Job_ID'] != in_job]
            
        st.session_state['main_data'] = pd.concat([current_df, proc], ignore_index=True)
        st.session_state['last_updated_job'] = in_job
        st.rerun()

# --- 6. DASHBOARD ---
st.title("🚜 Smart Schedule: Value Managed")

if not st.session_state['main_data'].empty:
    df_final = run_smart_engine(st.session_state['main_data'], oil_price_input)
    
    if st.session_state['last_updated_job']:
        last_job = st.session_state['last_updated_job']
        job_res = df_final[df_final['Job_ID'] == last_job]
        if not job_res.empty:
            r = job_res.iloc[0]
            st.success(f"✅ Job **{r['Job_ID']}** (BOPD: {r['BOPD_Value']}) Updated.")

    # --- KPI METRICS ---
    st.markdown("### 💰 Potential Value Managed (LPO)")
    st.info(f"Basis Perhitungan Baru: **Durasi Pekerjaan (Hari) x BOPD Real x ${oil_price_input}**")
    
    total_val_bbls = df_final['Production_Val_Bbls'].sum()
    total_val_usd = df_final['Revenue_Val_USD'].sum()
    total_bopd_all = df_final['BOPD_Value'].sum() 

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    
    kpi1.metric("Total Kapasitas BOPD", f"{total_bopd_all:,.0f} Bbls")
    kpi2.metric("Total Volume (Bbls)", f"{total_val_bbls:,.0f} Bbls", help="Akumulasi (Durasi x BOPD) semua job")
    kpi3.metric("Total Value (USD)", f"${total_val_usd:,.0f}", delta=f"Price: ${oil_price_input}") 
    kpi4.metric("Total Jobs", f"{len(df_final)}")
    
    st.markdown("---")
    
    # --- PIE CHART ---
    st.subheader("📊 Distribusi Value per Rig")
    rig_revenue = df_final.groupby('Rig_Name')['Revenue_Val_USD'].sum().reset_index()
    rig_revenue = rig_revenue.sort_values('Revenue_Val_USD', ascending=False)
    
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("**Top Rig Value (USD)**")
        st.dataframe(rig_revenue.head(5).style.format({"Revenue_Val_USD": "${:,.0f}"}), use_container_width=True)
    with c2:
        fig_pie = px.pie(rig_revenue, values='Revenue_Val_USD', names='Rig_Name', title='Proporsi Value per Rig', hole=0.4)
        fig_pie.update_traces(textposition='inside', textinfo='percent+label')
        st.plotly_chart(fig_pie, use_container_width=True)

    with st.expander("📄 Lihat Detail Data Perhitungan"):
        cols_map = {'Rig_Name': 'Rig', 'Job_ID': 'Job ID', 'Duration_Days': 'Durasi (Hari)', 'BOPD_Value': 'BOPD', 'Revenue_Val_USD': 'Value (USD)'}
        df_show = df_final[cols_map.keys()].rename(columns=cols_map).sort_values('Value (USD)', ascending=False)
        st.dataframe(df_show, use_container_width=True)

    st.markdown("---")

    # --- GRAFIK GANTT ---
    st.subheader("📅 Peta Jadwal Rig")
    fig = px.timeline(
        df_final, 
        x_start="Start_Date", x_end="Finish_Date", y="Rig_Name",
        color="Bar_Color", color_discrete_map="identity",
        hover_data=["Job_ID", "BOPD_Value", "Revenue_Val_USD"], 
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
        st.dataframe(rig_data[['Start_Date', 'Job_Category', 'Job_ID', 'Has_Constraint', 'BOPD_Value', 'Duration_Days']], use_container_width=True)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer: 
        df_final.to_excel(writer, index=False, sheet_name="Full Schedule")
    st.download_button("📥 Download Excel", buf.getvalue(), "Smart_Schedule_DurationLogic.xlsx")

else:
    st.warning("Silakan Upload Excel terlebih dahulu.")
    
