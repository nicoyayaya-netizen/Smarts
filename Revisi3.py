import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import io
import math
import re

# --- 1. CONFIG & SESSION STATE ---
st.set_page_config(page_title="SMART SITE READINESS", layout="wide")

# Init Session State
if 'data_current' not in st.session_state: st.session_state['data_current'] = pd.DataFrame()
if 'data_initial' not in st.session_state: st.session_state['data_initial'] = pd.DataFrame() # BASELINE TETAP
if 'kpi_result' not in st.session_state: st.session_state['kpi_result'] = None
if 'notifications' not in st.session_state: st.session_state['notifications'] = []

# --- 2. UTILITY FUNCTIONS ---
def parse_duration(val):
    try:
        if pd.isna(val) or val == '': return 1
        if isinstance(val, (int, float)): 
            val_float = float(val)
            if math.isnan(val_float) or math.isinf(val_float): return 1
            return math.ceil(val_float)
        match = re.search(r'\(([\d\.]+) Hari\)', str(val))
        if match: return math.ceil(float(match.group(1)))
        return 1
    except: return 1

def determine_category(duration):
    return 'MAJOR' if duration > 2 else 'MINOR'

def determine_team(activity, category):
    act_lower = str(activity).lower()
    # Team MPU Logic
    keywords_mpu = ['dismantle pump unit', 'dismantle hh', 'dismantle flow line', 'grass cutting']
    if any(k in act_lower for k in keywords_mpu): return "MPU WOWS (Minor Job)"
    
    # Team IEMS Logic
    keywords_iems = ['dress up', 'perbaikan kanal', 'access road', 'main road', 'acess road', 'kanal']
    if any(k in act_lower for k in keywords_iems): return "IEMS (Major Job)"

    # Fallback
    return "IEMS (Major Job)" if category == 'MAJOR' else "MPU WOWS (Minor Job)"

def determine_tier_label(bopd, limit_t1, limit_t2):
    if bopd >= limit_t1: return "Tier 1 (Critical)"
    elif bopd >= limit_t2: return "Tier 2 (High)"
    else: return "Tier 3 (Routine)"

def generate_major_minor_color(category, bopd, max_bopd):
    if pd.isna(max_bopd) or max_bopd == 0: max_bopd = 1
    try:
        ratio = bopd / max_bopd
        ratio = max(0.2, min(ratio, 1)) 
        white_mix = int(255 * (1 - ratio))
        if category == 'MAJOR':
            return f'rgb(255, {white_mix}, {white_mix})'
        else: 
            green_base = 180 + int(75 * (1-ratio))
            mix = int(255 * (1 - ratio))
            return f'rgb({mix}, {green_base}, {mix})'
    except:
        return 'rgb(200, 200, 200)'

def preprocess_data(df, source_type='Excel', t1_lim=50, t2_lim=20):
    new_data = []
    df.columns = [c.strip() for c in df.columns]
    
    for _, row in df.iterrows():
        if source_type == 'Manual' or 'Duration_Days' in df.columns:
            dur_raw = row.get('Duration_Days', 1)
            bopd_raw = row.get('BOPD_Value', 0)
            activity = str(row.get('Activity', 'Manual'))
            job_id = str(row.get('Job_ID', 'UNK'))
            rig_name = str(row.get('Rig_Name', 'UNK'))
            unit_count_raw = row.get('Unit_Count', 1)
            has_cons = str(row.get('Has_Constraint', 'No'))
            cons_note = str(row.get('Constraint_Note', '-'))
            orig_dur_raw = row.get('Original_Duration', dur_raw)
        else:
            dur_raw = row.get('Total Eksekusi (Jam/Hari)', 1)
            bopd_raw = row.get('BOPD_RIGDAYS', 0)
            const_txt = str(row.get('Rincian Penilaian Constraint', ''))
            has_cons = 'Yes' if len(const_txt) > 3 and const_txt.lower() != 'nan' else 'No'
            activity = str(row.get('SITE_ACTION_ITEM', 'Activity'))
            job_id = str(row.get('PROG CODE', 'UNK'))
            rig_name = str(row.get('HSRIG_NAME', 'Unknown-Rig'))
            unit_count_raw = 1
            cons_note = const_txt if has_cons == 'Yes' else '-'
            orig_dur_raw = dur_raw

        try:
            bopd = float(bopd_raw)
            if math.isnan(bopd) or math.isinf(bopd): bopd = 0.0
        except: bopd = 0.0
        
        dur = parse_duration(dur_raw)
        orig_dur = parse_duration(orig_dur_raw)
        
        try: unit_count = int(unit_count_raw)
        except: unit_count = 1

        cat = determine_category(dur)
        tier = determine_tier_label(bopd, t1_lim, t2_lim)
        
        if bopd >= t1_lim: rec_text = "🔥 Tier 1"
        elif bopd >= t2_lim: rec_text = "⚡ Tier 2"
        else: rec_text = "✓ Tier 3"

        new_data.append({
            'Recommendation': rec_text,
            'Job_ID': job_id,
            'Rig_Name': rig_name,
            'Activity': activity[:50],
            'Duration_Days': dur, 
            'Original_Duration': orig_dur,
            'Unit_Count': unit_count, 
            'BOPD_Value': bopd, 
            'Tier_Label': tier,
            'Job_Category': cat,
            'Exec_Team': determine_team(activity, cat),
            'Has_Constraint': has_cons,
            'Constraint_Note': cons_note,
            'Source': source_type
        })
    
    df_clean = pd.DataFrame(new_data)
    if not df_clean.empty:
        df_clean['BOPD_Value'] = df_clean['BOPD_Value'].fillna(0.0)
    return df_clean

