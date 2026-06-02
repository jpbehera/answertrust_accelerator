"""Generate a printable PDF of the opening + speaker notes for slides 1–3."""
import os
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                PageBreak, KeepTogether, HRFlowable)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "AnswerTrust_Speaker_Notes.pdf")

PURPLE = HexColor("#3a2070")
ORANGE = HexColor("#c85a18")
INK    = HexColor("#1a2330")
MUTED  = HexColor("#6a6f82")
RULE   = HexColor("#dfdfea")
QUOTE_BG = HexColor("#f5eeff")

styles = getSampleStyleSheet()

H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                    fontSize=20, leading=24, textColor=PURPLE,
                    spaceAfter=6, spaceBefore=0)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                    fontSize=14, leading=18, textColor=ORANGE,
                    spaceAfter=4, spaceBefore=12)
H3 = ParagraphStyle("H3", parent=styles["Heading3"], fontName="Helvetica-Bold",
                    fontSize=11, leading=14, textColor=PURPLE,
                    spaceAfter=4, spaceBefore=10)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica",
                      fontSize=10.5, leading=14.5, textColor=INK,
                      alignment=TA_LEFT, spaceAfter=6)
QUOTE = ParagraphStyle("Quote", parent=BODY, fontName="Helvetica",
                       fontSize=11, leading=15.5, textColor=INK,
                       leftIndent=14, rightIndent=14,
                       borderColor=PURPLE, borderWidth=0,
                       backColor=QUOTE_BG,
                       borderPadding=(8, 10, 8, 10),
                       spaceBefore=4, spaceAfter=8)
CUE = ParagraphStyle("Cue", parent=BODY, fontName="Helvetica-Bold",
                     fontSize=9.5, leading=12, textColor=ORANGE,
                     spaceBefore=8, spaceAfter=2)
SMALL = ParagraphStyle("Small", parent=BODY, fontName="Helvetica-Oblique",
                       fontSize=9, leading=12, textColor=MUTED,
                       spaceAfter=4)
META = ParagraphStyle("Meta", parent=BODY, fontName="Helvetica",
                      fontSize=9, leading=11, textColor=MUTED,
                      spaceAfter=10)


def hr():
    return HRFlowable(width="100%", thickness=0.6, color=RULE,
                      spaceBefore=10, spaceAfter=10)


story = []

# ---------- Title ----------
story.append(Paragraph("AnswerTrust — Speaker Notes", H1))
story.append(Paragraph("Slides 1 · 2 · 3 &nbsp;&nbsp;|&nbsp;&nbsp; Opening + click-by-click talking points", META))
story.append(hr())

# ---------- Opening ----------
story.append(Paragraph("🎤 Opening — before Slide 1's first click", H2))
story.append(Paragraph(
    '"Every enterprise has agentic AI in pilot.<br/>'
    'But a fraction of them have it in production.<br/>'
    "Not because the models don't work — because <b>no one can prove the answer</b>.<br/>"
    "That's the gap we close today.\"",
    QUOTE))
story.append(Paragraph("<i>[Pause one beat. Advance to Slide 1.]</i>", SMALL))
story.append(hr())

# ---------- Slide 1 ----------
story.append(Paragraph("Slide 1 — The Gap &nbsp;<font color='#6a6f82' size='10'>(3 click stages)</font>", H2))

story.append(Paragraph("[CLICK 1] — Flow strip appears (Pilot → Production → Risk &amp; Audit)", CUE))
story.append(Paragraph(
    '"Here\'s the journey every agentic AI program is on right now.<br/>'
    "You start in <b>pilot</b> — exciting demos, real value.<br/>"
    "You try to push to <b>production</b> — and rollouts pause. Net-new agents freeze.<br/>"
    "Then <b>Risk and Audit</b> show up with one question: <i>prove this answer.</i><br/>"
    "And the room goes quiet.\"",
    QUOTE))
