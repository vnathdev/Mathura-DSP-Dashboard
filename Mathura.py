import streamlit as st
import pandas as pd
from datetime import datetime
import calendar
import altair as alt

# --- MUST BE THE FIRST STREAMLIT COMMAND ---
st.set_page_config(page_title="Mathura-Vrindavan DSP Dashboard", layout="wide", initial_sidebar_state="collapsed")

# ==========================================
# 1. EXCEL COLUMN HEADERS
# ==========================================
COL_SUBCATEGORY = "complaintsubtype"            
COL_STATUS      = "Status"                 
COL_CREATED     = "Complaint Registered Date"   
COL_RESOLVED    = "Closing Date"                
COL_ZONE        = "Zone"                   
COL_SURVEYOR    = "User"

# ==========================================
# 2. GEOGRAPHY-SPECIFIC CONFIGURATION
# ==========================================
CATEGORY_MAPPING = {
    # Civil
    "Potholes": "Civil",
    "Unpaved road": "Civil",
    "Broken Footpath-Divider": "Civil",
    "Footpath/Pavement Required": "Civil",
    "Barren Land to be Greened": "Civil",
    
    # Malba
    "Illegal Dumping of C&D waste": "Malba",
    
    # Sanitation
    "Muds -Silt sticking RoadSide": "Sanitation",
    "Muds -Silt sticking Road Side": "Sanitation",
    "Open-Vacant-Illegal Dumping": "Sanitation",
    "Burning of Garbage": "Sanitation",
    "Road Dust": "Sanitation",
    "Overflowing Garbage Dustbins": "Sanitation"
}

STATUS_COLUMNS = ["Open", "Pending", "Re-open", "Out of Scope", "Close"]
UNRESOLVED_STATUSES = ["Open", "Pending", "Re-open", "Out of Scope"]

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def display_with_fixed_footer(df, show_closure=True):
    if df.empty:
        st.warning("⚠️ No data available to display.")
        return
    body = df.iloc[:-1]
    total = df.iloc[[-1]]
    
    config = {}
    if show_closure and '% Closure' in df.columns:
        config['% Closure'] = st.column_config.NumberColumn(format="%.1f%%")
    if 'Avg Closure Time (Days)' in df.columns:
        config['Avg Closure Time (Days)'] = st.column_config.NumberColumn(format="%.1f")
        
    st.dataframe(body, use_container_width=True, column_config=config)
    st.markdown("⬇️ **Grand Total**") 
    st.dataframe(total, use_container_width=True, column_config=config)

