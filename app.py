"""
Flask web app for the KU Credit Transfer Evaluation Agent.

Run:  python app.py
Then open:  http://localhost:5000
"""
import io
import json
import os

import anthropic
import pdfplumber
import requests as http_requests
from flask import Flask, jsonify, render_template, request

from data_loader import get_data, is_ccns_institution, is_usde_recognized

app = Flask(__name__)
app.secret_key = "ku-credit-transfer-secret-2024"

MODEL = "claude-opus-4-7"

# ── Phase 1: Transcript Extraction Prompt ─────────────────────────────────────

EXTRACT_SYSTEM = """You are a university transcript analyst. Extract all information from the provided transcript text.

Return ONLY valid JSON — no markdown fences, no explanation outside the JSON:
{
  "school_name": "exact name as it appears on the transcript",
  "accreditation_mentioned": "accreditation body stated on transcript, or null if not mentioned",
  "credit_system": "semester" or "quarter",
  "credit_system_note": "e.g. Transcript uses semester hours" or "Transcript uses quarter hours. All credits converted to semester hours (divided by 1.5).",
  "gpa": number or null,
  "degree_awarded": "exact degree name if a degree was conferred, e.g. Associate of Arts, Bachelor of Science — null if none",
  "degree_type": "AA" or "AS" or "BA" or "BS" or "AAS" or "Other" or null,
  "has_bachelor_degree": true or false,
  "bachelor_degree_info": "degree name and year if found, otherwise null",
  "courses": [
    {
      "code": "exact course code from transcript",
      "name": "exact course name from transcript",
      "credits_original": number,
      "credits_semester": number,
      "grade": "letter grade exactly as shown"
    }
  ],
  "additional_components": [
    {
      "type": "Certificate / Test Score / Program Note / etc",
      "description": "description",
      "value": "value or detail"
    }
  ],
  "summary_notices": ["notice 1", "notice 2"]
}

Rules:
- Extract EVERY course listed, including D/F grades (filtering happens later).
- If QUARTER HOURS: credits_semester = round(credits_original / 1.5, 1). Add a conversion notice.
- If SEMESTER HOURS: credits_semester = credits_original.
- degree_type: classify awarded degree as AA, AS, BA, BS, AAS, or Other.
- has_bachelor_degree = true only if a Bachelor's degree was actually awarded/conferred.
- Include AP, CLEP, DANTES scores and certificates in additional_components.
- summary_notices: include GPA found, credit conversion, missing data, unusual grades.
"""

# ── Phase 2: Course Mapping Prompt ────────────────────────────────────────────

