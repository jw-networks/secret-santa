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


class SecretSantaError(Exception):
    pass


@dataclass(frozen=True)
class Participant:
    name: str
    regiment: str = ""


@dataclass(frozen=True)
class HistoryRecord:
    year: str
    giver: str
    recipient: str


def normalize_name(name: str) -> str:
    return name.strip()


def normalize_regiment(regiment: str) -> str:
    return regiment.strip()


def parse_names_from_text(text: str) -> List[str]:
    names = [normalize_name(line) for line in text.splitlines()]
    names = [name for name in names if name]

    if len(names) < 2:
        raise SecretSantaError("At least 2 valid names are required.")

    if len(set(names)) != len(names):
        raise SecretSantaError("Duplicate names found in the participant list.")

    return names


def parse_participants_from_text(text: str) -> List[Participant]:
    text = text.strip()

    if not text:
        raise SecretSantaError("At least 2 valid names are required.")

    # CSV paste mode
    if "," in text.splitlines()[0]:
        reader = csv.DictReader(io.StringIO(text))

        if "name" not in (reader.fieldnames or []):
            raise SecretSantaError("Pasted CSV must contain a 'name' column.")

        participants: List[Participant] = []

        for row in reader:
            name = normalize_name(row.get("name", ""))
            regiment = normalize_regiment(row.get("regiment", ""))

            if name:
                participants.append(Participant(name=name, regiment=regiment))

    # Plain one-name-per-line mode
    else:
        names = parse_names_from_text(text)
        participants = [Participant(name=name) for name in names]

    names = [participant.name for participant in participants]

    if len(participants) < 2:
        raise SecretSantaError("At least 2 valid names are required.")

    if len(set(names)) != len(names):
        raise SecretSantaError("Duplicate names found in the participant list.")

    return participants


def parse_participants_from_csv(file_bytes: bytes) -> List[Participant]:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    if "name" not in (reader.fieldnames or []):
        raise SecretSantaError("Names CSV must contain a 'name' column.")

    participants: List[Participant] = []

    for row in reader:
        name = normalize_name(row.get("name", ""))
        regiment = normalize_regiment(row.get("regiment", ""))

        if name:
            participants.append(Participant(name=name, regiment=regiment))

    names = [participant.name for participant in participants]

    if len(participants) < 2:
        raise SecretSantaError("At least 2 valid names are required.")

    if len(set(names)) != len(names):
        raise SecretSantaError("Duplicate names found in the participant list.")

    return participants


def parse_history_from_csv(file_bytes: bytes) -> List[HistoryRecord]:
    text = file_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    required = {"year", "giver", "recipient"}

    if not required.issubset(set(reader.fieldnames or [])):
        raise SecretSantaError(
            "History CSV must contain 'year', 'giver', and 'recipient' columns."
        )

    history: List[HistoryRecord] = []

    for row in reader:
        year = str(row.get("year", "")).strip()
        giver = normalize_name(row.get("giver", ""))
        recipient = normalize_name(row.get("recipient", ""))

        if year and giver and recipient:
            history.append(
                HistoryRecord(
                    year=year,
                    giver=giver,
                    recipient=recipient,
                )
            )

    return history


def build_history_set(history: List[HistoryRecord]) -> Set[Pair]:
    return {(record.giver, record.recipient) for record in history}


def is_valid_assignment(
    giver: str,
    recipient: str,
    assignments: Dict[str, str],
    history_pairs: Set[Pair],
    participant_regiments: Dict[str, str],
) -> bool:
    if giver == recipient:
        return False

    if (giver, recipient) in history_pairs:
        return False

    if recipient in assignments.values():
        return False

    # Prevent A -> B and B -> A
    if assignments.get(recipient) == giver:
        return False

    blocked_regiments = {"southern", "colonial"}

    giver_regiment = participant_regiments.get(giver, "").strip().lower()
    recipient_regiment = participant_regiments.get(recipient, "").strip().lower()

    if (
        giver_regiment in blocked_regiments
        and giver_regiment == recipient_regiment
    ):
        return False

    return True


