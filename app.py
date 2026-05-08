import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime

# --- SETTINGS & UI CONFIG ---
st.set_page_config(page_title="Disfluency Analyzer", layout="wide")
st.title("🗣️ Speech Disfluency Analyzer (v1.1)")

# --- HELPERS ---
def get_seconds(time_str):
    try:
        parts = [int(p) for p in time_str.split(':')]
        if len(parts) == 3: return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2: return parts[0] * 60 + parts[1]
        return 0
    except: return 0

def extract_timestamp(line):
    # Matches common transcript formats like 00:28:34 or 12:30:00
    match = re.search(r'(\d{1,2}:\d{2}:\d{2})', line)
    return get_seconds(match.group(1)) if match else None

def clean_transcript_clutter(text):
    # Removes VTT markers, arrows, and sub-second decimals
    text = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}', '', text)
    text = re.sub(r'\b\d{1,2}:\d{2}(:\d{2})?\b', '', text)
    return " ".join(text.split())

# --- 1. SIDEBAR ---
st.sidebar.header("1. Configure Word Lists")
n_input = st.sidebar.text_area("Non-Lexical (N)", value="uh, um, er, ah, mm-hmm, erm, hmm, eh, huh", height=100)
l_input = st.sidebar.text_area("Lexical (L)", value="like, you know, so, therefore, I mean", height=100)
n_list = [w.strip().lower() for w in n_input.split(",")]
l_list = [w.strip().lower() for w in l_input.split(",")]

# --- 2. METADATA ---
st.header("2. Visit & Session Information")
c1, c2, c3 = st.columns(3)
with c1: participant_id = st.text_input("Participant ID", value="P001")
with c2: visit_date = st.date_input("Visit Date", value=datetime.today())
with c3: num_sessions = st.number_input("Number of Speeches", min_value=1, value=1)

sessions_config = []
st.subheader("Speech Timestamps")
cols = st.columns(int(num_sessions))
for i in range(int(num_sessions)):
    with cols[i]:
        st.markdown(f"**Speech {i+1}**")
        s_name = st.text_input(f"Topic", key=f"name_{i}", value=f"Speech {i+1}")
        s_start = st.text_input(f"Start", key=f"start_{i}", value="00:00:00")
        s_end = st.text_input(f"End", key=f"end_{i}", value="00:05:00")
        sessions_config.append({"name": s_name, "start": s_start, "end": s_end})

raw_transcript = st.text_area("3. Paste Transcript Here:", height=200)

# --- 3. ANALYSIS LOGIC ---
def is_filler_heuristic(target, prev, nxt):
    target = target.lower()
    p = re.sub(r'[^\w]', '', prev[-1].lower()) if prev else ""
    n = re.sub(r'[^\w]', '', nxt[0].lower()) if nxt else ""
    if target == "so":
        if p in ["is", "was", "am", "are", "were", "be"]: return False
        if n in ["many", "much", "that", "far", "fast", "long", "as", "busy", "good"]: return False
        if n.endswith('y') or n.endswith('ed'): return False
    if target == "like":
        if p in ["i", "you", "he", "she", "it", "we", "they", "to"]: return False
        if n in ["to", "a", "an", "the"]: return False
    return True

def analyze_segment(text_block, n_list, l_list):
    clean_text = clean_transcript_clutter(text_block)
    words = clean_text.split()
    findings = []
    flagged_indices = []
    combined = sorted(n_list + l_list, key=len, reverse=True)

    for target in combined:
        matches = re.finditer(rf'\b{re.escape(target)}\b', clean_text.lower())
        for m in matches:
            if any(i in range(m.start(), m.end()) for i in flagged_indices): continue
            word_idx = len(clean_text[:m.start()].split())
            p_ctx = words[max(0, word_idx-1):word_idx]
            n_ctx = words[word_idx+len(target.split()):word_idx+len(target.split())+1]
            
            if is_filler_heuristic(target, p_ctx, n_ctx) or target in n_list:
                flagged_indices.extend(range(m.start(), m.end()))
                findings.append({
                    "Word": target, "Category": "Non-Lexical" if target in n_list else "Lexical",
                    "Context": "... " + " ".join(words[max(0, word_idx-2):word_idx+3]) + " ...",
                    "Is Filler?": True, "Count": len(target.split()), "start": m.start(), "end": m.end()
                })
    
    # Create Highlighted Preview
    sorted_findings = sorted(findings, key=lambda x: x['start'], reverse=True)
    highlighted = clean_text
    for f in sorted_findings:
        original = highlighted[f['start']:f['end']]
        highlighted = highlighted[:f['start']] + f"**[{original}]**" + highlighted[f['end']:]
        
    return sorted(findings, key=lambda x: x['start']), words, highlighted

