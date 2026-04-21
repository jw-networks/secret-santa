import csv
import io
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Set, Tuple

import base64
import requests
import streamlit as st

# 405th-inspired palette
PRIMARY = "#69C5E8"
SECONDARY = "#0F7F8A"
ACCENT = "#1D1D22"
TEXT = "#F4F7FA"
MUTED = "#9ECFDF"


Pair = Tuple[str, str]
HistoryPair = Tuple[str, str, str]


class SecretSantaError(Exception):
    pass


@dataclass(frozen=True)
class HistoryRecord:
    year: str
    giver: str
    recipient: str


def normalize_name(name: str) -> str:
    return name.strip()


def parse_names_from_text(text: str) -> List[str]:
    names = [normalize_name(line) for line in text.splitlines()]
    names = [name for name in names if name]

    if len(names) < 2:
        raise SecretSantaError("At least 2 valid names are required.")

    if len(set(names)) != len(names):
        raise SecretSantaError("Duplicate names found in the participant list.")

    return names


def parse_names_from_csv(file_bytes: bytes) -> List[str]:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if "name" not in (reader.fieldnames or []):
        raise SecretSantaError("Names CSV must contain a 'name' column.")

    names: List[str] = []
    for row in reader:
        name = normalize_name(row.get("name", ""))
        if name:
            names.append(name)

    if len(names) < 2:
        raise SecretSantaError("At least 2 valid names are required.")

    if len(set(names)) != len(names):
        raise SecretSantaError("Duplicate names found in the participant list.")

    return names


def parse_history_from_csv(file_bytes: bytes) -> List[HistoryRecord]:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = {"year", "giver", "recipient"}
    if not required.issubset(set(reader.fieldnames or [])):
        raise SecretSantaError("History CSV must contain 'year', 'giver', and 'recipient' columns.")

    history: List[HistoryRecord] = []
    for row in reader:
        year = str(row.get("year", "")).strip()
        giver = normalize_name(row.get("giver", ""))
        recipient = normalize_name(row.get("recipient", ""))
        if year and giver and recipient:
            history.append(HistoryRecord(year=year, giver=giver, recipient=recipient))

    return history


def build_history_set(history: List[HistoryRecord]) -> Set[Pair]:
    return {(record.giver, record.recipient) for record in history}


def is_valid_assignment(
    giver: str,
    recipient: str,
    assignments: Dict[str, str],
    history_pairs: Set[Pair],
) -> bool:
    if giver == recipient:
        return False

    if (giver, recipient) in history_pairs:
        return False

    if recipient in assignments.values():
        return False

    # Prevent A -> B and B -> A in the same round.
    if assignments.get(recipient) == giver:
        return False

    return True


def generate_assignments(
    names: List[str],
    history: List[HistoryRecord],
    max_attempts: int = 10000,
) -> Dict[str, str]:
    if len(names) == 2:
        raise SecretSantaError("With only 2 participants, reciprocal gifting is unavoidable.")

    history_pairs = build_history_set(history)

    for _ in range(max_attempts):
        assignments: Dict[str, str] = {}
        givers = names[:]
        random.shuffle(givers)

        for giver in givers:
            candidates = [
                recipient
                for recipient in names
                if is_valid_assignment(giver, recipient, assignments, history_pairs)
            ]
            random.shuffle(candidates)

            if not candidates:
                break

            assignments[giver] = candidates[0]

        if len(assignments) == len(names):
            return assignments

    raise SecretSantaError(
        "No valid assignment could be found with the current constraints. Try adding more participants or relaxing history."
    )


def assignments_to_csv(assignments: Dict[str, str], year: str) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["year", "giver", "recipient"])
    for giver, recipient in sorted(assignments.items()):
        writer.writerow([year, giver, recipient])
    return output.getvalue()


def names_template_csv() -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name"])
    writer.writerow(["Alice"])
    writer.writerow(["Bob"])
    writer.writerow(["Charlie"])
    return output.getvalue()


def history_template_csv() -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["year", "giver", "recipient"])
    writer.writerow(["2024", "Alice", "Bob"])
    writer.writerow(["2024", "Bob", "Charlie"])
    writer.writerow(["2025", "Charlie", "Alice"])
    return output.getvalue()


def combine_history(history: List[HistoryRecord], assignments: Dict[str, str], year: str) -> List[HistoryRecord]:
    updated = history[:]
    for giver, recipient in sorted(assignments.items()):
        updated.append(HistoryRecord(year=year, giver=giver, recipient=recipient))
    return updated


def history_to_csv(history: List[HistoryRecord]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["year", "giver", "recipient"])
    for record in history:
        writer.writerow([record.year, record.giver, record.recipient])
    return output.getvalue()


