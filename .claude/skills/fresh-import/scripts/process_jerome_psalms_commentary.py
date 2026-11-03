#!/usr/bin/env python3
"""Import Jerome's Homilies on the Psalms (Tractatus sive Homiliae in Psalmos, ed. Morin,
Anecdota Maredsolana III, 1897 and 1903; our public-domain English translation) into the
Commentaries-Database, one homily at a time, by driving a headless ``claude`` agent.

A per-work copy of process_augustine_commentary.py (see ../SKILL.md, "A homily series, one
file per sermon"): the same two-prompt flow, logs, --check and --order. Each of the 73
homilies is its own file in the Writings-Database, with its own url, so each is its own WORKS
entry ("PsHom001" .. "PsHom073"): Homilies 1-59 are Morin's first series, 60-73 his
"alternate series" of fourteen, which preaches again on psalms of the first (82, 83, 84, 89,
90, 91, 93, 95, 96):

    Writings-Database/Jerome/Homilies on Psalms/homily_041.html

    <article class="writing">
    <h1>Homily 41, on Psalm 119</h1>
    <i>Latin source: ... Psalm numbering follows the Septuagint/Vulgate (Morin).</i>
    <br/><br/>
    Let us come to the psalm that was read ...<br/><br/>      (paragraphs, no lemmas or notes)

A homily works through its psalm, quoting each verse (in plain text, as Jerome's Latin psalter
has it) as it reaches it. ``load_work`` gives ONE section per homily (WORKS "homily": True),
headed by the KJV range of its psalm (Psalm 119 in the Latin numbering is KJV 120: "120:1-7";
Latin 9 is KJV 9-10: "9:1-10:18"; Latin 114/115 are KJV 116:1-9/10-19; Latin 146/147 are KJV
147:1-11/12-20), and one piece per homily (6-42k chars; a homily is never cut). The preamble
(title and translator's note) is repeated at the top of the piece as background.

    python3 process_jerome_psalms_commentary.py PsHom001 --dry-run
    python3 process_jerome_psalms_commentary.py PsHom001
    python3 process_jerome_psalms_commentary.py PsHom002-PsHom030   # a chunk: one after another
    python3 process_jerome_psalms_commentary.py PsHom001-PsHom073 --check
    python3 process_jerome_psalms_commentary.py PsHom001 --order          # all files: homily order
    python3 process_jerome_psalms_commentary.py PsHom001 --fix-order BASE # ... and fix it
"""

import argparse
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from urllib.parse import quote

# --- Paths --------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# These scripts live in <Commentaries-Database>/.claude/skills/fresh-import/scripts.
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
# The claude agent runs here so the Commentaries-Database CLAUDE.md conventions apply
# and its relative `<Father>/<Book Verse>.toml` writes land in the right tree.
PROJECT_DIR = os.path.abspath(os.path.join(SKILL_DIR, "..", "..", ".."))
BOOK_NAMES_PATH = os.path.join(PROJECT_DIR, "book_names.json")
# The Writings-Database checkout: $WRITINGS_DB, else a sibling of the Commentaries-Database.
WRITINGS_DIR = os.environ.get("WRITINGS_DB") or os.path.join(
    os.path.dirname(PROJECT_DIR), "Writings-Database")
# Units and run logs go here (gitignored), not next to the scripts.
WORK_DIR = os.path.join(SKILL_DIR, "work")
# KJV lookup for the agent, run from PROJECT_DIR.
KJV_LOOKUP = 'python3 .claude/skills/fresh-import/scripts/kjv_lookup.py "<Book> <C>:<V>"'
KJV_DB = os.path.join(SCRIPT_DIR, "kjv.sqlite")

FATHER = "Jerome"

# Not used to cut anything (a homily is one piece, whatever its size); kept for the audit.
SPLIT_CHARS = 60000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

HOMILIES = "Jerome/Homilies on Psalms"
H1_RE = re.compile(r"<h1>(Homily (\d+), on Psalm (\d+)(?: \(Alternate Series\))?)</h1>")


