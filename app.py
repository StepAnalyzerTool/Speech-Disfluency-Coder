import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime, timedelta

# --- SETTINGS & UI CONFIG ---
st.set_page_config(page_title="Disfluency Analyzer", layout="wide")
st.title("🗣️ Speech Disfluency Analyzer (v0.9)")

# --- HELPER: TIME CONVERSION ---
def get_seconds(time_str):
    """Converts HH:MM:SS or MM:SS to total seconds."""
    try:
        parts = [int(p) for p in time_str.split(':')]
        if len(parts) == 3: # HH:MM:SS
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif len(parts) == 2: # MM:SS
            return parts[0] * 60 + parts[1]
        return 0
    except:
        return 0

# --- 1. SIDEBAR: WORD LIST CONFIGURATION ---
st.sidebar.header("1. Configure Word Lists")
default_n = "uh, um, er, ah, mm-hmm, erm, hmm, eh, huh"
default_l = "like, you know, so, therefore, I mean"

n_list_input = st.sidebar.text_area("Non-Lexical (N)", value=default_n, height=100)
l_list_input = st.sidebar.text_area("Lexical (L)", value=default_l, height=100)

n_list = [w.strip().lower() for w in n_list_input.split(",")]
l_list = [w.strip().lower() for w in l_list_input.split(",")]
all_targets = n_list + l_list

# --- 2. MAIN: VISIT & SESSION METADATA ---
st.header("2. Visit & Session Information")
col_id, col_date, col_num = st.columns([1, 1, 1])
with col_id: participant_id = st.text_input("Participant ID", value="P001")
with col_date: visit_date = st.date_input("Visit Date", value=datetime.today())
with col_num: num_sessions = st.number_input("Number of Speeches", min_value=1, value=1)

sessions_config = []
st.subheader("Speech Timestamps")
cols = st.columns(int(num_sessions))
for i in range(int(num_sessions)):
    with cols[i]:
        st.markdown(f"**Speech {i+1}**")
        s_name = st.text_input(f"Topic", key=f"name_{i}", value=f"Speech {i+1}")
        s_start = st.text_input(f"Start", key=f"start_{i}", placeholder="12:00:00")
        s_end = st.text_input(f"End", key=f"end_{i}", placeholder="12:02:00")
        sessions_config.append({"name": s_name, "start": s_start, "end": s_end, "idx": i})

# --- 3. TRANSCRIPT INPUT ---
st.header("3. Input Transcript")
raw_transcript = st.text_area("Paste the full transcript here:", height=200)

# --- 4. ENGINE ---
def is_filler_heuristic(target, context_prev, context_next):
    # (Heuristics remain same as v0.8)
    target = target.lower()
    prev_word = re.sub(r'[^\w]', '', context_prev[-1].lower()) if context_prev else ""
    next_word = re.sub(r'[^\w]', '', context_next[0].lower()) if context_next else ""
    linking_verbs = ["is", "was", "am", "are", "were", "be", "been", "being", "become", "becomes", "became"]
    if target == "so":
        if prev_word in linking_verbs: return False
        if next_word in ["many", "much", "that", "far", "fast", "long", "as", "busy", "good", "bad"]: return False
        if next_word.endswith('y') or next_word.endswith('ed'): return False
    if target == "like":
        if prev_word in ["i", "you", "he", "she", "it", "we", "they", "to"]: return False
        if next_word in ["to", "a", "an", "the"]: return False
    return True

def analyze_text(text_block, n_list, l_list):
    clean_block = re.sub(r'\d{1,2}:\d{2}(:\d{2})?', '', text_block)
    clean_block = " ".join(clean_block.split())
    words = clean_block.split()
    findings = []
    flagged_indices = []
    combined_list = sorted(n_list + l_list, key=len, reverse=True)

    for target in combined_list:
        matches = re.finditer(rf'\b{re.escape(target)}\b', clean_block.lower())
        for m in matches:
            if any(i in range(m.start(), m.end()) for i in flagged_indices): continue
            word_idx = len(clean_block[:m.start()].split())
            prev_context = words[max(0, word_idx-1):word_idx]
            next_context = words[word_idx+len(target.split()):word_idx+len(target.split())+1]
            
            if is_filler_heuristic(target, prev_context, next_context) or target in n_list:
                flagged_indices.extend(range(m.start(), m.end()))
                findings.append({
                    "Word": target, "Category": "Non-Lexical" if target in n_list else "Lexical",
                    "Context": "... " + " ".join(words[max(0, word_idx-2):word_idx+3]) + " ...",
                    "Is Filler?": True, "Count": len(target.split()), "start": m.start(), "end": m.end()
                })
    return sorted(findings, key=lambda x: x['start']), words