story.append(Paragraph("<i>[Beat. Click.]</i>", SMALL))

story.append(Paragraph("[CLICK 2] — Five questions reveal on the left", CUE))
story.append(Paragraph(
    '"These are the five questions Risk and Audit always ask — in this order:<br/>'
    "Is the answer <b>correct</b>?<br/>"
    "Was the data <b>fit for use</b>?<br/>"
    "Was the user <b>allowed to see those rows</b>?<br/>"
    "What <b>exactly</b> happened — show me the trace?<br/>"
    "When do we <b>intervene</b> — and at what threshold?<br/><br/>"
    "Today, no single Microsoft service answers all five. Purview answers part. "
    "Foundry answers part. Fabric answers part. Defender and Sentinel answer part.<br/>"
    "The answer lives in the seams between them — and that seam is empty.\"",
    QUOTE))
story.append(Paragraph("<i>[Beat. Click.]</i>", SMALL))

story.append(Paragraph("[CLICK 3] — Hub diagram reveals on the right", CUE))
story.append(Paragraph(
    '"Our proposal is to build the <b>connective tissue</b> — the wiring that joins '
    "Purview, Foundry, Fabric, and Security into one answerable artifact.<br/>"
    "One score per answer. One ledger row. One trace.<br/>"
    "We call it <b>AnswerTrust</b> — and it's what turns 'we trust the model' into "
    "'here's the proof.'\"",
    QUOTE))
story.append(Paragraph(
    "<b>Transition →</b> &nbsp;\"So how does that work? Four lanes, four jobs.\"",
    BODY))

story.append(PageBreak())

# ---------- Slide 2 ----------
story.append(Paragraph("Slide 2 — Trust Stack &nbsp;<font color='#6a6f82' size='10'>(2 click stages)</font>", H2))

story.append(Paragraph("[CLICK 1] — Four lanes appear (on slide entry)", CUE))
story.append(Paragraph(
    '"Four lanes — every Microsoft service you already own, organized by the job '
    "it does for trust.<br/><br/>"
    "<b>Observability</b> — App Insights and OTel give us per-hop tracing. Real-Time "
    "Hub and KQL give us the AnswerLedger. Eventstream and the Real-Time Dashboard "
    "give us live ingest and drill-to-trace.<br/><br/>"
    "<b>Governance</b> — Purview labels, DLP, lineage. Entra On-Behalf-Of carries "
    "identity end-to-end. Fabric Workspaces and OneLake enforce domain isolation "
    "through Azure Policy.<br/><br/>"
    "<b>Security</b> — Defender for Cloud watches the agents at runtime. Sentinel "
    "correlates abuse. Foundry's red-team agent stress-tests with PyRIT. IRM and "
    "Key Vault handle insider risk and secrets.<br/><br/>"
    "<b>Quality and Eval</b> — Fabric DQ for validity, completeness, freshness. "
    "Foundry evaluators for groundedness, relevance, safety. Golden-set regression "
    "on every PR.<br/><br/>"
    "<b>Every one of these services already exists.</b> Every one already emits signals. "
    "We're not building a platform — we're building the wiring that makes them "
    "answer one question together.\"",
    QUOTE))
story.append(Paragraph("<i>[Beat. Click.]</i>", SMALL))

story.append(Paragraph("[CLICK 2] — AnswerTrust formula band + 0.83 chip reveal", CUE))
story.append(Paragraph(
    '"And the wiring produces this:<br/><br/>'
    "<b>AnswerTrust = 0.30·Eval + 0.25·DQ + 0.20·LabelCompliance + 0.15·Freshness − 0.10·RedTeamFlags</b>"
    "<br/><br/>"
    "One number, per answer, on a 0-to-1 scale. Weights are tunable per domain — "
    "healthcare may weight DQ higher, finance may weight LabelCompliance higher.<br/><br/>"
    "<b>0.83</b> is the threshold we recommend as a production SLA. Anything below "
    "→ the answer goes to a human. Anything above → it ships, and the ledger row "
    "is the receipt.\"",
    QUOTE))