def _last_verse(chapter):
    db = sqlite3.connect(KJV_DB)
    (n,) = db.execute("select max(txt_location) from bible_kjv where book='psalms' and "
                      "txt_location between ? and ?", (chapter * 1000000,
                                                       chapter * 1000000 + 999)).fetchone()
    return n % 1000000


def kjv_heading(latin):
    """The KJV range of a psalm in the Septuagint/Vulgate numbering: 'C:1-V' (or a part)."""
    split = {9: "9:1-10:18", 114: "116:1-9", 115: "116:10-19", 146: "147:1-11",
             147: "147:12-20"}
    if latin in split:
        return split[latin]
    c = latin + 1 if 10 <= latin <= 112 or 116 <= latin <= 145 else latin
    assert latin <= 8 or latin >= 148 or c == latin + 1, latin
    return f"{c}:1-{_last_verse(c)}"


# Notes for every homily (in the prompt), then each homily's own.
COMMON_NOTES = (
    "PSALM NUMBERING. Jerome (and the title of this piece) numbers the Psalms as the "
    "Septuagint and Latin Bible do, which for most psalms is one BELOW the KJV: this homily's "
    "\"Psalm {latin}\" is KJV {kjv_name}. Within a psalm his verses can also be counted "
    "differently (the Latin counts a psalm's title as a verse), so always place a stretch by "
    "the WORDING of the verse he quotes, matched against the KJV, never by a number. His "
    "psalter is translated from the Greek, so its wording often differs from the KJV's (\"the "
    "horn of the unicorn\", \"the seat of pestilence\"): find the KJV verse that corresponds. "
    "THE TITLE. Jerome often spends a long stretch on the psalm's title (\"Unto the end, a "
    "psalm of David\", which the KJV prints above verse 1 without a number, or sometimes lacks "
    "altogether). Commentary on the title goes under verse 1 of the KJV psalm (\"Psalms 84_1\"), "
    "as a block of its own or together with the verse-1 commentary that follows it. A homily's "
    "opening (a word to the hearers, a remark about the psalm just sung or read) stays at the "
    "start of the first block; its close (an exhortation, the doxology \"To whom be glory unto "
    "the ages of ages. Amen.\", a word about the Gospel reading to come) stays at the end of the "
    "last block.")
HOMILY_NOTES = {
    1: ("This is the first homily: its opening on the Psalter as a great house with many keys "
        "(\"The Psalter is like a great house, which has one outer key on the door\") introduces "
        "the whole series and the first psalm; it stays at the start of the first block, which "
        "goes in \"Psalms 1_1\" (append it after the blocks already there: Jerome's prefaces "
        "to the Psalter stay first)."),
    4: ("Psalm 9 in the Latin numbering is KJV Psalms 9 AND 10 together: Jerome speaks mainly "
        "about the title (KJV 9:1), then quotes \"In this snare which they stretched out, their "
        "own foot has been caught\" (KJV 9:15), \"All the nations that forget God\" (KJV 9:17), "
        "and \"He sits in ambush with the rich\" (KJV 10:8), and the poor man caught in the "
        "snare (KJV 10:9-10). File each stretch under the KJV verse it expounds, in Psalm 9 or "
        "Psalm 10."),
    39: "Psalm 114 in the Latin numbering is KJV Psalm 116:1-9.",
    40: "Psalm 115 in the Latin numbering is KJV Psalm 116:10-19 (\"I believed, therefore have "
        "I spoken\" is KJV 116:10).",
    41: ("The homily opens on the psalm read before this one (\"The hundred and eighteenth psalm, "
         "as we have often said, is a lettered one\", KJV Psalm 119) and on the fifteen psalms "
         "of steps: that introduction stays at the start of the first block, in \"Psalms "
         "120_1\"."),
    56: "Psalm 146 in the Latin numbering is KJV Psalm 147:1-11.",
    57: "Psalm 147 in the Latin numbering is KJV Psalm 147:12-20 (\"Praise the Lord, O "
        "Jerusalem\" is KJV 147:12).",
    60: ("This homily is a single paragraph (about 19,000 characters): cut it between "
         "sentences. Its opening refers back to \"above\" (\"has been discussed more fully "
         "above\"); it stays at the start of the first block."),
}
def _work(f):
    path = os.path.join(WRITINGS_DIR, HOMILIES, f)
    with open(path, encoding="utf-8") as fh:
        m = H1_RE.search(fh.read())
    title, n, latin = m.group(1), int(m.group(2)), int(m.group(3))
    return f"PsHom{n:03d}", {
        "html": f"{HOMILIES}/{f}",
        "book": "Psalms",
        "homily": True,
        "number": n,
        "latin_psalm": latin,
        # The <h1>, as the url'd blocks of the old import already had it.
        "source_title": title,
        "passage": kjv_heading(latin),
        "notes": HOMILY_NOTES.get(n, ""),
    }