# --- 5. EXECUTION & TABS ---
if raw_transcript:
    st.divider()
    all_session_data = []
    lines = raw_transcript.split('\n')
    tabs = st.tabs([s['name'] for s in sessions_config])

    for i, tab in enumerate(tabs):
        with tab:
            cfg = sessions_config[i]
            session_text = ""
            in_range = False
            for line in lines:
                if cfg['start'] and cfg['start'] in line: in_range = True
                if in_range: session_text += line + " "
                if cfg['end'] and cfg['end'] in line: in_range = False; break
            
            if session_text:
                findings, words = analyze_text(session_text, n_list, l_list)
                
                # Calculation Logic
                st.subheader(f"Verify: {cfg['name']}")
                df = pd.DataFrame(findings)
                edited_df = st.data_editor(df[["Context", "Word", "Category", "Is Filler?"]], key=f"editor_{i}", width=800)
                
                # Filtering only confirmed disfluencies
                confirmed = edited_df[edited_df["Is Filler?"] == True]
                
                # Metrics
                total_n = confirmed[confirmed["Category"] == "Non-Lexical"]["Word"].count()
                # For Lexical, we count occurrences, but "you know" = 2 disfluencies
                total_l = sum(confirmed[confirmed["Category"] == "Lexical"]["Word"].apply(lambda x: len(x.split())))
                total_dis = total_n + total_l
                
                raw_word_count = len(words)
                func_words = raw_word_count - total_dis
                
                duration_sec = get_seconds(cfg['end']) - get_seconds(cfg['start'])
                duration_min = duration_sec / 60 if duration_sec > 0 else 0
                
                # Display Metrics
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Functional Words", func_words)
                m2.metric("Total Disfluencies", total_dis)
                m3.metric("Duration", f"{duration_min:.2f} min")
                m4.metric("Fluency (WPM)", f"{(func_words/duration_min):.1f}" if duration_min > 0 else "0")

                # Store for Export
                session_results = {
                    "Participant_ID": participant_id, "Date": visit_date, 
                    "Speech_#": i+1, "Topic": cfg['name'], "Duration_Min": round(duration_min, 2),
                    "Total_Words_Functional": func_words, 
                    "Fluency_WPM": round(func_words/duration_min, 2) if duration_min > 0 else 0,
                    "Total_Dis_per_100": round((total_dis/func_words)*100, 2) if func_words > 0 else 0,
                    "Lexical_per_100": round((total_l/func_words)*100, 2) if func_words > 0 else 0,
                    "NonLexical_per_100": round((total_n/func_words)*100, 2) if func_words > 0 else 0,
                    "Total_Dis_per_Min": round(total_dis/duration_min, 2) if duration_min > 0 else 0,
                    "Lexical_per_Min": round(total_l/duration_min, 2) if duration_min > 0 else 0,
                    "NonLexical_per_Min": round(total_n/duration_min, 2) if duration_min > 0 else 0,
                }
                
                # Individual Counts
                for target in all_targets:
                    session_results[f"Count_{target}"] = confirmed[confirmed["Word"] == target]["Word"].count()
                
                all_session_data.append(session_results)

    # --- 6. EXPORT BUTTON ---
    st.divider()
    if all_session_data:
        final_df = pd.DataFrame(all_session_data)
        st.subheader("4. Final Report Preview")
        st.dataframe(final_df)
        
        # Excel Export Logic
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            final_df.to_excel(writer, index=False, sheet_name='Disfluency_Report')
        
        st.download_button(
            label="📥 Download Excel Report",
            data=buffer.getvalue(),
            file_name=f"Disfluency_Report_{participant_id}_{visit_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