# --- 3. CORE ENGINE (COMPARISON LOGIC - 3 LAYERS) ---
def run_comparison_engine(df_current, df_initial, oil_price, start_date_obj, constraint_delay_days):
    if df_current.empty: return None, pd.DataFrame(), pd.DataFrame()

    # --- A. SKENARIO SMART ---
    df_current['Constraint_Score'] = df_current['Has_Constraint'].apply(lambda x: 1 if x == 'Yes' else 0)
    
    # SORTING: Constraint (Asc) -> BOPD (Desc) -> Duration (Asc)
    df_smart = df_current.sort_values(
        by=['Constraint_Score', 'BOPD_Value', 'Duration_Days'], 
        ascending=[True, False, True]
    ).copy()

    # --- B. SKENARIO ORIGINAL ---
    baseline_df = df_initial if not df_initial.empty else df_current
    df_orig = baseline_df.sort_values(by=['BOPD_Value'], ascending=[False]).copy()

    def calculate_schedule(dataframe, label_prefix, logic_type):
        schedule_list = []
        rig_timeline = {}
        
        base_start = start_date_obj 
        max_bopd = dataframe['BOPD_Value'].max() if not dataframe.empty else 10

        for _, row in dataframe.iterrows():
            rig = row['Rig_Name']
            duration = int(row['Duration_Days'])
            
            # Delay Logic: Gunakan Parameter Input User
            start_delay = 0
            if logic_type == 'Original' and row['Has_Constraint'] == 'Yes':
                start_delay = constraint_delay_days # <-- DYNAMIC DELAY
            
            curr_start = rig_timeline.get(rig, base_start) + timedelta(days=start_delay)
            curr_end = curr_start + timedelta(days=duration)
            rig_timeline[rig] = curr_end 
            
            # Revenue Gain per Job
            job_rev_gain = 0
            if label_prefix == "Smart Readiness":
                days_saved_cons = constraint_delay_days if row['Has_Constraint'] == 'Yes' else 0 # <-- DYNAMIC SAVING
                days_saved_eff = max(0, row['Original_Duration'] - duration)
                total_days_saved = days_saved_cons + days_saved_eff
                job_rev_gain = total_days_saved * row['BOPD_Value'] * oil_price
            
            uc = row.get('Unit_Count', 1)
            unit_mk = f"⚡{uc}" if uc > 1 else ""

            schedule_list.append({
                'Rig_Name': rig, 'Job_ID': row['Job_ID'], 'Activity': row['Activity'],
                'Start_Date': curr_start, 'Finish_Date': curr_end,
                'Duration_Days': duration, 'BOPD_Value': row['BOPD_Value'],
                'Display_Text': f"{row['Job_ID']} | BOPD:{row['BOPD_Value']:.1f} {unit_mk}",
                'Bar_Color': generate_major_minor_color(row['Job_Category'], row['BOPD_Value'], max_bopd),
                'Has_Constraint': row['Has_Constraint'], 'Constraint_Note': row['Constraint_Note'],
                'Exec_Team': row['Exec_Team'], 'Tier_Label': row['Tier_Label'],
                'Scenario': label_prefix, 'Unit_Count': uc,
                'Revenue_Gain_USD': job_rev_gain
            })
        return pd.DataFrame(schedule_list)

    res_smart = calculate_schedule(df_smart, "Smart Readiness", logic_type='Smart')
    res_orig = calculate_schedule(df_orig, "Original Plan", logic_type='Original')
    
    def get_cum_bopd(df_sch):
        if df_sch.empty: return pd.Series()
        dates = pd.date_range(df_sch['Start_Date'].min(), df_sch['Finish_Date'].max())
        daily_prod = pd.Series(0, index=dates)
        for _, r in df_sch.iterrows(): daily_prod[r['Finish_Date']:] += r['BOPD_Value']
        return daily_prod

    cum_smart = get_cum_bopd(res_smart)
    cum_orig = get_cum_bopd(res_orig)
    
    all_dates = cum_smart.index.union(cum_orig.index)
    smart_filled = cum_smart.reindex(all_dates).ffill().fillna(0)
    orig_filled = cum_orig.reindex(all_dates).ffill().fillna(0)
    
    daily_gain_bbls = (smart_filled - orig_filled).sum()
    total_gain_usd = daily_gain_bbls * oil_price
    
    return {'bbls': daily_gain_bbls, 'usd': total_gain_usd}, res_smart, res_orig

