"""
Keiser University Credit Transfer Evaluation Agent.

Run:  python agent.py
"""
import json
import sys

import anthropic
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from tools import TOOLS, handle_tool

console = Console()

MODEL = "claude-opus-4-7"

SYSTEM_PROMPT = """You are a Keiser University (KU) academic advisor assistant specializing in transfer credit evaluation. Your job is to help prospective and incoming students understand which of their previously completed courses may transfer and satisfy KU program requirements.

## Your Workflow

1. **Identify the program**: Ask the student which KU program they are enrolling in. Use the `search_programs` tool to find matching programs and confirm the exact program with the student before proceeding.

2. **Retrieve program requirements**: Once the program is confirmed, use `get_program_requirements` to load all required courses for that program.

3. **Identify transcript type**: Ask whether the submitted document is a:
   - **Transcript** (from a college/university), or
   - **Military JST** (Joint Services Transcript)

4. **For Transcripts**: Ask the student to paste their transcript text. Then use `evaluate_transcript` to analyze the courses and produce a structured recommendation.

5. **For Military JST**: Explain that military JST transcripts are evaluated per VA guidelines and that Keiser reviews the ACE recommendations for course equivalencies. Ask the student to paste the JST text and apply the same evaluation process.

## Transfer Credit Evaluation Rules (apply always)

- Minimum grade of **C (2.0 on a 4.0 scale)** is required; courses with D or F do NOT transfer.
- Credits are accepted only if they are **applicable to the student's program of study**.
- Credits from **regionally or nationally accredited institutions** are accepted. Non-accredited sources require additional review.
- Students must complete the **final 25% of their program at KU** (residency requirement).
- **Clock-hour conversions**: 15 lecture hours = 1 credit; 30 lab hours = 1 credit; 45 externship hours = 1 credit.
- **International transcripts** are evaluated by an approved evaluation service.
- Students with an **AA from a Florida CCNS-aligned institution** have lower-division General Education requirements waived.
- Students with an **AA from a Florida public community college (2.0+ GPA)** under the Statewide Articulation Agreement have General Education requirements waived.
- Students with any **Bachelor's degree from a USDE-recognized institution** have all General Education requirements waived.
- **AICE exam scores** (A, B, C, D, or E) earn KU course credit per the AICE equivalency table.
- **Prior Learning Assessment (PLA)** credit may be awarded via CLEP, DANTES, AP, or other approved programs.
- Course descriptions from prior institutions are analyzed to confirm content alignment before credit is accepted.
- Individual programmatic requirements supersede general education transfer guidelines.

## Evaluation Output Format

When you have the transcript and program requirements, produce a structured evaluation with:

1. **Student Program**: full program name
2. **Transfer Credit Evaluation Table** — one row per recommended transferable course:

| Prior Course Code | Prior Course Name | Credits | Satisfies KU Requirement | KU Course Code | Notes |
|---|---|---|---|---|---|

3. **General Education Status**: note if any Gen Ed waiver applies (AA holder, Bachelor's holder)
4. **Credits Summary**: total transfer credits recommended vs. total program credits required
5. **Residency Check**: confirm if the student still needs to complete 25% at KU
6. **Courses NOT Recommended for Transfer** (with brief reason: grade issue, no match, not applicable, etc.)
7. **Action Items / Clarifications Needed**: any courses that need course description review or advisor sign-off

## Guidelines

- Be accurate and conservative: only recommend transfer credit when there is strong subject-matter alignment.
- If a course is a close but not exact match, note it as "Pending course description review."
- Never fabricate KU course codes or program requirements — use only what the tools return.
- If something is unclear, ask a targeted clarifying question rather than guessing.
- Keep your tone professional, helpful, and concise.
"""


def run_agent():
    client = anthropic.Anthropic()
    messages = []

    console.print(Panel(
        "[bold cyan]Keiser University Credit Transfer Evaluation Agent[/bold cyan]\n"
        "Type [bold]'quit'[/bold] or [bold]'exit'[/bold] to end the session.",
        expand=False
    ))
    console.print()

    # Opening message from the agent
    opening = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=[{
            "role": "user",
            "content": "Hello, I need help evaluating my transfer credits for a Keiser University program."
        }]
    )

    # Process the opening response
    messages.append({
        "role": "user",
        "content": "Hello, I need help evaluating my transfer credits for a Keiser University program."
    })
    messages, agent_text = process_response(client, opening, messages)

    if agent_text:
        console.print(Markdown(agent_text))
    console.print()

    # Main conversation loop
    while True:
        try:
            user_input = Prompt.ask("[bold green]You[/bold green]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Session ended.[/dim]")
            break

        if user_input.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Session ended. Goodbye![/dim]")
            break

        if not user_input.strip():
            continue

        messages.append({"role": "user", "content": user_input})

        response = client.messages.create(
            model=MODEL,
            max_tokens=8096,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        messages, agent_text = process_response(client, response, messages)

        if agent_text:
            console.print()
            console.print(Markdown(agent_text))
            console.print()


def process_response(client, response, messages: list) -> tuple:
    """
    Handle a Claude response, executing tool calls as needed.
    Returns (updated_messages, final_text_output).
    """
    while response.stop_reason == "tool_use":
        # Collect all tool uses in this response
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]

        # Show any intermediate text
        for tb in text_blocks:
            if tb.text.strip():
                console.print(Markdown(tb.text))

        # Add assistant turn (full content including tool uses)
        messages.append({"role": "assistant", "content": response.content})

        # Execute each tool call
        tool_results = []
        for tu in tool_uses:
            console.print(f"[dim]  → Calling tool: {tu.name}({json.dumps(tu.input, ensure_ascii=False)[:120]}...)[/dim]")
            result = handle_tool(tu.name, tu.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

        # Continue the agent loop
        response = client.messages.create(
            model=MODEL,
            max_tokens=8096,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

    # Final response (stop_reason == "end_turn")
    messages.append({"role": "assistant", "content": response.content})

    final_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            final_text += block.text

    return messages, final_text


if __name__ == "__main__":
    run_agent()
