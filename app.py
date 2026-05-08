import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime

# --- SETTINGS & UI CONFIG ---
st.set_page_config(page_title="Disfluency Analyzer", layout="wide")
st.title("🗣️ Speech Disfluency Analyzer (v1.5)")

# --- HELPERS ---
def get_seconds(time_str):
    try:
        parts = [int(p) for p in time_str.split(':')]
        if len(parts) == 3: return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2: return parts[0] * 60 + parts[1]
        return 0
    except: return 0

def extract_timestamp(line):
    match = re.search(r'(\d{1,2}:\d{2}:\d{2})|(\d{1,2}:\d{2})', line)
    return get_seconds(match.group(0)) if match else None

def clean_transcript_clutter(text, markers, general_exclusions):
    # 1. Remove VTT markers and timestamps
    text = re.sub(r'\d{1,2}:\d{2}:\d{2}\.\d{3} --> \d{1,2}:\d{2}:\d{2}\.\d{3}', '', text)
    text = re.sub(r'\b\d{1,2}:\d{2}(:\d{2})?\b', '', text)
    text = re.sub(r'^[A-Za-z\s\d]+:', '', text, flags=re.MULTILINE)
    
    # 2. START MARKER LOGIC: Delete everything before and including the marker
    for m in markers:
        m_clean = m.strip()
        if m_clean:
            # Flexible regex for digits/words (e.g. "one" or "1")
            pattern = rf'\b{re.escape(m_clean)}\b'
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match and match.start() < 150: # Only nukes if found at the beginning
                text = text[match.end():]
                break # Only process the first marker found

    # 3. GENERAL EXCLUSIONS (Mid-speech phrases)
    for phrase in general_exclusions:
        p_clean = phrase.strip()
        if p_clean:
            pattern = re.escape(p_clean).replace(r'\ ', r'\s+')
            text = re.sub(pattern + r'[\s,.]*', '', text, flags=re.IGNORECASE)
            
    text = re.sub(r'\s+', ' ', text)
    return text.strip(",. ")

# --- 1. SIDEBAR: CONFIGURATION ---
st.sidebar.header("1. Configure Analysis")
n_input = st.sidebar.text_area("Non-Lexical (N)", value="uh, um, er, ah, mm-hmm, erm, hmm, eh, huh", height=80)
l_input = st.sidebar.text_area("Lexical (L)", value="like, you know, so, therefore, I mean", height=80)

st.sidebar.markdown("---")
st.sidebar.subheader("Protocol Cleaning")
# NEW: Specifically for the "one" in "3, 2, 1"
marker_input = st.sidebar.text_area("Speech Start Markers (e.g. 'one'):", 
                                    value="one, 1, start, beginning", height=100)
ex_input = st.sidebar.text_area("Other Exclusions (One per line):", 
                                value="thank you for listening\nend of session", height=80)

n_list = [w.strip().lower() for w in n_input.split(",")]
l_list = [w.strip().lower() for w in l_input.split(",")]
markers = [m.strip() for m in marker_input.split(",") if m.strip()]
exclude_list = [p.strip() for p in ex_input.split("\n") if p.strip()]

# --- 2. VISIT METADATA ---
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
        s_start = st.text_input(f"Start", key=f"start_{i}", placeholder="00:00:00")
        s_end = st.text_input(f"End", key=f"end_{i}", placeholder="00:05:00")
        sessions_config.append({"name": s_name, "start": s_start, "end": s_end})

raw_transcript = st.text_area("3. Paste Transcript Here:", height=200)

# --- 3. ANALYSIS ENGINE ---
def is_filler_heuristic(target, prev, nxt):
    target = target.lower()
    p = re.sub(r'[^\w]', '', prev[-1].lower()) if prev else ""
    n = re.sub(r'[^\w]', '', nxt[0].lower()) if nxt else ""
    if target == "so":
        if p in ["is", "was", "am", "are", "were", "be", "been"]: return False
        if n in ["many", "much", "that", "far", "fast", "long", "as", "busy", "good"]: return False
        if n.endswith('y') or n.endswith('ed'): return False
    if target == "like":
        if p in ["i", "you", "he", "she", "it", "we", "they", "to"]: return False
        if n in ["to", "a", "an", "the"]: return False
    return True