story.append(Paragraph(
    "<b>Transition →</b> &nbsp;\"That single number does something powerful — it gives "
    "three different audiences the same artifact.\"",
    BODY))

story.append(PageBreak())

# ---------- Slide 3 ----------
story.append(Paragraph("Slide 3 — Business Value &nbsp;<font color='#6a6f82' size='10'>(auto-cascade, no clicks)</font>", H2))

story.append(Paragraph("Cards animate in", CUE))
story.append(Paragraph(
    '"One artifact. Three audiences.<br/><br/>'
    "<b>For the CTO and data leaders</b> — AnswerTrust becomes a publishable SLA. "
    "Per agent. Per domain. <b>Dollars per answer</b> becomes a steerable metric, "
    "not a surprise on the cloud bill. Most importantly — it unblocks the regulated "
    "business units that have been sitting on agentic AI for a year because they "
    "couldn't get sign-off.<br/><br/>"
    "<b>For the data platform team</b> — this is the first end-to-end pattern for "
    "observability across Fabric, multi-agent orchestration, and MCP tools. "
    "Regression on golden questions. DQ joined to answers via a shared <font face='Courier'>run_id</font>. "
    "And it reuses the KQL and Eventstream substrate you already operate — no new "
    "platform to learn.<br/><br/>"
    "<b>For the CISO and compliance</b> — every answer becomes a forensic record. "
    "DLP enforcement, DQ verdict, red-team flags, IRM signal — all on one trace. "
    "This is <i>literally</i> the artifact regulators ask for. DSPM, Sentinel, IRM — "
    "one source of truth instead of three dashboards.\"",
    QUOTE))

story.append(Paragraph("Metrics band", CUE))
story.append(Paragraph(
    '"And here are the SLAs we\'ll commit to on day one:<br/>'
    "100% trace coverage. 100% provenance. 100% DQ coverage. At least 30 golden "
    "questions in the regression set. <b>Under 5 minutes</b> to detect drift. "
    "<b>Under 10 minutes</b> to remediate a wrong answer.<br/>"
    "These aren't aspirational — they're achievable on the existing Microsoft stack "
    "the moment we wire it together.\"",
    QUOTE))

story.append(Paragraph("Tagline", CUE))
story.append(Paragraph(
    '"Governance × Quality × Observability × Evaluation × Security — '
    "<b>one ledger row, one number per answer.</b>\"",
    QUOTE))

story.append(Paragraph(
    "<b>Transition →</b> &nbsp;\"And here's what an operator actually sees when this "
    "is live in production…\"",
    BODY))

story.append(hr())

# ---------- Delivery cues ----------
story.append(Paragraph("🎯 Delivery cues", H2))
story.append(Paragraph(
    "<b>Pace:</b> ~110 wpm. Slides 1–3 should run 4–5 minutes total.", BODY))
story.append(Paragraph(
    "<b>Eye contact on the punchlines:</b> \"the room goes quiet\" · "
    "\"the seam is empty\" · \"0.83\" · \"one ledger row, one number per answer.\"", BODY))
story.append(Paragraph(
    "<b>Hands:</b> Use the click stages as natural pause points — don't keep talking "
    "through the animation.", BODY))


# ---------- Build ----------
def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.6 * inch, 0.4 * inch,
                      "AnswerTrust · Speaker Notes (Slides 1–3)")
    canvas.drawRightString(LETTER[0] - 0.6 * inch, 0.4 * inch,
                           f"Page {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=LETTER,
                        leftMargin=0.65 * inch, rightMargin=0.65 * inch,
                        topMargin=0.6 * inch, bottomMargin=0.7 * inch,
                        title="AnswerTrust Speaker Notes",
                        author="AnswerTrust")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(f"✓ wrote {OUT}")