@st.cache_data
def process_data(df):
    df.columns = df.columns.str.strip()
    
    # Check for critical columns
    missing_cols = [col for col in [COL_SUBCATEGORY, COL_STATUS, COL_CREATED] if col not in df.columns]
    if missing_cols:
        st.error(f"❌ Missing critical columns in Excel: {', '.join(missing_cols)}")
        st.stop()
    
    # 1. Map Categories & Filter
    df['Subcategory_Clean'] = df[COL_SUBCATEGORY].astype(str).str.strip()
    df['MainCategory'] = df['Subcategory_Clean'].map(CATEGORY_MAPPING)
    df = df.dropna(subset=['MainCategory']).copy()
    
    # 2. Status Logic
    def get_bucket(status_name):
        s = str(status_name).strip()
        if s in STATUS_COLUMNS: return s
        return "Open"
    df['StatusBucket'] = df[COL_STATUS].apply(get_bucket)
    
    # 3. Precision Date Parsing
    df[COL_CREATED] = df[COL_CREATED].astype(str).str.strip()
    
    # Parse "Oct 13; 2025 8:27 AM" explicitly
    exact_created = pd.to_datetime(df[COL_CREATED], format='%b %d; %Y %I:%M %p', errors='coerce')
    # Fallback just in case the semicolon is missing in some rows
    fallback_created = pd.to_datetime(df[COL_CREATED].str.replace(';', ','), errors='coerce')
    df[COL_CREATED] = exact_created.fillna(fallback_created)
    
    if COL_RESOLVED in df.columns:
        df[COL_RESOLVED] = df[COL_RESOLVED].astype(str).str.strip()
        
        # Parse "mm/dd/yyyy hh:mm" (24-hour time) explicitly
        exact_resolved = pd.to_datetime(df[COL_RESOLVED], format='%m/%d/%Y %H:%M', errors='coerce')
        # Fallback just in case
        fallback_resolved = pd.to_datetime(df[COL_RESOLVED], dayfirst=False, errors='coerce')
        df[COL_RESOLVED] = exact_resolved.fillna(fallback_resolved)
        
        # Calculate closure times
        df['ClosureTimeDays'] = (df[COL_RESOLVED] - df[COL_CREATED]).dt.days
        df['ClosureTimeDays'] = df['ClosureTimeDays'].apply(lambda x: x if pd.notna(x) and x >= 0 else None)
    else:
        df['ClosureTimeDays'] = None
        
    # 4. Aging
    now = datetime.now()
    df['AgeDays'] = (now - df[COL_CREATED]).dt.days
    
    def get_age_bucket(row):
        if row['StatusBucket'] == 'Close': return "Closed"
        days = row['AgeDays']
        if pd.isna(days): return "Unknown"
        if days < 30: return "< 1 Month"
        elif 30 <= days <= 180: return "1-6 Months"
        elif 180 < days <= 365: return "6-12 Months"
        else: return "> 1 Year"
    df['AgeBucket'] = df.apply(get_age_bucket, axis=1)
    
    return df

def generate_pivot_summary(df, group_col, label_suffix="Total", show_avg_time=False):
    if df.empty: return pd.DataFrame()
    summary = df.groupby([group_col, 'StatusBucket']).size().unstack(fill_value=0)
    
    for col in STATUS_COLUMNS:
        if col not in summary.columns: summary[col] = 0
            
    summary = summary[STATUS_COLUMNS] 
    summary['Unresolved Total'] = summary[UNRESOLVED_STATUSES].sum(axis=1)
    summary['Grand Total'] = summary['Unresolved Total'] + summary['Close']
    summary['% Closure'] = summary.apply(lambda r: (r['Close'] / r['Grand Total'] * 100) if r['Grand Total'] > 0 else 0, axis=1).round(1)
    
    if show_avg_time and 'ClosureTimeDays' in df.columns:
        summary['Avg Closure Time (Days)'] = df.groupby(group_col)['ClosureTimeDays'].mean().round(1)

    total_row_data = {col: summary[col].sum() for col in STATUS_COLUMNS + ['Unresolved Total', 'Grand Total']}
    total_row_data['% Closure'] = (total_row_data['Close'] / total_row_data['Grand Total'] * 100) if total_row_data['Grand Total'] > 0 else 0
    
    if show_avg_time and 'ClosureTimeDays' in df.columns:
        total_row_data['Avg Closure Time (Days)'] = df['ClosureTimeDays'].mean().round(1)
    
    total_row = pd.DataFrame([total_row_data], index=[f'**{label_suffix}**'])
    
    cols_order = STATUS_COLUMNS + ['Unresolved Total', 'Grand Total', '% Closure']
    if show_avg_time and 'ClosureTimeDays' in df.columns: cols_order.append('Avg Closure Time (Days)')
        
    return pd.concat([summary, total_row])[cols_order]

def generate_aging_summary(df, group_col):
    if 'AgeBucket' not in df.columns or df.empty: return pd.DataFrame()
    summary = df.groupby([group_col, 'AgeBucket']).size().unstack(fill_value=0)
    cols = ['< 1 Month', '1-6 Months', '6-12 Months', '> 1 Year']
    for c in cols:
        if c not in summary.columns: summary[c] = 0
    summary = summary[cols]
    summary['Total Unresolved'] = summary.sum(axis=1)
    return summary.sort_values('Total Unresolved', ascending=False)