MAPPING_SYSTEM = """You are a Keiser University (KU) transfer credit evaluator.

You are given:
1. PROGRAM_REQUIREMENTS — required KU courses. SOURCE OF TRUTH for all KU course data.
2. TRANSCRIPT_COURSES — student courses with grade C or higher only. SOURCE OF TRUTH for transfer data.
3. GEN_ED_STATUS — pre-determined waiver status (do not re-evaluate this).

=== PRE-EVALUATION: GEN ED SCOPE ===
Act on GEN_ED_STATUS exactly as follows — do NOT re-state or re-explain the waiver rules:
- "Waived (Florida AA CCNS)": SKIP all lower-division general education courses in PROGRAM_REQUIREMENTS. Only match program-required (non-GenEd) courses.
- "Waived (Bachelor Degree)": SKIP ALL general education courses. Only match program-required courses.
- "Not Waived": Evaluate ALL PROGRAM_REQUIREMENTS courses.

=== LEVEL COMPATIBILITY (MANDATORY — check before any match) ===
Determine course level from first digit of course number:
- 1xxx or 2xxx = Lower Division
- 3xxx or 4xxx = Upper Division

Rules:
- Lower Division transcript course (1xxx/2xxx) → can ONLY match Lower Division KU course (1xxx/2xxx). MUST NOT match 3xxx/4xxx.
- Upper Division transcript course (3xxx/4xxx) → can match Upper Division KU course. May match lower ONLY if content is highly equivalent.
- Level mismatch → EXCLUDE from all tables, no exceptions.

=== MATCHING CRITERIA (only after level check passes) ===
Match using: course code similarity + course name/subject similarity + credit hours alignment.
- Strong match: substantially equivalent content, credit hours equal or within 1.
- Potential match: same subject area, less certain — worth advisor review.
- No confident match → EXCLUDE entirely. Never include a row just to fill the table.

=== VALIDATION (run before producing tables) ===
- Every ku_code must exist verbatim in PROGRAM_REQUIREMENTS.
- No ku_code should appear in TRANSCRIPT_COURSES codes.
- Every transfer_code must exist verbatim in TRANSCRIPT_COURSES.

Return ONLY valid JSON, no markdown fences:
{
  "strong_matches": [
    {
      "ku_code": "from PROGRAM_REQUIREMENTS verbatim",
      "ku_name": "from PROGRAM_REQUIREMENTS verbatim",
      "ku_credits": number,
      "transfer_code": "from TRANSCRIPT_COURSES verbatim",
      "transfer_credits": number,
      "transfer_grade": "string",
      "reason": "brief explanation"
    }
  ],
  "potential_matches": [
    {
      "ku_code": "string",
      "ku_name": "string",
      "ku_credits": number,
      "transfer_code": "string",
      "transfer_credits": number,
      "transfer_grade": "string",
      "reason": "brief explanation of uncertainty"
    }
  ]
}
"""


# ── USDE recognition check via local DOE institution list ─────────────────────

def check_usde_recognition(school_name: str) -> dict:
    """
    Check if a school is USDE-recognized using the local DOE institution list.
    Returns: {recognized: bool|None, institution_name, accreditations, note}
    """
    usde_list = get_data().get("usde_list", [])
    if not usde_list:
        return {
            "recognized": None,
            "institution_name": school_name,
            "accreditations": [],
            "note": "USDE institution list unavailable. Manual verification required at https://ope.ed.gov/dapip/"
        }
    if is_usde_recognized(school_name, usde_list):
        return {
            "recognized": True,
            "institution_name": school_name,
            "accreditations": [],
            "note": ""
        }
    return {
        "recognized": False,
        "institution_name": school_name,
        "accreditations": [],
        "note": f"'{school_name}' was not found in the U.S. Department of Education recognized institution list."
    }