def generate_assignments(
    participants: List[Participant],
    history: List[HistoryRecord],
    max_attempts: int = 10000,
) -> Dict[str, str]:
    names = [participant.name for participant in participants]

    if len(names) == 2:
        raise SecretSantaError(
            "With only 2 participants, reciprocal gifting is unavoidable."
        )

    participant_regiments = {
        participant.name: participant.regiment
        for participant in participants
    }

    history_pairs = build_history_set(history)

    for _ in range(max_attempts):
        assignments: Dict[str, str] = {}

        givers = names[:]
        random.shuffle(givers)

        for giver in givers:
            candidates = [
                recipient
                for recipient in names
                if is_valid_assignment(
                    giver,
                    recipient,
                    assignments,
                    history_pairs,
                    participant_regiments,
                )
            ]

            random.shuffle(candidates)

            if not candidates:
                break

            assignments[giver] = candidates[0]

        if len(assignments) == len(names):
            return assignments

    raise SecretSantaError(
        "No valid assignment could be found with the current constraints."
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

    writer.writerow(["name", "regiment"])
    writer.writerow(["Alice", "Southern"])
    writer.writerow(["Bob", "Colonial"])
    writer.writerow(["Charlie", "Midwest"])

    return output.getvalue()


def history_template_csv() -> str:
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["year", "giver", "recipient"])
    writer.writerow(["2024", "Alice", "Bob"])
    writer.writerow(["2024", "Bob", "Charlie"])
    writer.writerow(["2025", "Charlie", "Alice"])

    return output.getvalue()


def combine_history(
    history: List[HistoryRecord],
    assignments: Dict[str, str],
    year: str,
) -> List[HistoryRecord]:
    updated = history[:]

    for giver, recipient in sorted(assignments.items()):
        updated.append(
            HistoryRecord(
                year=year,
                giver=giver,
                recipient=recipient,
            )
        )

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
    encoded = encoded.replace("\n", "")

    return base64.b64decode(encoded).decode("utf-8")


def save_github_file(path: str, content_text: str, commit_message: str) -> None:
    owner = st.secrets["github"]["owner"]
    repo = st.secrets["github"]["repo"]
    branch = st.secrets["github"].get("branch", "main")

    current = fetch_github_file(path)
    sha = current["sha"]

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    encoded_content = base64.b64encode(
        content_text.encode("utf-8")
    ).decode("utf-8")

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
    st.set_page_config(
        page_title="405th Secret Santa",
        page_icon="🎁",
        layout="wide",
    )

    st.title("405th Secret Santa Generator")

    st.write(
        "Generate Secret Santa pairings with support for history tracking "
        "and regiment restrictions."
    )

    current_year = str(datetime.now().year)

    year = st.text_input(
        "Year for this round",
        value=current_year,
    )

    st.subheader("Participants")

    names_file = st.file_uploader(
        "Upload names CSV",
        type=["csv"],
        key="names_file",
    )

    names_text = st.text_area(
        "Or paste participants",
        placeholder=(
            "name,regiment\n"
            "Alice,Southern\n"
            "Bob,Colonial\n"
            "Charlie,Midwest\n\n"
            "Or paste one name per line."
        ),
        height=180,
    )

    st.caption(
        "Southern cannot pair with Southern. "
        "Colonial cannot pair with Colonial."
    )

    st.subheader("History")

    history_file = st.file_uploader(
        "Upload history CSV (optional)",
        type=["csv"],
        key="history_file",
    )

    if st.button("Generate pairings", type="primary"):
        try:
            if names_file is not None:
                participants = parse_participants_from_csv(
                    names_file.getvalue()
                )
            else:
                participants = parse_participants_from_text(names_text)

            history: List[HistoryRecord] = []

            if history_file is not None:
                history = parse_history_from_csv(
                    history_file.getvalue()
                )

            assignments = generate_assignments(
                participants,
                history,
            )

            updated_history = combine_history(
                history,
                assignments,
                year,
            )

            st.success(
                f"Generated pairings for {len(participants)} participants."
            )

            st.dataframe(
                [
                    {
                        "giver": giver,
                        "recipient": recipient,
                    }
                    for giver, recipient in sorted(assignments.items())
                ],
                use_container_width=True,
            )

            assignments_csv = assignments_to_csv(assignments, year)

            updated_history_csv = history_to_csv(updated_history)

            st.download_button(
                "Download assignments CSV",
                data=assignments_csv,
                file_name=f"assignments_{year}.csv",
                mime="text/csv",
            )

            st.download_button(
                "Download updated history CSV",
                data=updated_history_csv,
                file_name="history_updated.csv",
                mime="text/csv",
            )

        except SecretSantaError as error:
            st.error(str(error))

        except Exception as error:
            st.error(f"Unexpected error: {error}")


if __name__ == "__main__":
    main()