# ==========================================
# MAIN APP
# ==========================================

def main():
    st.title("📊 Mathura-Vrindavan DSP Dashboard")
    st.markdown("---")
    
    st.sidebar.header("📂 Data Source")
    uploaded_file = st.sidebar.file_uploader("Upload Complaints Data (XLSX)", type=['xlsx'])

    st.sidebar.markdown("---")
    st.sidebar.header("🧭 Navigation")
    
    if 'current_view' not in st.session_state:
        st.session_state.current_view = "Main Category Summary"
    
    views = [
        "Main Category Summary",
        "Subcategory Drill-Down",
        "Zone-wise Drill-Down",
        "Age-wise Pendency",
        "Monthly Trend Analysis",
        "Custom Date Range Analysis",
        "Quarterly Performance (FY)",
        "Surveyor Performance"
    ]
    
    for view in views:
        btn_type = "primary" if st.session_state.current_view == view else "secondary"
        if st.sidebar.button(view, use_container_width=True, type=btn_type):
            st.session_state.current_view = view
            st.rerun()

    if uploaded_file is not None:
        try:
            df = pd.read_excel(uploaded_file)
            df_processed = process_data(df)
            
            main_categories = sorted(df_processed['MainCategory'].unique().tolist())
            
            valid_created_years = df_processed[COL_CREATED].dt.year.dropna().unique().tolist()
            valid_resolved_years = []
            if COL_RESOLVED in df_processed.columns:
                valid_resolved_years = df_processed[COL_RESOLVED].dt.year.dropna().unique().tolist()
            all_years = sorted(list(set(valid_created_years + valid_resolved_years)), reverse=True)

            # ==========================================
            # VIEWS
            # ==========================================
            
            if st.session_state.current_view == "Main Category Summary":
                st.subheader("📈 Main Category Summary")
                summary_table = generate_pivot_summary(df_processed, 'MainCategory', "TOTAL")
                
                if not summary_table.empty:
                    body_df = summary_table.iloc[:-1]
                    total_series = summary_table.iloc[-1]
                    
                    st.markdown("##### 🎯 Citywide Grand Totals")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("🔴 Total Unresolved", int(total_series['Unresolved Total']))
                    m2.metric("🟢 Total Closed", int(total_series['Close']))
                    m3.metric("📋 Grand Total", int(total_series['Grand Total']))
                    m4.metric("✅ % Closure", f"{int(round(total_series['% Closure']))}%")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("##### 📂 Category-wise Breakdown")
                    st.dataframe(body_df, use_container_width=True, column_config={"% Closure": st.column_config.NumberColumn(format="%.1f%%")})
                
                st.markdown("---")
                st.subheader("📊 Citywide & Zone-wise Snapshot")
                c1, c2 = st.columns([2, 1])
                
                with c1:
                    st.markdown("**Tickets Raised vs. Closed by Zone**")
                    if COL_ZONE in df_processed.columns:
                        zone_raised = df_processed.groupby(COL_ZONE).size().rename("Total Raised")
                        zone_closed = df_processed[df_processed['StatusBucket'] == 'Close'].groupby(COL_ZONE).size().rename("Total Closed")
                        zone_bar_df = pd.concat([zone_raised, zone_closed], axis=1).fillna(0).astype(int)
                        st.bar_chart(zone_bar_df, use_container_width=True)
                    else:
                        st.info(f"⚠️ '{COL_ZONE}' column not found in data.")
                        
                with c2:
                    st.markdown("**Citywide Status Breakdown**")
                    status_counts = df_processed['StatusBucket'].value_counts().reset_index()
                    status_counts.columns = ['Status', 'Count']
                    pie_chart = alt.Chart(status_counts).mark_arc(innerRadius=40).encode(
                        theta=alt.Theta(field="Count", type="quantitative"),
                        color=alt.Color(field="Status", type="nominal", 
                                        scale=alt.Scale(
                                            domain=STATUS_COLUMNS,
                                            range=['#EF4444', '#F59E0B', '#8B5CF6', '#9CA3AF', '#10B981'] 
                                        )),
                        tooltip=['Status', 'Count']
                    ).properties(height=350)
                    st.altair_chart(pie_chart, use_container_width=True)

            elif st.session_state.current_view == "Subcategory Drill-Down":
                st.subheader("🔍 Subcategory Drill-Down")
                tabs = st.tabs(main_categories)
                for tab, main_cat in zip(tabs, main_categories):
                    with tab:
                        sub_df = df_processed[df_processed['MainCategory'] == main_cat]
                        if not sub_df.empty:
                            display_with_fixed_footer(generate_pivot_summary(sub_df, 'Subcategory_Clean', f"{main_cat} Total"))

            elif st.session_state.current_view == "Zone-wise Drill-Down":
                st.subheader("🗺️ Zone-wise Drill-Down")
                if COL_ZONE not in df_processed.columns:
                    st.error(f"Column '{COL_ZONE}' required for this view is missing.")
                else:
                    st.markdown("##### 📍 Zone Comparison by Status & Closure Time")
                    b3_cat_all = st.selectbox("Select Main Category (For Zone Comparison)", main_categories, key="b3_cat_all")
                    zone_matrix_df = df_processed[df_processed['MainCategory'] == b3_cat_all]
                    if not zone_matrix_df.empty:
                        display_with_fixed_footer(generate_pivot_summary(zone_matrix_df, COL_ZONE, "ALL ZONES TOTAL", show_avg_time=True))
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("##### 📋 Subcategory Detail by Zone")
                    c1, c2 = st.columns(2)
                    with c1: b3_cat_spec = st.selectbox("Select Main Category", main_categories, key="b3_cat_spec")
                    with c2: b3_zone_spec = st.selectbox("Select Zone", sorted(df_processed[COL_ZONE].dropna().unique()), key="b3_zone_spec")
                    
                    zone_spec_df = df_processed[(df_processed['MainCategory'] == b3_cat_spec) & (df_processed[COL_ZONE] == b3_zone_spec)]
                    if not zone_spec_df.empty:
                        display_with_fixed_footer(generate_pivot_summary(zone_spec_df, 'Subcategory_Clean', f"{b3_cat_spec} - {b3_zone_spec} Total", show_avg_time=True))
                    else:
                        st.warning("No data found.")

            elif st.session_state.current_view == "Age-wise Pendency":
                st.subheader("⏳ Age-wise Pendency Analysis")
                b5_cat = st.selectbox("Select Category", main_categories)
                
                # Filter to only show unresolved items
                age_df = df_processed[(df_processed['MainCategory'] == b5_cat) & (df_processed['StatusBucket'].isin(UNRESOLVED_STATUSES))]
                if not age_df.empty:
                    st.dataframe(generate_aging_summary(age_df, 'Subcategory_Clean'), use_container_width=True)
                else:
                    st.success("No unresolved tickets found for this category.")

            elif st.session_state.current_view == "Monthly Trend Analysis":
                st.subheader("📅 Monthly Trend Analysis")
                st.caption("Compare ticket volumes and track average closure times across the year.")
                
                if all_years:
                    selected_year = st.selectbox("Select Year", all_years, key="trend_year")
                    st.markdown(f"**1. Monthly Ticket Volume ({selected_year})**")
                    
                    raised_mask = df_processed[COL_CREATED].dt.year == selected_year
                    raised_counts = df_processed[raised_mask][COL_CREATED].dt.month.value_counts().rename("Tickets Raised")
                    
                    closed_counts = pd.Series(dtype=int, name="Tickets Closed")
                    if COL_RESOLVED in df_processed.columns:
                        closed_mask = (df_processed[COL_RESOLVED].dt.year == selected_year) & (df_processed['StatusBucket'] == 'Close')
                        closed_counts = df_processed[closed_mask][COL_RESOLVED].dt.month.value_counts().rename("Tickets Closed")
                    
                    trend_df = pd.concat([raised_counts, closed_counts], axis=1).fillna(0).astype(int)
                    if not trend_df.empty:
                        trend_df = trend_df.sort_index()
                        table_df = trend_df.copy()
                        table_df.index = table_df.index.map(lambda x: calendar.month_abbr[int(x)] if pd.notna(x) else 'Unknown')
                        table_df.index.name = "Month"
                        
                        total_row = pd.DataFrame([{'Tickets Raised': table_df['Tickets Raised'].sum(), 'Tickets Closed': table_df['Tickets Closed'].sum()}], index=['**TOTAL**'])
                        st.dataframe(pd.concat([table_df, total_row]), use_container_width=True)
                        
                        chart_df = trend_df.copy()
                        chart_df.index = [f"{selected_year}-{str(int(m)).zfill(2)}" for m in chart_df.index]
                        st.bar_chart(chart_df, use_container_width=True)
                        
                        st.markdown("---")
                        st.markdown(f"**2. Average Closure Days by Subcategory ({selected_year})**")
                        
                        if COL_RESOLVED in df_processed.columns:
                            closed_year_df = df_processed[(df_processed[COL_RESOLVED].dt.year == selected_year) & (df_processed['StatusBucket'] == 'Close')].copy()
                            
                            if not closed_year_df.empty and 'ClosureTimeDays' in closed_year_df.columns:
                                closed_year_df['ResolvedMonth'] = closed_year_df[COL_RESOLVED].dt.month
                                
                                st.markdown("##### 🏢 Main Category Averages")
                                main_avg_pivot = closed_year_df.groupby(['MainCategory', 'ResolvedMonth'])['ClosureTimeDays'].mean().unstack(fill_value=None).round(1)
                                for m in range(1, 13):
                                    if m not in main_avg_pivot.columns: main_avg_pivot[m] = None
                                        
                                main_avg_pivot = main_avg_pivot[range(1, 13)]
                                main_avg_pivot.columns = [calendar.month_abbr[m] for m in range(1, 13)]
                                main_avg_pivot['Yearly Avg'] = closed_year_df.groupby('MainCategory')['ClosureTimeDays'].mean().round(1)
                                
                                monthly_avgs = closed_year_df.groupby('ResolvedMonth')['ClosureTimeDays'].mean().round(1)
                                total_row_data = {calendar.month_abbr[m]: monthly_avgs.get(m, None) for m in range(1, 13)}
                                total_row_data['Yearly Avg'] = closed_year_df['ClosureTimeDays'].mean().round(1)
                                
                                st.dataframe(pd.concat([main_avg_pivot, pd.DataFrame([total_row_data], index=['**OVERALL AVG**'])]), use_container_width=True)
                                
                                st.markdown("##### 🔍 Subcategory Drill-Down")
                                for main_cat in sorted(closed_year_df['MainCategory'].unique()):
                                    with st.expander(f"📂 {main_cat} Subcategories"):
                                        sub_df = closed_year_df[closed_year_df['MainCategory'] == main_cat]
                                        sub_pivot = sub_df.groupby(['Subcategory_Clean', 'ResolvedMonth'])['ClosureTimeDays'].mean().unstack(fill_value=None).round(1)
                                        for m in range(1, 13):
                                            if m not in sub_pivot.columns: sub_pivot[m] = None
                                        sub_pivot = sub_pivot[range(1, 13)]
                                        sub_pivot.columns = [calendar.month_abbr[m] for m in range(1, 13)]
                                        sub_pivot['Yearly Avg'] = sub_df.groupby('Subcategory_Clean')['ClosureTimeDays'].mean().round(1)
                                        st.dataframe(sub_pivot, use_container_width=True)
                                        
                                st.markdown("---")
                                st.markdown("**3. Category-wise Average Closure Trend**")
                                line_df = closed_year_df.groupby(['ResolvedMonth', 'MainCategory'])['ClosureTimeDays'].mean().unstack()
                                line_df.index = [f"{selected_year}-{str(int(m)).zfill(2)}" for m in line_df.index]
                                st.line_chart(line_df, use_container_width=True)
                            else:
                                st.info("No closure time data available.")
                else:
                    st.warning("⚠️ No valid dates found in the data.")

            elif st.session_state.current_view == "Custom Date Range Analysis":
                st.subheader("📆 Custom Date Range Analysis")
                c1, c2 = st.columns(2)
                with c1:
                    min_date = df_processed[COL_CREATED].min().date()
                    max_date = df_processed[COL_CREATED].max().date()
                    custom_dates = st.date_input("1️⃣ Select Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
                with c2:
                    custom_cat = st.selectbox("2️⃣ Select Category", ["All Categories"] + main_categories)
                    
                if len(custom_dates) == 2:
                    start_date, end_date = custom_dates
                    raised_mask = (df_processed[COL_CREATED].dt.date >= start_date) & (df_processed[COL_CREATED].dt.date <= end_date)
                    raised_df = df_processed[raised_mask]
                    
                    if COL_RESOLVED in df_processed.columns:
                        closed_mask = (df_processed[COL_RESOLVED].dt.date >= start_date) & (df_processed[COL_RESOLVED].dt.date <= end_date) & (df_processed['StatusBucket'] == 'Close')
                        closed_df = df_processed[closed_mask]
                        closed_out_of_raised_df = raised_df[(raised_df['StatusBucket'] == 'Close') & (raised_df[COL_RESOLVED].dt.date >= start_date) & (raised_df[COL_RESOLVED].dt.date <= end_date)]
                    else:
                        closed_df = closed_out_of_raised_df = pd.DataFrame(columns=df_processed.columns)
                        
                    if custom_cat != "All Categories":
                        raised_df = raised_df[raised_df['MainCategory'] == custom_cat]
                        closed_df = closed_df[closed_df['MainCategory'] == custom_cat]
                        closed_out_of_raised_df = closed_out_of_raised_df[closed_out_of_raised_df['MainCategory'] == custom_cat]
                        group_col = 'Subcategory_Clean'
                    else:
                        group_col = 'MainCategory'
                        
                    raised_grouped = raised_df.groupby(group_col).size().rename("Total Raised")
                    closed_grouped = closed_df.groupby(group_col).size().rename("Total Closed")
                    closed_out_grouped = closed_out_of_raised_df.groupby(group_col).size().rename("Closed (Out of Raised)")
                    
                    custom_summary = pd.concat([raised_grouped, closed_grouped, closed_out_grouped], axis=1).fillna(0).astype(int)
                    if not custom_summary.empty:
                        custom_summary["% of New Tickets Resolved"] = ((custom_summary["Closed (Out of Raised)"] / custom_summary["Total Raised"]) * 100).fillna(0).round(1)
                        total_raised = custom_summary["Total Raised"].sum()
                        total_row = pd.DataFrame([{
                            "Total Raised": total_raised, "Total Closed": custom_summary["Total Closed"].sum(),
                            "Closed (Out of Raised)": custom_summary["Closed (Out of Raised)"].sum(), 
                            "% of New Tickets Resolved": (custom_summary["Closed (Out of Raised)"].sum() / total_raised * 100) if total_raised > 0 else 0
                        }], index=["**TOTAL**"])
                        
                        st.dataframe(pd.concat([custom_summary, total_row]), use_container_width=True, column_config={"% of New Tickets Resolved": st.column_config.NumberColumn(format="%.1f%%")})
                        st.bar_chart(custom_summary[["Total Raised", "Total Closed", "Closed (Out of Raised)"]], use_container_width=True)
                    else:
                        st.info("No data found for this specific combination.")

            elif st.session_state.current_view == "Quarterly Performance (FY)":
                st.subheader("📊 Quarterly Performance (FY)")
                def get_fy(date_val):
                    if pd.isna(date_val): return None
                    if date_val.month <= 3: return f"{date_val.year - 1}-{str(date_val.year)[-2:]}"
                    else: return f"{date_val.year}-{str(date_val.year + 1)[-2:]}"
                def get_fy_q(date_val):
                    if pd.isna(date_val): return None
                    if date_val.month in [4, 5, 6]: return "Q1"
                    elif date_val.month in [7, 8, 9]: return "Q2"
                    elif date_val.month in [10, 11, 12]: return "Q3"
                    else: return "Q4"

                fy_df = df_processed.copy()
                fy_df['FY'] = fy_df[COL_CREATED].apply(get_fy)
                fy_df['FY_Quarter'] = fy_df[COL_CREATED].apply(get_fy_q)

                if COL_RESOLVED in fy_df.columns:
                    fy_df['Resolved_FY'] = fy_df[COL_RESOLVED].apply(get_fy)
                    fy_df['Resolved_FY_Quarter'] = fy_df[COL_RESOLVED].apply(get_fy_q)

                available_fys = sorted(fy_df['FY'].dropna().unique().tolist(), reverse=True)
                
                if available_fys:
                    c1, c2 = st.columns(2)
                    with c1: selected_fy = st.selectbox("1️⃣ Select Financial Year", available_fys)
                    with c2: quarterly_cat = st.selectbox("2️⃣ Select Category", ["All Categories"] + main_categories)
                    
                    q_base_df = fy_df[fy_df['FY'] == selected_fy].copy()
                    if COL_RESOLVED in fy_df.columns:
                        q_closed_base_df = fy_df[fy_df['Resolved_FY'] == selected_fy].copy()
                    else:
                        q_closed_base_df = pd.DataFrame(columns=fy_df.columns)

                    if quarterly_cat != "All Categories":
                        q_base_df = q_base_df[q_base_df['MainCategory'] == quarterly_cat]
                        q_closed_base_df = q_closed_base_df[q_closed_base_df['MainCategory'] == quarterly_cat]
                    
                    if not q_base_df.empty or not q_closed_base_df.empty:
                        q_raised = q_base_df.groupby('FY_Quarter').size().rename("Tickets Raised")
                        q_total_closed = q_closed_base_df[q_closed_base_df['StatusBucket'] == 'Close'].groupby('Resolved_FY_Quarter').size().rename("Total Closed")
                        
                        if COL_RESOLVED in q_base_df.columns:
                            same_q_mask = (q_base_df['StatusBucket'] == 'Close') & (q_base_df['Resolved_FY_Quarter'] == q_base_df['FY_Quarter']) & (q_base_df['Resolved_FY'] == q_base_df['FY'])
                            q_resolved = q_base_df[same_q_mask].groupby('FY_Quarter').size().rename("Resolved Same Quarter")
                        else:
                            q_resolved = pd.Series(dtype=int, name="Resolved Same Quarter")
                        
                        quarter_summary = pd.concat([q_raised, q_total_closed, q_resolved], axis=1).fillna(0).astype(int)
                        for q in ['Q1', 'Q2', 'Q3', 'Q4']:
                            if q not in quarter_summary.index: quarter_summary.loc[q] = [0, 0, 0]
                        quarter_summary = quarter_summary.sort_index()
                        quarter_summary['% Resolved Same Quarter'] = ((quarter_summary['Resolved Same Quarter'] / quarter_summary['Tickets Raised']) * 100).fillna(0).round(1)
                        
                        total_raised = quarter_summary["Tickets Raised"].sum()
                        total_row = pd.DataFrame([{
                            "Tickets Raised": total_raised, "Total Closed": quarter_summary["Total Closed"].sum(),
                            "Resolved Same Quarter": quarter_summary["Resolved Same Quarter"].sum(), 
                            "% Resolved Same Quarter": (quarter_summary["Resolved Same Quarter"].sum() / total_raised * 100) if total_raised > 0 else 0
                        }], index=["**TOTAL**"])
                        
                        st.dataframe(pd.concat([quarter_summary, total_row]), use_container_width=True, column_config={"% Resolved Same Quarter": st.column_config.NumberColumn(format="%.1f%%")})
                        st.bar_chart(quarter_summary[['Tickets Raised', 'Total Closed', 'Resolved Same Quarter']], use_container_width=True)
                        
                    st.markdown("---")
                    st.markdown("##### 🚜 Category Gap Analysis Trend")
                    c3, c4 = st.columns(2)
                    with c3: gap_fy = st.selectbox("3️⃣ Select Financial Year (Gap Trend)", available_fys, key="gap_fy")
                    with c4: gap_cats = st.multiselect("4️⃣ Select Categories", options=main_categories, default=main_categories[:2])
                    
                    if gap_cats:
                        sm_df = fy_df[(fy_df['FY'] == gap_fy) & (fy_df['MainCategory'].isin(gap_cats))].copy()
                        if not sm_df.empty:
                            sm_raised = sm_df.groupby('FY_Quarter').size().rename("Tickets Raised")
                            if COL_RESOLVED in sm_df.columns:
                                sm_closed = sm_df[(sm_df['StatusBucket'] == 'Close') & (sm_df['Resolved_FY_Quarter'] == sm_df['FY_Quarter']) & (sm_df['Resolved_FY'] == sm_df['FY'])].groupby('FY_Quarter').size().rename("Closed Same Quarter")
                            else:
                                sm_closed = pd.Series(dtype=int, name="Closed Same Quarter")
                                
                            sm_trend = pd.concat([sm_raised, sm_closed], axis=1).fillna(0).astype(int)
                            for q in ['Q1', 'Q2', 'Q3', 'Q4']:
                                if q not in sm_trend.index: sm_trend.loc[q] = [0, 0]
                            sm_trend = sm_trend.sort_index()
                            sm_trend['Gap (Unresolved)'] = sm_trend['Tickets Raised'] - sm_trend['Closed Same Quarter']
                            sm_trend['% Resolved Same Quarter'] = ((sm_trend['Closed Same Quarter'] / sm_trend['Tickets Raised']) * 100).fillna(0).round(1)
                            
                            st.dataframe(sm_trend, use_container_width=True, column_config={"% Resolved Same Quarter": st.column_config.NumberColumn(format="%.1f%%")})
                            st.line_chart(sm_trend[['Tickets Raised', 'Closed Same Quarter']], use_container_width=True)

            elif st.session_state.current_view == "Surveyor Performance":
                st.subheader("📝 Surveyor Performance")
                if COL_SURVEYOR in df_processed.columns:
                    if all_years:
                        surveyor_year = st.selectbox("Select Year", all_years)
                        surveyor_df = df_processed[df_processed[COL_CREATED].dt.year == surveyor_year]
                        if not surveyor_df.empty:
                            user_ticket_counts = surveyor_df[COL_SURVEYOR].value_counts()
                            top_users = user_ticket_counts[user_ticket_counts >= 100].index.tolist()
                            if top_users:
                                top_surveyor_df = surveyor_df[surveyor_df[COL_SURVEYOR].isin(top_users)]
                                surveyor_pivot = pd.crosstab(index=top_surveyor_df[COL_CREATED].dt.month, columns=top_surveyor_df[COL_SURVEYOR], margins=True, margins_name='**TOTAL**')
                                surveyor_pivot.index = surveyor_pivot.index.map(lambda val: calendar.month_abbr[int(val)] if str(val).isdigit() or isinstance(val, (int, float)) else val)
                                surveyor_pivot.index.name = "Month"
                                st.dataframe(surveyor_pivot, use_container_width=True)
                            else:
                                st.info(f"No surveyor raised 100+ tickets in {surveyor_year}.")
                else:
                    st.warning(f"⚠️ Column '{COL_SURVEYOR}' not found.")

        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
            st.exception(e)
    else:
        st.info("👆 Please upload the Complaints Data file in the sidebar to begin.")

if __name__ == "__main__":
    main()