# --- 5. SIDEBAR ---
st.sidebar.title("🛠️ Control Panel")

# PARAMETER DINAMIS TIER
with st.sidebar.expander("⚙️ Parameter Global", expanded=False):
    tier1_limit = st.number_input("Batas Tier 1 (>)", value=50)
    tier2_limit = st.number_input("Batas Tier 2 (>)", value=20)
    # FITUR BARU: ATUR DELAY CONSTRAINT
    constraint_delay = st.number_input("Hukuman Delay Constraint (Hari)", value=7, min_value=1, help="Berapa hari delay jika Constraint diabaikan? Default: 7 Hari")

with st.sidebar.expander("🔔 History", expanded=False):
    if st.session_state['notifications']:
        for note in reversed(st.session_state['notifications']): st.caption(note)
    else: st.caption("No changes yet.")

if st.sidebar.button("🗑️ Reset System"):
    st.session_state['data_current'] = pd.DataFrame()
    st.session_state['data_initial'] = pd.DataFrame()
    st.session_state['kpi_result'] = None
    st.session_state['notifications'] = []
    st.rerun()

st.sidebar.markdown("---")
# TOOLS TANGGAL
st.sidebar.subheader("📅 Parameter Jadwal")
start_date_input = st.sidebar.date_input("Mulai Operasi", datetime.now())
oil_price_input = st.sidebar.number_input("Harga Minyak ($)", value=65.0)

uploaded = st.sidebar.file_uploader("Import Excel Data", type=['xlsx'])
if uploaded:
    df_raw = pd.read_excel(uploaded)
    df_proc = preprocess_data(df_raw, 'Excel', t1_lim=tier1_limit, t2_lim=tier2_limit)
    if not df_proc.empty:
        if st.session_state['data_initial'].empty: 
            st.session_state['data_initial'] = df_proc.copy()
        
        st.session_state['data_current'] = df_proc.copy()
        st.session_state['notifications'].append(f"📥 Import {len(df_proc)} jobs.")

# --- 6. ADD MANUAL JOB ---
st.sidebar.markdown("---")
with st.sidebar.expander("➕ Add Manual Job"):
    with st.form("add_form"):
        exist_rigs = st.session_state['data_current']['Rig_Name'].unique().tolist() if not st.session_state['data_current'].empty else ["Rig-01"]
        new_rig = st.selectbox("Pilih Rig", exist_rigs)
        new_job = st.text_input("Job ID", "JOB-NEW")
        new_act = st.text_input("Activity", "Service")
        new_bopd = st.number_input("BOPD", 0.0, 1000.0, 10.0)
        c1, c2 = st.columns(2)
        new_dur = c1.number_input("Durasi (Hari)", 1, 100, 4)
        new_unit = c2.number_input("Unit", 1, 10, 1)
        new_cons = st.checkbox("Constraint?", False)
        new_note = st.text_input("Catatan")
        
        if st.form_submit_button("Add Job"):
            row = {'Rig_Name': new_rig, 'Job_ID': new_job, 'Duration_Days': math.ceil(new_dur/new_unit),
                   'Original_Duration': new_dur, 'Unit_Count': new_unit, 'Activity': new_act,
                   'BOPD_Value': new_bopd, 'Has_Constraint': 'Yes' if new_cons else 'No',
                   'Constraint_Note': new_note if new_cons else '-', 'Source': 'Manual'}
            st.session_state['data_current'] = pd.concat([st.session_state['data_current'], preprocess_data(pd.DataFrame([row]), 'Manual', t1_lim=tier1_limit, t2_lim=tier2_limit)], ignore_index=True)
            st.session_state['notifications'].append(f"➕ Added {new_job}")
            st.rerun()