def github_headers() -> Dict[str, str]:
    token = st.secrets["github"]["token"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_github_file(path: str) -> Dict[str, str]:
    owner = st.secrets["github"]["owner"]
    repo = st.secrets["github"]["repo"]
    branch = st.secrets["github"].get("branch", "main")

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    response = requests.get(
        url,
        headers=github_headers(),
        params={"ref": branch},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def load_github_file_text(path: str) -> str:
    current = fetch_github_file(path)

    encoded = current["content"]
    encoded = encoded.replace("\n", "")  # remove real newlines

    return base64.b64decode(encoded).decode("utf-8")


def save_github_file(path: str, content_text: str, commit_message: str) -> None:
    owner = st.secrets["github"]["owner"]
    repo = st.secrets["github"]["repo"]
    branch = st.secrets["github"].get("branch", "main")

    current = fetch_github_file(path)
    sha = current["sha"]

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    encoded_content = base64.b64encode(content_text.encode("utf-8")).decode("utf-8")

    payload = {
        "message": commit_message,
        "content": encoded_content,
        "sha": sha,
        "branch": branch,
    }

    response = requests.put(
        url,
        headers=github_headers(),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()


def main() -> None:
    st.set_page_config(page_title="405th Secret Santa", page_icon="🎁", layout="wide")

    st.markdown(
        f"""
        <style>
            .stApp {{
                background: radial-gradient(circle at top, rgba(15,127,138,0.28), rgba(0,0,0,0) 35%),
                            linear-gradient(180deg, #091115 0%, #0c161b 45%, #081014 100%);
                color: {TEXT};
            }}
            .block-container {{
                padding-top: 2rem;
                padding-bottom: 2rem;
                max-width: 1100px;
            }}
            h1, h2, h3 {{
                color: {TEXT};
                letter-spacing: 0.02em;
            }}
            .hero-card, .section-card {{
                background: linear-gradient(180deg, rgba(29,29,34,0.94), rgba(16,23,29,0.96));
                border: 1px solid rgba(105,197,232,0.28);
                border-radius: 20px;
                box-shadow: 0 8px 30px rgba(0,0,0,0.28);
            }}
            .hero-card {{
                padding: 1.35rem 1.5rem;
                margin-bottom: 1rem;
                position: relative;
                overflow: hidden;
            }}
            .hero-card:before {{
                content: "";
                position: absolute;
                inset: 0;
                background: linear-gradient(90deg, rgba(105,197,232,0.08), rgba(15,127,138,0.05));
                pointer-events: none;
            }}
            .section-card {{
                padding: 1rem 1rem 0.5rem 1rem;
                margin-bottom: 1rem;
            }}
            .eyebrow {{
                color: {PRIMARY};
                font-size: 0.86rem;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.12em;
                margin-bottom: 0.35rem;
            }}
            .hero-title {{
                font-size: 2.2rem;
                font-weight: 800;
                margin-bottom: 0.35rem;
                line-height: 1.05;
            }}
            .hero-sub {{
                color: {MUTED};
                font-size: 1rem;
                max-width: 760px;
            }}
            .rule-box {{
                background: rgba(105,197,232,0.08);
                border: 1px solid rgba(105,197,232,0.18);
                border-radius: 16px;
                padding: 0.9rem 1rem;
                margin-top: 0.25rem;
            }}
            .stButton > button, .stDownloadButton > button {{
                border-radius: 999px;
                border: 1px solid rgba(105,197,232,0.35);
                background: linear-gradient(180deg, {PRIMARY}, #59b8dc);
                color: #081014;
                font-weight: 800;
            }}
            .stButton > button:hover, .stDownloadButton > button:hover {{
                border-color: rgba(105,197,232,0.65);
                box-shadow: 0 0 0 2px rgba(105,197,232,0.12);
            }}
            .stTextInput input, .stTextArea textarea, .stFileUploader {{
                background: rgba(255,255,255,0.03);
                border-radius: 14px;
            }}
            [data-testid="stDataFrame"] {{
                border: 1px solid rgba(105,197,232,0.2);
                border-radius: 16px;
                overflow: hidden;
            }}
            .footer-note {{
                color: {MUTED};
                font-size: 0.92rem;
            }}
        </style>
        <div class="hero-card">
            <div class="eyebrow">405th Infantry Division</div>
            <div class="hero-title">Secret Santa Generator</div>
            <div class="hero-sub">Built with a 405th-inspired interface using cool blue highlights, dark tactical panels, and a cleaner event-ready layout.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write(
        "Upload names and optional pairing history, then generate a new round that avoids self-pairs, repeat giver→recipient pairs, and mutual swaps."
    )

    current_year = str(datetime.now().year)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    top_left, top_right = st.columns([1, 1])
    with top_left:
        year = st.text_input("Year for this round", value=current_year)
    with top_right:
        st.markdown(
            '<div class="rule-box"><strong>Rules enforced</strong><br>No self-pairing<br>No repeated giver → recipient from history<br>No two-person swap in the same round</div>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Participants")
    names_file = st.file_uploader("Upload names CSV", type=["csv"], key="names_file")
    names_text = st.text_area(
        "Or paste one name per line",
        placeholder="Alice\nBob\nCharlie\nDana",
        height=180,
    )

    st.subheader("History")
    history_file = st.file_uploader("Upload history CSV (optional)", type=["csv"], key="history_file")

    h1, h2 = st.columns(2)
    with h1:
        if st.button("Load official history from GitHub", use_container_width=True):
            try:
                history_text = load_github_file_text(st.secrets["github"]["history_path"])
                st.session_state["loaded_history_bytes"] = history_text.encode("utf-8")
                loaded_history = parse_history_from_csv(st.session_state["loaded_history_bytes"])
                st.session_state["loaded_history_count"] = len(loaded_history)
                st.success(f"Loaded {len(loaded_history)} history records from GitHub.")
            except requests.HTTPError as error:
                st.error(
                    f"GitHub API error: {error.response.status_code} {error.response.text}"
                )
            except Exception as error:
                st.error(f"Load failed: {error}")
    with h2:
        if st.button("Clear loaded history", use_container_width=True):
            st.session_state.pop("loaded_history_bytes", None)
            st.session_state.pop("loaded_history_count", None)
            st.success("Loaded GitHub history cleared.")

    if "loaded_history_count" in st.session_state:
        st.caption(f"Official GitHub history loaded: {st.session_state['loaded_history_count']} records")

    with st.expander("CSV templates"):
        st.download_button(
            "Download names template",
            data=names_template_csv(),
            file_name="names_template.csv",
            mime="text/csv",
        )
        st.download_button(
            "Download history template",
            data=history_template_csv(),
            file_name="history_template.csv",
            mime="text/csv",
        )

    st.markdown('</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([1.1, 0.9])

    with col1:
        if st.button("Generate pairings", type="primary", use_container_width=True):
            try:
                if names_file is not None:
                    names = parse_names_from_csv(names_file.getvalue())
                else:
                    names = parse_names_from_text(names_text)

                history: List[HistoryRecord] = []
                if history_file is not None:
                    history = parse_history_from_csv(history_file.getvalue())
                elif "loaded_history_bytes" in st.session_state:
                    history = parse_history_from_csv(st.session_state["loaded_history_bytes"])

                assignments = generate_assignments(names, history)
                updated_history = combine_history(history, assignments, year)

                st.session_state["assignments"] = assignments
                st.session_state["updated_history"] = updated_history
                st.session_state["year"] = year
                st.session_state["names_count"] = len(names)

            except SecretSantaError as error:
                st.error(str(error))
            except Exception as error:
                st.error(f"Unexpected error: {error}")

    with col2:
        st.markdown(
            '<div class="section-card"><div class="eyebrow">Event notes</div><p class="footer-note">Upload an existing history file if you want this year to avoid prior pairings. After generating, download the updated history file and use that next time.</p></div>',
            unsafe_allow_html=True,
        )

    if "assignments" in st.session_state:
        assignments = st.session_state["assignments"]
        updated_history = st.session_state["updated_history"]
        run_year = st.session_state["year"]

        st.success(f"Generated pairings for {st.session_state['names_count']} participants.")

        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.subheader("Assignments")
        st.dataframe(
            [{"giver": giver, "recipient": recipient} for giver, recipient in sorted(assignments.items())],
            use_container_width=True,
        )

        assignments_csv = assignments_to_csv(assignments, run_year)
        updated_history_csv = history_to_csv(updated_history)

        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "Download assignments CSV",
                data=assignments_csv,
                file_name=f"assignments_{run_year}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with d2:
            st.download_button(
                "Download updated history CSV",
                data=updated_history_csv,
                file_name="history_updated.csv",
                mime="text/csv",
                use_container_width=True,
            )

        st.divider()
        st.subheader("Official history save")

        commit_message = st.text_input(
            "Commit message",
            value=f"Update Secret Santa history for {run_year}",
        )

        if st.button("Save history to GitHub", use_container_width=True):
            try:
                save_github_file(
                    path=st.secrets["github"]["history_path"],
                    content_text=updated_history_csv,
                    commit_message=commit_message,
                )
                st.success("History saved to GitHub.")
                st.session_state["loaded_history_bytes"] = updated_history_csv.encode("utf-8")
                st.session_state["loaded_history_count"] = len(updated_history)
            except requests.HTTPError as error:
                st.error(
                    f"GitHub API error: {error.response.status_code} {error.response.text}"
                )
            except Exception as error:
                st.error(f"Save failed: {error}")

        st.markdown('</div>', unsafe_allow_html=True)

        st.info(
            "Use the updated history CSV next time so this year's pairings are automatically blocked in future rounds."
        )


if __name__ == "__main__":
    main()