WORKS = dict(_work(f) for f in sorted(os.listdir(os.path.join(WRITINGS_DIR, HOMILIES)))
             if re.fullmatch(r"homily_\d{3}\.html", f))


def kjv_name(work):
    """'Psalm 120', 'Psalms 9-10', 'Psalm 116:1-9' (for the prompt)."""
    h = work["passage"]
    (c1, v1), (c2, v2) = [tuple(map(int, p.split(":"))) for p in
                          (h.split("-")[0], h.split("-", 1)[1] if ":" in h.split("-", 1)[1]
                           else f"{h.split(':')[0]}:{h.split('-')[1]}")]
    if c1 != c2:
        return f"Psalms {c1}-{c2}"
    return f"Psalm {c1}" if v1 == 1 and v2 == _last_verse(c1) else f"Psalm {c1}:{v1}-{v2}"


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file. Every segment is
    double-encoded (spaces as %2520), with %2F between segments, matching the existing urls
    ("file=Jerome%2FHomilies%2520on%2520Psalms%2Fhomily_030.html")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"jerome_{work_key.lower()}_units")


# --- Parsing ------------------------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")
# The title and the translator's note (with its own nested italics), then the paragraph break.
PREAMBLE_RE = re.compile(r"(?s)^.*?</h1>\n<i>Latin source:.*?</a>[^<]*</i>\n<br/><br/>\n")


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def load_work(work):
    """Return (preamble_html, sections): ONE section per homily. Its heading is the KJV range
    of the psalm ("120:1-7"); its html (what the agent sees) and body (the text imported and
    checked) are the homily's text; `chapter` is the KJV psalm."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = PREAMBLE_RE.match(text)
    if not m:
        raise SystemExit(f"{work['html']}: can't find the title and translator's note")
    preamble, rest = m.group(), text[m.end():].replace("</article>", "").rstrip() + "\n"
    section = {
        "heading": work["passage"],
        "chapter": int(work["passage"].split(":")[0]),
        "html": rest,
        "body": rest,
    }
    return preamble, [section]


def paragraphs_of(section):
    """Plain-text paragraphs of a section (for the check)."""
    out = []
    for p in re.split(r"(?:<br\s*/?>\s*){2,}", section["body"]):
        p = _clean(p)
        if p:
            out.append(p)
    return out


def make_units(preamble, sections, cap):
    """One piece per homily, named by its number ("Hom041.html")."""
    n = int(re.search(r"<h1>Homily (\d+)", preamble).group(1))
    return [{"name": f"Hom{n:03d}.html", "chapter": sections[0]["chapter"],
             "sections": sections}]


def unit_html(preamble, unit):
    tail = "</article>\n" if "<article" in preamble else ""
    return preamble + "".join(s["html"] for s in unit["sections"]) + tail


def write_units(work_key, preamble, units):
    d = units_dir_for(work_key)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    for u in units:
        with open(os.path.join(d, u["name"]), "w", encoding="utf-8") as f:
            f.write(unit_html(preamble, u))
    return d


# --- Prompts ------------------------------------------------------------------

PROMPT1_TEMPLATE = (
    "We have Jerome's Homilies on the Psalms here: 73 sermons, each a file of its own (Homilies "
    "1-59 are one series, 60-73 a second series, which preaches again on some of the same "
    "psalms). This piece is Homily {number}, \"{units_dir}/{unit_name}\", cut from our "
    "PUBLIC-DOMAIN English translation, \"{html_path}\" (consult it if you need surrounding "
    "context; the other homilies are in the same folder). The homilies are sermons on the book "
    "of {book} -- file everything under the book \"{book}\", in the \"{father}/\" folder.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its psalm, in KJV numbering: {heading})\n\n"
    "Read the WHOLE file and import its commentary IN FULL into our commentaries db. The piece "
    "repeats the homily's title and the translator's note at the top -- that is background for "
    "you, not commentary; don't import it.\n\n"
    "VERSE KEYS. There are no verse labels: Jerome works through his psalm, quoting each verse "
    "(or part of a verse) as he reaches it, in plain text or in quotation marks, and expounding "
    "it, often with digressions (on other Scripture, on the monks, the heretics, the Jews) that "
    "arise from the verse in hand. For each stretch of commentary, work out which KJV verse(s) "
    "of {book} it actually expounds -- compare the Scripture Jerome quotes and discusses with "
    "the KJV text, looking it up with `" + KJV_LOOKUP + "` -- and file it there, under KJV "
    "chapter/verse numbering. A digression goes with the verse it arises from.{notes}\n\n"
    "Wherever possible, we want to use smaller verse ranges / individual verses. Do NOT simply "
    "file the homily under its whole psalm: break it up wherever the exposition moves from one "
    "verse to the next, e.g. if a stretch comments on 91:5, insert it in \"Psalms 91_5\", not "
    "in \"Psalms 91_1-16\". It's ok to use a range if necessary to avoid breaking up a coherent "
    "thought/piece (Jerome sometimes expounds several verses as one argument, or reads a verse "
    "twice, first literally and then spiritually), just prefer smaller ranges/individual verses "
    "-- but don't chop the sermon into tiny fragments either. When you split the homily, its "
    "blocks together must still contain the WHOLE of it, every word -- and you split ONLY by "
    "cutting the text into consecutive stretches: each block must be one continuous stretch of "
    "Jerome, in his order, from a sentence boundary to a sentence boundary. Do NOT duplicate "
    "the same stretch of commentary across several {book} verses -- put it ONCE, at its "
    "smallest accurate verse/range.\n\n"
    "CROSS-BOOK PARALLELS ARE WELCOME (and distinct from the within-{book} duplication "
    "forbidden above). Jerome constantly quotes and expounds other Scripture. Whenever a "
    "stretch genuinely QUOTES AND EXPOUNDS a specific verse from another book -- an OT verse, "
    "a Gospel passage, an Epistle passage, or another Psalm -- you may ALSO file that portion "
    "under that verse in its own file (e.g. \"Genesis 3_17\", \"Matthew 5_3\", \"Psalms 119_1\"), "
    "in addition to its placement under this homily's psalm. File a cross-parallel only where "
    "Jerome genuinely expounds the passage, not for a passing mention or a bare one-line "
    "proof-text. Use KJV book/verse numbering for the target file. When Jerome names another "
    "psalm by number (\"in the eighth psalm\"), that number is the Latin one: check the KJV "
    "psalm and verse by the wording.\n\n"
    "THE TEXT. Copy Jerome's words VERBATIM -- nothing abridged, paraphrased, corrected, added "
    "or rearranged. Drop the html tags (italics simply become plain text; don't turn them into "
    "quotation marks) and separate paragraphs with a single blank line. Keep the translation's "
    "punctuation as printed: its single and double quotation marks (which don't always pair "
    "up), the em dashes (\"—\"), the ellipses, the translator's words in square brackets "
    "(\"[and]\"), and the Latin, Greek and Hebrew words as printed (\"Misericordiam et iudicium "
    "cantabo tibi Domine\", \"ἐπινίκιον\", \"ALAMOTH\", transliterations with macrons). Leave "
    "out the title and the translator's note. Don't add headings, verse numbers or notes of "
    "your own. Don't write a python script to do this; process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY commentary you import from this homily, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}\"\n"
    "(the same url and title for all of them -- this homily is one page).\n\n"
    "EXISTING BLOCKS. The old import of these homilies has ALREADY been deleted, so you are "
    "only ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it. Many {book} files hold blocks from Jerome's other works (excerpts "
    "titled \"BRIEF COMMENTARY ON PSALM ...\", his letters, his prefaces to the Psalter, his "
    "commentaries on the prophets and on Matthew): they stay first, untouched -- don't remove, "
    "merge or \"deduplicate\" them. Earlier runs of THIS import have already filed other "
    "homilies, so you will also find blocks titled \"Homily N, on Psalm ...\" for other "
    "homilies (another url) in the files you write to -- in particular, the second series "
    "(Homilies 60-73) preaches again on psalms the first series covers, so a file may already "
    "hold the other series' homily on the same verse: those are NOT old imports or duplicates "
    "either; leave them exactly as they are and append yours after them."
)

PROMPT2 = "Double check, was this fully imported properly?"


def build_prompt1(work, units_dir, units, unit):
    common = COMMON_NOTES.format(latin=work["latin_psalm"], kjv_name=kjv_name(work))
    own = work.get("notes", "")
    # The second series preaches again on psalms of the first: say so in its notes.
    pair = next((w["number"] for w in WORKS.values() if w["number"] < 60
                 and w["latin_psalm"] == work["latin_psalm"]), None) if work["number"] >= 60 else None
    if pair:
        own = (own + " " if own else "") + (
            f"Homily {pair} of the first series preaches on the same psalm, and its blocks "
            "are already in these verse files: leave them first, and append yours after them.")
    notes = " ".join(x for x in (common, own) if x)
    return PROMPT1_TEMPLATE.format(
        number=work["number"],
        units_dir=units_dir,
        unit_name=unit["name"],
        html_path=os.path.join(WRITINGS_DIR, work["html"]),
        book=work["book"],
        father=FATHER,
        heading=", ".join(s["heading"] for s in unit["sections"]),
        notes=f" {notes}" if notes else "",
        source_url=source_url_for(work),
        source_title=work["source_title"],
    )


# --- Deterministic post-import check ------------------------------------------

PROBE_WORDS = 8


def _norm(s):
    s = s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'}))
    return re.sub(r"\s+", " ", s).strip()


def run_check(work, sections, quiet=False):
    """Return a list of problems (empty == all good). Prints a summary."""
    folder = os.path.join(PROJECT_DIR, FATHER)
    url = source_url_for(work)
    book = work["book"]
    with open(BOOK_NAMES_PATH, encoding="utf-8") as f:
        books = json.load(f)["canonical_names"]
    filename_re = re.compile(
        "(" + "|".join(map(re.escape, books)) + r") \d+_\d+(?:-\d+(?:_\d+)?)?\.toml"
    )
    problems, quotes, files_used, cross, contiguity = [], [], 0, [], []
    source = _norm(" ".join(" ".join(paragraphs_of(s)) for s in sections))

    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml"):
            continue
        path = os.path.join(folder, fn)
        with open(path, encoding="utf-8") as f:
            if url not in f.read():
                continue
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            problems.append(f"{fn}: TOML parse error: {exc}")
            continue
        mine = [c for c in data.get("commentary", []) if c.get("source_url") == url]
        if not mine:
            continue
        if not filename_re.fullmatch(fn):
            problems.append(f"{fn}: filename is not '<Book> C_V' / 'C_V-V' / 'C_V-C_V'")
        own_book = fn.startswith(book + " ")
        if own_book:
            files_used += 1
        else:
            cross.append(fn[:-5])
        for c in mine:
            q = c.get("quote", "")
            contiguity.append((fn, q))
            if own_book:
                quotes.append(q)
            if c.get("source_title") != work["source_title"]:
                problems.append(f"{fn}: wrong source_title {c.get('source_title')!r}")
            if re.search(r"</?[a-z]+>|\[note:", q):
                problems.append(f"{fn}: leftover html tag or [note: ...] in a block")

    for fn, q in contiguity:
        if _norm(q) not in source:
            problems.append(
                f"{fn}: block is not one continuous stretch of the source (text cut up, "
                f"rearranged or altered): {_norm(q)[:80]!r}"
            )

    haystack = _norm(" ".join(quotes))
    probed = 0
    for s in sections:
        for i, p in enumerate(paragraphs_of(s), 1):
            words = _norm(p).split(" ")
            for label, probe in (("start", words[:PROBE_WORDS]), ("end", words[-PROBE_WORDS:])):
                probed += 1
                if " ".join(probe) not in haystack:
                    problems.append(
                        f"paragraph {i} {label} not found: {' '.join(probe)!r}"
                    )

    tag = f"Homily {work['number']}"
    if problems or not quiet:
        print(f"\nCHECK {tag}: {len(quotes)} block(s) in {files_used} {book} file(s); "
              f"{probed} paragraph probes; cross-book ({len(cross)}): {', '.join(cross) or 'none'}")
    if problems:
        print(f"CHECK FAILED -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
    elif not quiet:
        print("CHECK PASSED")
    return problems


# --- Live rendering of stream-json events -------------------------------------


def _truncate(text, limit=500):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + " …"


def render_event(event):
    """Print a human-readable line for one stream-json event, live."""
    etype = event.get("type")

    if etype == "system" and event.get("subtype") == "init":
        model = event.get("model", "?")
        print(f"    · session start (model={model})")

    elif etype == "assistant":
        for block in event.get("message", {}).get("content", []):
            btype = block.get("type")
            if btype == "text" and block.get("text", "").strip():
                print(f"    💬 {_truncate(block['text'])}")
            elif btype == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {})
                hint = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                hint = f" {_truncate(str(hint), 160)}" if hint else ""
                print(f"    🔧 {name}{hint}")

    elif etype == "user":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                flag = " [error]" if block.get("is_error") else ""
                print(f"    ↳ result{flag}: {_truncate(str(content), 200)}")

    elif etype == "result":
        if event.get("subtype") != "success":
            print(f"    ⚠ result subtype={event.get('subtype')}")


# --- One claude call ----------------------------------------------------------


def is_rate_limit_error(stderr):
    lower = stderr.lower()
    return any(
        term in lower
        for term in ["rate limit", "rate_limit", "overloaded", "too many requests", "529"]
    )


def call_claude(prompt, events_log, tag, resume_session=None):
    """Run one headless claude invocation, streaming stream-json events.

    Returns (final_text, session_id). Every raw event line is persisted to
    events_log tagged with `tag` (e.g. "Part003_Ch02a/prompt1"). When resume_session
    is given, the call continues that conversation via --resume."""
    delays = RETRY_DELAYS
    for attempt in range(len(delays) + 1):
        cmd = ["claude", "-p", "--dangerously-skip-permissions"]
        if resume_session:
            cmd += ["--resume", resume_session]
        cmd += ["--output-format", "stream-json", "--verbose", prompt]

        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        final_text = ""
        session_id = resume_session
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events_log.write(
                json.dumps({"tag": tag, "attempt": attempt + 1, "event": event}) + "\n"
            )
            events_log.flush()
            if event.get("session_id"):
                session_id = event["session_id"]
            render_event(event)
            if event.get("type") == "result" and "result" in event:
                final_text = event["result"]

        proc.wait()
        stderr = proc.stderr.read()

        if proc.returncode == 0:
            return final_text.strip(), session_id

        if is_rate_limit_error(stderr):
            delays = RATE_LIMIT_DELAYS

        if attempt < len(delays):
            wait = delays[attempt]
            print(
                f"    Retry {attempt + 1}/{len(delays)} after {wait}s... "
                f"(rc={proc.returncode} stderr={stderr.strip()[:80]})"
            )
            time.sleep(wait)
        else:
            msg = (
                f"rc={proc.returncode} stderr={stderr.strip()[:200]} "
                f"final={final_text.strip()[:200]}"
            )
            raise RuntimeError(f"claude call failed after retries: {msg}")

    raise RuntimeError("Unreachable")


# --- Driver -------------------------------------------------------------------


def log_record(log, unit, prompt_no, started, ended, session_id, output):
    log.write(
        json.dumps(
            {
                "unit": unit["name"],
                "sections": [s["heading"] for s in unit["sections"]],
                "prompt": prompt_no,
                "timestamp": started.isoformat(),
                "duration_seconds": round((ended - started).total_seconds(), 1),
                "session_id": session_id,
                "output": output,
            }
        )
        + "\n"
    )
    log.flush()


def process_unit(work, units_dir, units, unit, log, events_log):
    """Run prompt 1 (import) then prompt 2 (self-review) in one conversation."""
    print(f"\n{'=' * 60}")
    print(f"{unit['name']}: {', '.join(s['heading'] for s in unit['sections'])}")
    print(f"{'=' * 60}")
    tag = unit["name"].removesuffix(".html")

    print("  [prompt 1] importing...")
    started = datetime.now()
    out1, session_id = call_claude(
        build_prompt1(work, units_dir, units, unit), events_log, tag=f"{tag}/prompt1"
    )
    ended = datetime.now()
    log_record(log, unit, 1, started, ended, session_id, out1)
    print(f"  [prompt 1] done ({round((ended - started).total_seconds(), 1)}s)"
          f" -- session {session_id}")
    print(f"  {_truncate(out1, 300)}")

    if not session_id:
        print("  WARNING: no session_id captured from prompt 1; prompt 2 would "
              "start a fresh conversation. Skipping prompt 2 for this piece.")
        return

    print("  [prompt 2] double-checking...")
    started = datetime.now()
    out2, _ = call_claude(
        PROMPT2, events_log, tag=f"{tag}/prompt2", resume_session=session_id
    )
    ended = datetime.now()
    log_record(log, unit, 2, started, ended, session_id, out2)
    print(f"  [prompt 2] done ({round((ended - started).total_seconds(), 1)}s)")
    print(f"  {_truncate(out2, 300)}")



def check_order(base=None):
    """Cross-homily order: in each file, the Homilies' blocks (all appended after the files'
    BASE content) must follow homily number, then source position. Pieces run out of sequence
    (the pilot) break it. With `base`, reorder only those appended blocks, by cutting the file
    text, and assert the BASE content stays a byte-identical prefix. Returns the files out of
    order (before any fix)."""
    folder = os.path.join(PROJECT_DIR, FATHER)
    block_re = re.compile(r"(?m)^\[\[commentary\]\][ \t]*$")
    url_no = {source_url_for(w): w["number"] for w in WORKS.values()}
    sources = {}

    def pos(n, quote):
        if n not in sources:
            secs = load_work(WORKS[f"PsHom{n:03d}"])[1]
            sources[n] = _norm(" ".join(" ".join(paragraphs_of(s)) for s in secs))
        return sources[n].find(_norm(quote))

    bad = []
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml") or fn == "metadata.toml":
            continue
        path = os.path.join(folder, fn)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if "Homilies%2520on%2520Psalms" not in text:
            continue
        starts = [m.start() for m in block_re.finditer(text)]
        blocks = [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]
        parsed = tomllib.loads(text)["commentary"]
        assert len(parsed) == len(blocks), fn
        keys = [(url_no[c["source_url"]], pos(url_no[c["source_url"]], c["quote"]))
                if c.get("source_url") in url_no else None for c in parsed]
        mine = [i for i, k in enumerate(keys) if k]
        if not mine:
            continue
        if mine != list(range(mine[0], len(blocks))):
            print(f"  NOT APPENDED AT THE END: {fn}")
            bad.append(fn)
            continue
        order = sorted(mine, key=lambda i: keys[i])
        if order == mine:
            continue
        print(f"  OUT OF HOMILY ORDER: {fn[:-5]} {[keys[i][0] for i in mine]}")
        bad.append(fn)
        if base:
            new = text[:starts[mine[0]]] + "".join(
                blocks[i].rstrip("\n") + "\n\n" for i in order)
            new = new.rstrip("\n") + "\n"
            old = subprocess.run(["git", "-C", PROJECT_DIR, "show",
                                  f"{base}:{FATHER}/{fn}"], capture_output=True, text=True).stdout
            assert new.startswith(old.rstrip("\n")), fn
            assert tomllib.loads(new)["commentary"] == (
                parsed[:mine[0]] + [parsed[i] for i in order]), fn
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            print("    reordered")
    print(f"{len(bad)} file(s) out of homily order" + (" (fixed)" if base and bad else ""))
    return bad


def expand_works(specs):
    """Work keys from the arguments: keys ("PsHom005") and ranges ("PsHom005-PsHom030")."""
    keys = sorted(WORKS)
    out = []
    for spec in specs:
        a, _, b = spec.partition("-")
        if a not in WORKS or (b and b not in WORKS):
            raise SystemExit(f"unknown work {spec!r} (keys run PsHom001 .. PsHom073)")
        out += keys[keys.index(a):keys.index(b) + 1] if b else [a]
    return out


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "works", nargs="+",
        help="Homilies to import, run one after another: keys (PsHom005) and/or ranges "
             "(PsHom005-PsHom030).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true",
        help="Print the pieces and the first prompt; write and call nothing.",
    )
    mode.add_argument(
        "--split-only", action="store_true",
        help="Write the pieces to the units folders and keep them (for inspection).",
    )
    mode.add_argument("--check", action="store_true",
                      help="Run only the check (printing only failures when several works).")
    mode.add_argument("--order", action="store_true",
                      help="Check that every file holds the Homilies' blocks in homily order "
                           "(any works argument; all files are checked).")
    mode.add_argument("--fix-order", metavar="BASE",
                      help="As --order, and reorder the out-of-order files' appended blocks, "
                           "keeping their content at BASE (the deletion commit) unchanged.")
    args = parser.parse_args()
    if args.order or args.fix_order:
        sys.exit(1 if check_order(args.fix_order) and not args.fix_order else 0)
    keys = expand_works(args.works)

    with open(BOOK_NAMES_PATH, encoding="utf-8") as f:
        assert "Psalms" in json.load(f)["canonical_names"]

    loaded = {}
    for k in keys:
        pre, secs = load_work(WORKS[k])
        loaded[k] = (pre, secs, make_units(pre, secs, SPLIT_CHARS))

    if args.check:
        bad = [k for k in keys if run_check(WORKS[k], loaded[k][1], quiet=len(keys) > 1)]
        print(f"\n{len(keys) - len(bad)} of {len(keys)} homily(ies) pass the check"
              + (f"; failing: {', '.join(bad)}" if bad else ""))
        sys.exit(1 if bad else 0)

    print(f"Work:       {FATHER}, Homilies on the Psalms ({len(keys)} homily(ies))")
    print(f"Agent cwd:  {PROJECT_DIR}")
    for k in keys:
        pre, secs, units = loaded[k]
        size = sum(len(s["html"]) for s in secs)
        print(f"  {k}  {units[0]['name']}  {size:>6} chars  [{secs[0]['heading']}]")

    if args.dry_run:
        k = keys[0]
        pre, secs, units = loaded[k]
        print(f"\nSource url: {source_url_for(WORKS[k])}")
        print(f"\n--dry-run: prompt 1 for {units[0]['name']}:\n")
        print(build_prompt1(WORKS[k], units_dir_for(k), units, units[0]))
        print(f"\n[prompt 2 is always]: {PROMPT2}")
        return

    if args.split_only:
        for k in keys:
            pre, secs, units = loaded[k]
            print(f"Wrote {units[0]['name']} to {write_units(k, pre, units)}")
        return

    log_dir = os.path.join(WORK_DIR, "jerome_psalms_import_logs")
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(log_dir, f"run-{stamp}.jsonl")
    events_path = os.path.join(log_dir, f"run-{stamp}.events.jsonl")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}\n")

    failed = []
    with open(log_path, "a") as log, open(events_path, "a") as events_log:
        for k in keys:
            pre, secs, units = loaded[k]
            units_dir = write_units(k, pre, units)
            unit = units[0]
            try:
                process_unit(WORKS[k], units_dir, units, unit, log, events_log)
            except RuntimeError as exc:
                print(f"  ABORTING at {k} ({unit['name']}): {exc}")
                print(f"  (piece kept in {units_dir})")
                log.write(json.dumps({"unit": unit["name"], "error": str(exc)}) + "\n")
                log.flush()
                sys.exit(1)
            shutil.rmtree(units_dir)
            if run_check(WORKS[k], secs):
                failed.append(k)

    print(f"\nDone. {len(keys)} homily(ies) processed.")
    print(f"Summary log: {log_path}")
    print(f"Details log: {events_path}")
    if failed:
        print(f"CHECK FAILED for: {', '.join(failed)} (see above)")


if __name__ == "__main__":
    main()