# --- 7. DASHBOARD MAIN ---
st.title("🏗️ SMART SITE READINESS")

if not st.session_state['data_current'].empty:
    
    # --- A. TABLE EDITOR ---
    with st.expander("⚡ Planning & Editing", expanded=True):
        st.info(f"💡 **Info:** Sistem menggunakan asumsi Hukuman Delay = **{constraint_delay} Hari** (Bisa diubah di Sidebar).")
        unique_rigs = st.session_state['data_current']['Rig_Name'].unique().tolist()
        
        df_for_editor = st.session_state['data_current'].copy()
        
        edited_df = st.data_editor(
            df_for_editor[['Job_ID', 'Rig_Name', 'Recommendation', 'BOPD_Value', 'Duration_Days', 'Has_Constraint', 'Constraint_Note', 'Activity']],
            column_config={
                "Rig_Name": st.column_config.SelectboxColumn("Pilih Rig", options=unique_rigs, required=True),
                "Recommendation": st.column_config.TextColumn("Rekomendasi (Status)", disabled=True), 
                "Has_Constraint": st.column_config.SelectboxColumn("Constraint?", options=["Yes", "No"]),
                "BOPD_Value": st.column_config.NumberColumn("BOPD", min_value=0.0, format="%.2f"),
                "Duration_Days": st.column_config.NumberColumn("Durasi", min_value=1)
            },
            num_rows="dynamic",
            key="editor",
            use_container_width=True
        )

    # --- B. TOMBOL TRIGGER UTAMA ---
    st.markdown("---")
    if st.button("🔄 UPDATE SCHEDULE & CALCULATE", type="primary", use_container_width=True):
        curr_df = st.session_state['data_current'].copy()
        
        if len(edited_df) == len(curr_df):
            for col in ['Job_ID', 'Rig_Name', 'BOPD_Value', 'Duration_Days', 'Has_Constraint', 'Constraint_Note', 'Activity']:
                curr_df[col] = edited_df[col]
            
            curr_df['Tier_Label'] = curr_df['BOPD_Value'].apply(lambda x: determine_tier_label(x, tier1_limit, tier2_limit))
            
            def update_rec(bopd):
                if bopd >= tier1_limit: return "🔥 Tier 1"
                elif bopd >= tier2_limit: return "⚡ Tier 2"
                else: return "✓ Tier 3"
            curr_df['Recommendation'] = curr_df['BOPD_Value'].apply(update_rec)

            curr_df['Job_Category'] = curr_df['Duration_Days'].apply(determine_category)
            curr_df['Exec_Team'] = curr_df.apply(lambda x: determine_team(x['Activity'], x['Job_Category']), axis=1)
        
        st.session_state['data_current'] = curr_df
        
        # PASSING PARAMETER DELAY KE ENGINE
        kpi, df_smart, df_orig = run_comparison_engine(
            curr_df, 
            st.session_state['data_initial'], 
            oil_price_input, 
            start_date_input,
            constraint_delay # <-- Dynamic Param
        )
        
        st.session_state['kpi_result'] = {'kpi': kpi, 'df_smart': df_smart, 'df_orig': df_orig, 'timestamp': datetime.now().strftime('%H:%M:%S')}
        st.rerun()

    # --- C. DISPLAY HASIL ---
    if st.session_state['kpi_result']:
        res = st.session_state['kpi_result']
        kpi = res['kpi']
        df_smart = res['df_smart']
        df_orig = res['df_orig']
        
        st.markdown("---")
        k1, k2, k3 = st.columns(3)
        k1.metric("Optimization Gain", f"{kpi['bbls']:,.0f} Bbls")
        k2.metric("Revenue Gain", f"${kpi['usd']:,.0f}", help="Selisih vs Kondisi Awal")
        k3.metric("Total Jobs", f"{len(df_smart)}")
        st.caption(f"Calculated at: {res['timestamp']}")
        
        # 1. TEAM RECOMMENDATION
        st.subheader("📢 Team Follow-Up Recommendation")
        top_jobs = df_smart.head(5).copy()
        cols = st.columns(len(top_jobs)) if not top_jobs.empty else [st.empty()]
        for i, (index, row) in enumerate(top_jobs.iterrows()):
            with cols[i]:
                team = row['Exec_Team']
                color = "🔴" if "IEMS" in team else "🟢" if "MPU" in team else "🔵"
                
                with st.container(border=True):
                    st.markdown(f"**{color} {team}**")
                    st.caption(f"{row['Rig_Name']}")
                    st.markdown(f"**{row['Job_ID']}**")
                    if row['Has_Constraint'] == 'Yes': st.error(f"⛔ {row['Constraint_Note']}")
                    else: st.success("✅ READY")

        with st.expander("📂 Lihat Detail Semua Pekerjaan"):
            st.dataframe(df_smart[['Job_ID', 'Rig_Name', 'Exec_Team', 'Has_Constraint', 'Constraint_Note', 'Duration_Days', 'Unit_Count']], use_container_width=True)

        st.markdown("---")
        
        # 2. S-CURVE
        st.subheader("📈 S-Curve: Smart vs Original Baseline")
        def create_scurve(df_input, label):
            if df_input.empty: return pd.DataFrame()
            df_temp = df_input[['Finish_Date', 'BOPD_Value']].copy()
            df_temp['Finish_Date'] = pd.to_datetime(df_temp['Finish_Date']).dt.date
            df_grouped = df_temp.groupby('Finish_Date')['BOPD_Value'].sum().reset_index().sort_values('Finish_Date')
            df_grouped['Cum_BOPD'] = df_grouped['BOPD_Value'].cumsum()
            df_grouped.set_index('Finish_Date', inplace=True)
            idx = pd.date_range(df_grouped.index.min(), df_grouped.index.max())
            df_filled = df_grouped.reindex(idx).fillna(method='ffill').reset_index()
            df_filled.rename(columns={'index': 'Date'}, inplace=True)
            df_filled['Scenario'] = label
            return df_filled

        curve_smart = create_scurve(df_smart, 'Smart Plan (Edited)')
        curve_orig = create_scurve(df_orig, 'Original Baseline (Initial)')
        
        if not curve_smart.empty and not curve_orig.empty:
            max_date = max(curve_smart['Date'].max(), curve_orig['Date'].max())
            def extend(df):
                last = df.iloc[-1]
                if last['Date'] < max_date:
                    add = pd.DataFrame({'Date': [max_date], 'Cum_BOPD': [last['Cum_BOPD']], 'Scenario': [last['Scenario']]})
                    return pd.concat([df, add], ignore_index=True)
                return df
            final_plot = pd.concat([extend(curve_smart), extend(curve_orig)], ignore_index=True)
            fig = px.line(final_plot, x='Date', y='Cum_BOPD', color='Scenario',
                          color_discrete_map={'Smart Plan (Edited)': '#00CC96', 'Original Baseline (Initial)': '#EF553B'})
            fig.update_layout(hovermode="x unified", height=400)
            st.plotly_chart(fig, use_container_width=True)

        # 3. PIE CHART
        st.subheader("📊 Distribusi Value per Rig")
        c1, c2 = st.columns([1.5, 1])
        rig_rev = df_smart.groupby('Rig_Name')['Revenue_Gain_USD'].sum().reset_index().sort_values('Revenue_Gain_USD', ascending=False)
        
        with c1:
            fig_pie = px.pie(rig_rev, values='Revenue_Gain_USD', names='Rig_Name', hole=0.4)
            st.plotly_chart(fig_pie, use_container_width=True)
        with c2:
            st.dataframe(rig_rev.style.format({"Revenue_Gain_USD": "${:,.0f}"}), use_container_width=True, height=300)

        # 4. GANTT CHART (CLEAN)
        st.subheader("📅 Peta Jadwal Rig")
        fig_gantt = px.timeline(
            df_smart, x_start="Start_Date", x_end="Finish_Date", y="Rig_Name",
            color="Bar_Color", color_discrete_map="identity",
            hover_data=["Job_ID", "BOPD_Value", "Tier_Label", "Activity"],
            height=600
        )
        fig_gantt.update_yaxes(autorange="reversed")
        st.plotly_chart(fig_gantt, use_container_width=True)

        # 5. DOWNLOAD
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            df_smart.to_excel(writer, index=False, sheet_name="Smart Schedule")
        st.download_button("📥 Download Excel Result", buf.getvalue(), "Smart_Schedule.xlsx")

    else:
        st.info("👈 Silakan atur tanggal & edit data tabel, lalu klik tombol **'🔄 UPDATE SCHEDULE & CALCULATE'**.")

else:
    st.info("👋 Silakan Upload Excel atau Input Manual di Sidebar.")