def clean_json(raw: str) -> str:
    """Strip markdown code fences from a JSON string."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/degree-types")
def degree_types():
    data = get_data()
    types = {}
    for key, info in data["programs"].items():
        dt = info["degree_type"]
        ds = info["degree_type_short"]
        if dt not in types:
            types[dt] = ds
    order = {"AA": 0, "AS": 1, "BA": 2, "BS": 3}
    result = sorted(
        [{"degree_type": k, "short": v} for k, v in types.items()],
        key=lambda x: order.get(x["short"], 99)
    )
    return jsonify(result)


@app.route("/api/programs")
def programs():
    degree_type = request.args.get("degree_type", "")
    data = get_data()
    result = []
    for key, info in data["programs"].items():
        if info["degree_type"] == degree_type:
            result.append({
                "key": key,
                "program_name": info["program_name"],
                "full_name": info["full_name"],
                "program_code": info["program_code"],
            })
    result.sort(key=lambda x: x["program_name"])
    return jsonify(result)


@app.route("/api/program-requirements")
def program_requirements():
    program_key = request.args.get("key", "")
    data = get_data()
    program = data["programs"].get(program_key)
    if not program:
        return jsonify({"error": "Program not found"}), 404

    categories = []
    for cat_name, cat in program["categories"].items():
        disciplines = []
        for disc_name, disc in cat["disciplines"].items():
            disciplines.append({
                "name": disc_name,
                "total_credits": disc["total_credits"],
                "courses": disc["courses"],
            })
        categories.append({
            "name": cat_name,
            "total_credits": cat["total_credits"],
            "disciplines": disciplines,
        })

    return jsonify({
        "full_name": program["full_name"],
        "program_code": program["program_code"],
        "degree_type": program["degree_type"],
        "categories": categories,
    })


@app.route("/api/extract-pdf", methods=["POST"])
def extract_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400
    try:
        pdf_bytes = f.read()
        page_texts = []

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):

                # Strategy 1: layout-aware text (preserves column spacing)
                text = None
                try:
                    text = page.extract_text(layout=True)
                except TypeError:
                    pass

                # Strategy 2: plain text extraction
                if not text or len(text.strip()) < 20:
                    text = page.extract_text()

                # Strategy 3: word-level reconstruction (handles complex layouts)
                if not text or len(text.strip()) < 20:
                    words = page.extract_words(
                        x_tolerance=5, y_tolerance=5,
                        keep_blank_chars=False, use_text_flow=True
                    )
                    if words:
                        # Group words by approximate y-position (same line = within 5pt)
                        lines_dict = {}
                        for w in words:
                            y = round(w["top"] / 5) * 5
                            lines_dict.setdefault(y, []).append(w)
                        sorted_lines = [lines_dict[y] for y in sorted(lines_dict)]
                        text = "\n".join(
                            "  ".join(w["text"] for w in sorted(ln, key=lambda w: w["x0"]))
                            for ln in sorted_lines
                        )

                if text and text.strip():
                    page_texts.append(f"--- Page {page_num} ---\n{text.strip()}")

        full_text = "\n\n".join(page_texts).strip()

        if not full_text:
            return jsonify({
                "error": "Could not extract text from this PDF. "
                         "Make sure it is a text-based PDF (not a scanned image). "
                         "Try opening the PDF and selecting text — if you cannot select any text, it is a scanned image and cannot be processed."
            }), 422

        return jsonify({"text": full_text, "page_count": len(page_texts)})

    except Exception as e:
        return jsonify({"error": f"PDF extraction failed: {str(e)}"}), 500


@app.route("/api/debug-pdf", methods=["POST"])
def debug_pdf():
    """Returns raw extracted text for debugging — visible in the textarea before evaluation."""
    return extract_pdf()


@app.route("/api/evaluate", methods=["POST"])
def evaluate():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "ANTHROPIC_API_KEY is not set on the server."}), 500

    body = request.get_json() or {}
    program_key    = body.get("program_key", "").strip()
    transcript_text = body.get("transcript_text", "").strip()

    if not program_key or not transcript_text:
        return jsonify({"error": "Missing program_key or transcript_text"}), 400

    data    = get_data()
    program = data["programs"].get(program_key)
    if not program:
        return jsonify({"error": f"Program '{program_key}' not found"}), 404

    # Flatten required courses
    required_courses = []
    for cat_name, cat in program["categories"].items():
        for disc_name, disc in cat["disciplines"].items():
            for course in disc["courses"]:
                required_courses.append({
                    "category": cat_name,
                    "discipline": disc_name,
                    "code": course["code"],
                    "name": course["name"],
                    "credits": course["credits"],
                })

    client = anthropic.Anthropic()

    # ── Phase 1: Extract transcript ────────────────────────────────────────────
    try:
        r1 = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": f"Extract all information from this transcript:\n\n{transcript_text}"}],
        )
        raw1 = "".join(b.text for b in r1.content if hasattr(b, "text"))
        extracted = json.loads(clean_json(raw1))
    except Exception as e:
        return jsonify({"error": f"Phase 1 (extraction) failed: {str(e)}"}), 500

    # ── USDE recognition check ─────────────────────────────────────────────────
    school_name   = extracted.get("school_name", "")
    accred_on_doc = extracted.get("accreditation_mentioned")
    usde          = check_usde_recognition(school_name) if school_name else {
        "recognized": None, "note": "School name not found in transcript.", "accreditations": []
    }

    # If school is definitively NOT USDE-recognized → stop here
    if usde["recognized"] is False:
        return jsonify({
            "blocked": True,
            "blocked_reason": f"This institution is not USDE-recognized, and credits are not transferable.",
            "school_name": school_name,
            "accreditation": usde,
        })

    # ── Determine Gen Ed waiver status ─────────────────────────────────────────
    ccns_list     = data["ccns_list"]
    in_ccns       = is_ccns_institution(school_name, ccns_list)
    degree_type   = extracted.get("degree_type", "")
    gpa           = extracted.get("gpa")
    has_bachelor  = extracted.get("has_bachelor_degree", False)

    if degree_type == "AA" and in_ccns and (gpa is None or gpa >= 2.0):
        gen_ed_status = "Waived (Florida AA CCNS)"
        gen_ed_note   = (
            f"{school_name} is a Florida CCNS institution. "
            "Student holds an AA degree (GPA ≥ 2.0). "
            "All lower-division general education requirements are considered met. "
            "Program-required courses are still evaluated."
        )
    elif has_bachelor and in_ccns:
        gen_ed_status = "Waived (Bachelor Degree)"
        gen_ed_note   = (
            f"Student holds a Bachelor's degree from {school_name}, a CCNS institution. "
            "All general education requirements are considered met. "
            "Program-required courses are still evaluated."
        )
    else:
        gen_ed_status = "Not Waived"
        gen_ed_note   = ""

    # ── Filter eligible courses (grade C or higher) ───────────────────────────
    PASSING = {"A+","A","A-","B+","B","B-","C+","C","S","P","CR","TR","T"}
    eligible = [
        c for c in extracted.get("courses", [])
        if str(c.get("grade", "")).strip().upper() in PASSING
    ]

    # ── Phase 2: Map courses ───────────────────────────────────────────────────
    mapping_prompt = f"""GEN_ED_STATUS: {gen_ed_status}