def analyze_segment(text_block, n_list, l_list, markers, exclude_list):
    clean_text = clean_transcript_clutter(text_block, markers, exclude_list)
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
    
    sorted_findings = sorted(findings, key=lambda x: x['start'], reverse=True)
    highlighted = clean_text
    for f in sorted_findings:
        original = highlighted[f['start']:f['end']]
        highlighted = highlighted[:f['start']] + f"**[{original}]**" + highlighted[f['end']:]
    return sorted(findings, key=lambda x: x['start']), words, highlighted

# --- 4. DISPLAY ---
if raw_transcript:
    st.divider()
    report_data = []
    lines = raw_transcript.split('\n')
    tabs = st.tabs([s['name'] for s in sessions_config])
    
    for i, tab in enumerate(tabs):
        with tab:
            cfg = sessions_config[i]
            start_s, end_s = get_seconds(cfg['start']), get_seconds(cfg['end'])
            seg_lines = []
            current_time = -1
            for line in lines:
                ts = extract_timestamp(line); 
                if ts is not None: current_time = ts
                if start_s <= current_time <= end_s and not re.match(r'^\d{2}:\d{2}:\d{2}', line.strip()):
                    seg_lines.append(line)
            
            seg_text = " ".join(seg_lines)
            if seg_text.strip():
                findings, words, highlight = analyze_segment(seg_text, n_list, l_list, markers, exclude_list)
                st.subheader("Visual Audit")
                st.markdown(highlight)
                st.divider()
                
                st.subheader(f"Verify Counts: {cfg['name']}")
                df_f = pd.DataFrame(findings) if findings else pd.DataFrame(columns=["Context", "Word", "Category", "Is Filler?"])
                edited_df = st.data_editor(df_f[["Context", "Word", "Category", "Is Filler?"]], key=f"edit_{i}", width=800)
                
                confirmed = edited_df[edited_df["Is Filler?"] == True]
                total_n = confirmed[confirmed["Category"] == "Non-Lexical"]["Word"].count()
                total_l = sum(confirmed[confirmed["Category"] == "Lexical"]["Word"].apply(lambda x: len(x.split())))
                total_dis = total_n + total_l
                func_words = len(words) - total_dis
                dur_m = (end_s - start_s) / 60
                
                st.markdown("### 📊 Session Summary")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Dis_per_Min", f"{total_dis/dur_m:.2f}" if dur_m > 0 else "0")
                m2.metric("Dis_per_100_Words", f"{(total_dis/func_words)*100:.2f}" if func_words > 0 else "0")
                m3.metric("Functional Words", func_words)
                m4.metric("Duration (min)", f"{dur_m:.2f}")

                row = {"ID": participant_id, "Date": visit_date, "Speech_#": i+1, "Topic": cfg['name'], "Dur": round(dur_m, 2), "Func_Words": func_words, "Dis_per_Min": round(total_dis/dur_m, 2), "Dis_per_100": round((total_dis/func_words)*100, 2)}
                for t in (n_list + l_list): row[f"Count_{t}"] = confirmed[confirmed["Word"] == t]["Word"].count()
                report_data.append(row)
            else: st.warning(f"No text found.")

    if report_data:
        st.divider(); st.subheader("4. Final Report Preview")
        final_df = pd.DataFrame(report_data); st.dataframe(final_df)
        try:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='openpyxl') as writer: final_df.to_excel(writer, index=False)
            st.download_button("📥 Download Excel Report", data=buf.getvalue(), file_name=f"Report_{participant_id}.xlsx")
        except: st.download_button("📥 Download CSV", data=final_df.to_csv(index=False).encode('utf-8'), file_name=f"Report_{participant_id}.csv")