# --- 4. DISPLAY TABS ---
if raw_transcript:
    st.divider()
    report_data = []
    lines = raw_transcript.split('\n')
    tabs = st.tabs([s['name'] for s in sessions_config])
    
    for i, tab in enumerate(tabs):
        with tab:
            cfg = sessions_config[i]
            start_s, end_s = get_seconds(cfg['start']), get_seconds(cfg['end'])
            
            # Extract relevant lines
            seg_lines = []
            for line in lines:
                ts = extract_timestamp(line)
                if ts and start_s <= ts <= end_s: seg_lines.append(line)
            
            seg_text = " ".join(seg_lines)
            if seg_text:
                findings, words, highlighted_text = analyze_segment(seg_text, n_list, l_list)
                
                st.subheader("Visual Audit (Automated Flags)")
                st.markdown(highlighted_text)
                st.divider()
                
                st.subheader(f"Verify Counts: {cfg['name']}")
                df_findings = pd.DataFrame(findings) if findings else pd.DataFrame(columns=["Context", "Word", "Category", "Is Filler?"])
                edited_df = st.data_editor(df_findings[["Context", "Word", "Category", "Is Filler?"]], key=f"edit_{i}", width=800)
                
                # Calculations
                confirmed = edited_df[edited_df["Is Filler?"] == True]
                total_n = confirmed[confirmed["Category"] == "Non-Lexical"]["Word"].count()
                total_l = sum(confirmed[confirmed["Category"] == "Lexical"]["Word"].apply(lambda x: len(x.split())))
                total_dis = total_n + total_l
                func_words = len(words) - total_dis
                dur_m = (end_s - start_s) / 60
                
                # Requested Summary Stats
                st.markdown("### 📊 Session Summary")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Disfluencies per Minute", f"{total_dis/dur_m:.2f}" if dur_m > 0 else "0")
                m2.metric("Disfluencies per 100 Words", f"{(total_dis/func_words)*100:.2f}" if func_words > 0 else "0")
                m3.metric("Functional Words", func_words)
                m4.metric("Duration (min)", f"{dur_m:.2f}")

                # Save for Master Report
                row = {
                    "Participant_ID": participant_id, "Date": visit_date, "Speech_#": i+1, "Topic": cfg['name'],
                    "Duration_Min": round(dur_m, 2), "Total_Words_Functional": func_words,
                    "Dis_per_Minute": round(total_dis/dur_m, 2) if dur_m > 0 else 0,
                    "Dis_per_100_Words": round((total_dis/func_words)*100, 2) if func_words > 0 else 0,
                }
                for t in (n_list + l_list):
                    row[f"Count_{t}"] = confirmed[confirmed["Word"] == t]["Word"].count()
                report_data.append(row)
            else:
                st.warning(f"No text found for {cfg['start']} to {cfg['end']}.")

    # --- 5. EXPORT ---
    if report_data:
        st.divider()
        st.subheader("4. Final Report Preview")
        final_df = pd.DataFrame(report_data)
        st.dataframe(final_df)
        
        # Download Logic
        try:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as writer:
                final_df.to_excel(writer, index=False)
            st.download_button("📥 Download Excel Report", data=buf.getvalue(), file_name=f"Report_{participant_id}.xlsx")
        except:
            st.download_button("📥 Download CSV Report", data=final_df.to_csv(index=False).encode('utf-8'), file_name=f"Report_{participant_id}.csv")