PROGRAM_REQUIREMENTS (KU — source of truth):
{json.dumps(required_courses, indent=2)}

TRANSCRIPT_COURSES (grade C or higher only — source of truth):
{json.dumps(eligible, indent=2)}

Map transcript courses to program requirements following all rules."""

    try:
        r2 = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=MAPPING_SYSTEM,
            messages=[{"role": "user", "content": mapping_prompt}],
        )
        raw2 = "".join(b.text for b in r2.content if hasattr(b, "text"))
        mapping = json.loads(clean_json(raw2))
    except Exception as e:
        return jsonify({"error": f"Phase 2 (mapping) failed: {str(e)}"}), 500

    # ── Build final response ───────────────────────────────────────────────────
    strong    = mapping.get("strong_matches", [])
    potential = mapping.get("potential_matches", [])

    return jsonify({
        "program_full_name": program["full_name"],
        "program_code":      program["program_code"],
        "school_name":             school_name,
        "accreditation_on_doc":    accred_on_doc,
        "accreditation":           usde,
        "credit_system":           extracted.get("credit_system", "semester"),
        "credit_system_note":      extracted.get("credit_system_note", ""),
        "gpa":                     extracted.get("gpa"),
        "degree_awarded":          extracted.get("degree_awarded"),
        "has_bachelor_degree":     has_bachelor,
        "bachelor_degree_info":    extracted.get("bachelor_degree_info"),
        "courses":                 extracted.get("courses", []),
        "additional_components":   extracted.get("additional_components", []),
        "summary_notices":         extracted.get("summary_notices", []),
        "is_ccns":                 in_ccns,
        "gen_ed_status":           gen_ed_status,
        "gen_ed_note":             gen_ed_note,
        "strong_matches":          strong,
        "potential_matches":       potential,
        "total_transfer_credits":  sum(float(m.get("transfer_credits") or 0) for m in strong),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting KU Credit Transfer Agent on port {port}...")
    if port == 5000:
        print("Open your browser and go to:  http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=port)
