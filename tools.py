"""
Claude API tool definitions for the KU credit transfer agent.
"""
import json
from data_loader import get_data

# ── tool schemas ───────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_programs",
        "description": (
            "Search Keiser University programs by name or degree type. "
            "Returns a list of matching programs with their keys and full names. "
            "Use this first to help the student identify the exact program they are enrolling in."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term (e.g. 'Accounting', 'Bachelor', 'Nursing', 'AA')"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_program_requirements",
        "description": (
            "Get the full course requirements for a specific KU program. "
            "Returns all categories, disciplines, and required courses with credit hours. "
            "Use this after the student has confirmed their program."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "program_key": {
                    "type": "string",
                    "description": "The program key in format 'ProgramName|DegreeType', e.g. 'Accounting|Associate of Arts'"
                }
            },
            "required": ["program_key"]
        }
    },
    {
        "name": "get_transfer_policy",
        "description": (
            "Get Keiser University's Undergraduate Transfer of Credit Policy. "
            "Returns the key policy rules and AICE exam equivalencies. "
            "Use this when evaluating whether a transferred course meets KU's acceptance criteria."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_special_rules",
        "description": (
            "Look up whether a specific KU program has special transfer rules beyond the general policy. "
            "Returns page references into the Program Transfer Policy document if special rules exist."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "program_name": {
                    "type": "string",
                    "description": "The program name to look up (e.g. 'Nursing', 'Accounting')"
                }
            },
            "required": ["program_name"]
        }
    },
    {
        "name": "evaluate_transcript",
        "description": (
            "Evaluate a student's transcript courses against a specific KU program's requirements. "
            "Pass in the raw transcript text and the program key. "
            "Returns a structured evaluation: which transferred courses satisfy which KU requirements, "
            "credit matches, policy compliance notes, and a summary table."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "transcript_text": {
                    "type": "string",
                    "description": "The full text of the student's transcript, pasted as-is."
                },
                "program_key": {
                    "type": "string",
                    "description": "The KU program key, e.g. 'Accounting|Associate of Arts'"
                }
            },
            "required": ["transcript_text", "program_key"]
        }
    }
]


# ── tool handlers ──────────────────────────────────────────────────────────────

def handle_tool(tool_name: str, tool_input: dict) -> str:
    """Dispatch a tool call and return a JSON string result."""
    data = get_data()

    if tool_name == "search_programs":
        query = tool_input["query"]
        results = []
        programs = data["programs"]
        q = query.lower()
        for key, info in programs.items():
            if (q in info["program_name"].lower()
                    or q in info["full_name"].lower()
                    or q in info["degree_type"].lower()):
                results.append({
                    "key": key,
                    "program_name": info["program_name"],
                    "degree_type": info["degree_type"],
                    "full_name": info["full_name"],
                    "program_code": info["program_code"],
                })
        results.sort(key=lambda x: (x["degree_type"], x["program_name"]))
        if not results:
            return json.dumps({"found": False, "message": f"No programs matched '{query}'.", "programs": []})
        return json.dumps({"found": True, "count": len(results), "programs": results})

    elif tool_name == "get_program_requirements":
        program_key = tool_input["program_key"]
        program = data["programs"].get(program_key)
        if not program:
            return json.dumps({"found": False, "message": f"Program key '{program_key}' not found."})
        # Build a compact summary of all required courses
        summary = {
            "program_name": program["program_name"],
            "degree_type": program["degree_type"],
            "full_name": program["full_name"],
            "program_code": program["program_code"],
            "categories": {}
        }
        for cat_name, cat in program["categories"].items():
            summary["categories"][cat_name] = {
                "total_credits": cat["total_credits"],
                "disciplines": {}
            }
            for disc_name, disc in cat["disciplines"].items():
                summary["categories"][cat_name]["disciplines"][disc_name] = {
                    "total_credits": disc["total_credits"],
                    "courses": disc["courses"]
                }
        return json.dumps({"found": True, "program": summary})

    elif tool_name == "get_transfer_policy":
        policy = data["policy"]
        return json.dumps({
            "rules": policy["rules"],
            "aice_equivalencies": policy["aice_equivalencies"]
        })

    elif tool_name == "get_special_rules":
        program_name = tool_input["program_name"]
        index = data["special_rules_index"]
        q = program_name.lower()
        matches = [e for e in index if e["program_name"].lower() == q]
        if not matches:
            # Try partial match
            matches = [e for e in index if q in e["program_name"].lower()]
        if matches:
            return json.dumps({"found": True, "entries": matches})
        return json.dumps({"found": False, "message": f"No special rules found for '{program_name}'."})

    elif tool_name == "evaluate_transcript":
        # This tool collects inputs for Claude to reason over;
        # the actual evaluation logic lives in the system prompt + Claude's reasoning.
        # We return the program requirements + policy so Claude can do the matching.
        transcript_text = tool_input["transcript_text"]
        program_key = tool_input["program_key"]

        program = data["programs"].get(program_key)
        if not program:
            return json.dumps({"error": f"Program key '{program_key}' not found."})

        policy = data["policy"]

        # Flatten all required courses for the program
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

        return json.dumps({
            "transcript_text": transcript_text,
            "program": {
                "full_name": program["full_name"],
                "program_code": program["program_code"],
            },
            "required_courses": required_courses,
            "policy_rules": policy["rules"],
            "aice_equivalencies": policy["aice_equivalencies"],
        })

    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
