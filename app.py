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

from data_loader import get_data

app = Flask(__name__)
app.secret_key = "ku-credit-transfer-secret-2024"

MODEL = "claude-opus-4-7"

# ── Phase 1: Transcript Extraction Prompt ─────────────────────────────────────

EXTRACT_SYSTEM = """You are a university transcript analyst. Extract all information from the provided transcript text.

Return ONLY valid JSON — no markdown fences, no explanation outside the JSON:
{
  "school_name": "exact name as it appears on the transcript",
  "credit_system": "semester" or "quarter",
  "credit_system_note": "e.g. Transcript uses semester hours" or "Transcript uses quarter hours. All credits converted to semester hours by dividing by 1.5.",
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
  "summary_notices": [
    "any important notice, e.g. quarter-to-semester conversion performed, missing grades, GPA, etc."
  ]
}

Rules:
- Extract EVERY course listed, including those with D or F grades (grade filtering happens later).
- If the transcript uses QUARTER HOURS: set credits_semester = round(credits_original / 1.5, 1) for each course. Add a conversion notice.
- If the transcript uses SEMESTER HOURS: credits_semester = credits_original.
- Set has_bachelor_degree = true if the transcript shows a completed Bachelor's degree was awarded.
- Include test scores (AP, CLEP, DANTES), certificates, or program notes in additional_components.
- summary_notices should include: conversion info, any GPA found, missing data, unusual grades, or other relevant alerts.
"""

# ── Phase 2: Course Mapping Prompt ────────────────────────────────────────────

MAPPING_SYSTEM = """You are a Keiser University (KU) transfer credit evaluator.

You are given:
1. PROGRAM_REQUIREMENTS — the list of required KU courses. This is the SOURCE OF TRUTH for all KU course data.
2. TRANSCRIPT_COURSES — courses extracted from the student's transcript. This is the SOURCE OF TRUTH for all transfer course data.

Your task: For each course in PROGRAM_REQUIREMENTS, determine if any TRANSCRIPT_COURSES course can satisfy it.

Match criteria (use all three together):
- Course code similarity (e.g. MAC2311 ↔ MATH 2311 or Calculus I)
- Course name / subject similarity
- Credit hours alignment (within 1 credit is acceptable)

Important rules:
- ONLY courses with a grade of C or higher (C-, B, A, etc.) qualify for transfer. Exclude D, F, W, I.
- ku_code MUST come verbatim from PROGRAM_REQUIREMENTS — never invent or modify.
- transfer_code MUST come verbatim from TRANSCRIPT_COURSES — never invent or modify.
- Strong match: high confidence the course covers the same material.
- Potential match: same subject area but not certain — worth advisor review.
- If a KU course has no reasonable match at all, EXCLUDE it entirely. Do not include rows just to fill the table.
- Verify every row before including it.

Return ONLY valid JSON, no markdown:
{
  "gen_ed_waiver": "none" or "bachelor" or "aa_florida",
  "gen_ed_waiver_note": "explanation or empty string",
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


# ── Accreditation check via DOE DAPIP API ─────────────────────────────────────

def check_accreditation(school_name: str) -> dict:
    """Query the DOE DAPIP API to check if a school is accredited."""
    try:
        url = "https://ope.ed.gov/dapip/api/institutions/search"
        params = {"name": school_name, "includeRecognizedStatus": "true"}
        r = http_requests.get(url, params=params, timeout=6)
        if r.status_code == 200:
            data = r.json()
            institutions = data if isinstance(data, list) else data.get("institutionList", [])
            if institutions:
                inst = institutions[0]
                accred_list = inst.get("accreditationList", [])
                regional_bodies = {
                    "Higher Learning Commission", "SACSCOC", "MSCHE", "NECHE",
                    "NWCCU", "WSCUC", "ACCJC"
                }
                regional = [a for a in accred_list
                            if any(rb.lower() in str(a).lower() for rb in regional_bodies)]
                return {
                    "found": True,
                    "institution_name": inst.get("institutionName", school_name),
                    "is_regionally_accredited": len(regional) > 0,
                    "accreditations": [str(a.get("agencyName", a)) for a in accred_list[:3]],
                    "note": ""
                }
            return {"found": False, "is_regionally_accredited": None,
                    "note": f"'{school_name}' not found in DOE DAPIP database. Manual verification required."}
    except Exception:
        pass
    return {"found": None, "is_regionally_accredited": None,
            "note": "Could not reach DOE DAPIP. Verify accreditation manually at https://ope.ed.gov/dapip/"}


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

    # ── Accreditation check ────────────────────────────────────────────────────
    school_name  = extracted.get("school_name", "")
    accred_result = check_accreditation(school_name) if school_name else {
        "found": None, "note": "School name not found in transcript."
    }

    # ── Phase 2: Map courses ───────────────────────────────────────────────────
    # Only pass courses with grade C or better to the mapping step
    PASSING_GRADES = {"A+","A","A-","B+","B","B-","C+","C","S","P","CR","TR"}
    eligible = [c for c in extracted.get("courses", [])
                if str(c.get("grade","")).upper().strip() in PASSING_GRADES
                or (len(str(c.get("grade",""))) == 1
                    and str(c.get("grade","")).upper() in {"A","B","C","S","P"})]

    mapping_prompt = f"""PROGRAM_REQUIREMENTS (KU):
{json.dumps(required_courses, indent=2)}

TRANSCRIPT_COURSES (student, grades C or higher only):
{json.dumps(eligible, indent=2)}

Has Bachelor's degree: {extracted.get("has_bachelor_degree", False)}
Bachelor's degree info: {extracted.get("bachelor_degree_info", "N/A")}

Map the transcript courses to the program requirements."""

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

    total_transfer_credits = sum(
        float(m.get("transfer_credits") or 0) for m in strong
    )

    return jsonify({
        "program_full_name": program["full_name"],
        "program_code":      program["program_code"],
        # Phase 1 data
        "school_name":          extracted.get("school_name", ""),
        "credit_system":        extracted.get("credit_system", "semester"),
        "credit_system_note":   extracted.get("credit_system_note", ""),
        "has_bachelor_degree":  extracted.get("has_bachelor_degree", False),
        "bachelor_degree_info": extracted.get("bachelor_degree_info"),
        "courses":              extracted.get("courses", []),
        "additional_components": extracted.get("additional_components", []),
        "summary_notices":      extracted.get("summary_notices", []),
        # Accreditation
        "accreditation": accred_result,
        # Phase 2 data
        "gen_ed_waiver":      mapping.get("gen_ed_waiver", "none"),
        "gen_ed_waiver_note": mapping.get("gen_ed_waiver_note", ""),
        "strong_matches":   strong,
        "potential_matches": potential,
        "total_transfer_credits": total_transfer_credits,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting KU Credit Transfer Agent on port {port}...")
    if port == 5000:
        print("Open your browser and go to:  http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=port)
