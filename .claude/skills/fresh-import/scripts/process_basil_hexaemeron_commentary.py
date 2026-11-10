#!/usr/bin/env python3
"""Import Basil of Caesarea's Hexaemeron (Blomfield Jackson's public-domain translation, NPNF
2nd series vol. 8) into the Commentaries-Database, one homily at a time, by driving a headless
``claude`` agent.

A per-work copy of process_augustine_commentary.py (Augustine's Tractates on John, see
../SKILL.md, "A homily series, one file per sermon"): the same two-prompt flow, logs, --check
and --order. Each of the nine homilies is its own file in the Writings-Database, with its own
url, so each is its own WORKS entry ("Hex01" .. "Hex09"):

    Writings-Database/Basil of Caesarea/The Hexaemeron/Homily 6-The Creation of Luminous Bodies.html

    <h1>Homily 6-The Creation of Luminous Bodies</h1>
    1. At the shows in the circus ...<sup><a href="#fn1" id="r1">1</a></sup> ...<br/><br/>
    2. ...                                     (numbered paragraphs, no lemma, no passage line)
    <section class="notes">...                 (Jackson's notes: Scripture, classical parallels)

A homily preaches on one day's work of Genesis 1, quoting each verse (often in italics) as it
reaches it. ``load_work`` gives ONE section per homily (WORKS "homily": True), headed by the
passage in PASSAGES (an audit hint only: there is no passage line in the source), and one piece
per homily (the biggest, Homily 6, is ~45k chars with the notes inline; a homily is never cut).
The NPNF paragraph numbers ("2. ") are dropped from the pieces and the body, as with the
Tractates. Jackson's notes are shown to the agent inline, as ``<sup>[note: Ps. lxxv. 3.]</sup>``;
the body (the text imported and checked) drops them.

The source was rebuilt from CCEL and corrected against the 1895 print just before this import
(Writings-Database fe650214, 012c3a8c).

    python3 process_basil_hexaemeron_commentary.py Hex01 --dry-run
    python3 process_basil_hexaemeron_commentary.py Hex01
    python3 process_basil_hexaemeron_commentary.py Hex02-Hex09     # one homily after another
    python3 process_basil_hexaemeron_commentary.py Hex01-Hex09 --check
    python3 process_basil_hexaemeron_commentary.py Hex01 --order           # all files: homily order
    python3 process_basil_hexaemeron_commentary.py Hex01 --fix-order BASE  # ... and fix it
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
import unicodedata
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

FATHER = "Basil of Caesarea"

# Not used to cut anything (a homily is one piece, whatever its size); kept for the audit.
SPLIT_CHARS = 60000

RETRY_DELAYS = [5, 15, 45]
RATE_LIMIT_DELAYS = [60, 120, 240]

# --- Per-work configuration ---------------------------------------------------

HEXAEMERON = "Basil of Caesarea/The Hexaemeron"


def _homily_files():
    """{n: file name} of the nine homilies ("Homily 6-The Creation of Luminous Bodies.html")."""
    folder = os.path.join(WRITINGS_DIR, HEXAEMERON)
    out = {}
    for fn in os.listdir(folder) if os.path.isdir(folder) else []:
        m = re.match(r"Homily (\d+)-.*\.html$", fn)
        if m:
            out[int(m[1])] = fn
    return out


# The Genesis passage each homily preaches on (a HINT for the audit and the prompt; the source
# has no passage line). Homily 8 opens on 1:24 and then turns back to the birds of 1:20-22, which
# the morning's Homily 7 had left out; Homily 9 (the evening) takes up 1:24 again.
PASSAGES = {1: "1:1", 2: "1:2-5", 3: "1:6-8", 4: "1:9-10", 5: "1:11-13", 6: "1:14-19",
            7: "1:20-21", 8: "1:20-25", 9: "1:24-27"}

# Notes for every homily (in the prompt), then each homily's own.
COMMON_NOTES = (
    "The passage named above is OUR GUESS from the homily's title and the verses it quotes, a "
    "HINT ONLY: the source names none, and Basil often recalls earlier verses or looks ahead. "
    "Basil quotes Genesis from the Greek (the Septuagint), so his wording often differs from the "
    "KJV (\"the earth was invisible and unfinished\" = Genesis 1:2 \"without form, and void\"; "
    "\"Let the waters bring forth abundantly the moving creature that hath life\" = 1:20): place "
    "each stretch by the sense of the verse he is expounding.")
HOMILY_NOTES = {
    1: ("This is the first homily: its opening (\"It is right that any one beginning to narrate "
        "the formation of the world\" ... down to the first quotation of \"In the beginning God "
        "created the heaven and the earth\") introduces the whole series; it stays at the start "
        "of the first block, which goes in \"Genesis 1_1\" (the old blocks there have been "
        "deleted, so create the file)."),
    8: ("This homily opens on Genesis 1:24 (\"Let the earth bring forth the living creature\"), "
        "but Basil soon notices that the birds of 1:20-22, created with the fishes, were left out "
        "of the morning's homily, and turns back to them for most of the sermon. File each "
        "stretch under the verse it actually expounds (1:24 for the opening, 1:20-22 for the "
        "birds), keeping the blocks in Basil's order."),
}

WORKS = {
    f"Hex{n:02d}": {
        "html": f"{HEXAEMERON}/{fn}",
        "book": "Genesis",
        "homily": True,
        "number": n,
        # As the url'd Hexaemeron blocks mostly already had it ("The Hexaemeron, Homily 6: The
        # Creation of Luminous Bodies"); Homily 2's title drops the file name's quotation marks.
        "source_title": (f"The Hexaemeron, Homily {n}: "
                         + re.sub(r"^Homily \d+-|\.html$", "", fn).replace('"', "")),
        "passage": PASSAGES[n],
        "notes": HOMILY_NOTES.get(n, ""),
    }
    for n, fn in sorted(_homily_files().items())
}


def source_url_for(work):
    """historicalchristian.faith url for a Writings-Database file. Every segment, the father
    folder included, is double-encoded (spaces as %2520, Homily 2's quotation marks as %2522),
    with %2F between segments, matching the existing urls
    ("file=Basil%2520of%2520Caesarea%2FThe%2520Hexaemeron%2FHomily%25206-The%2520...")."""
    segs = work["html"].split("/")
    return ("https://historicalchristian.faith/by_father.php?file="
            + "%2F".join(quote(seg, safe="").replace("%", "%25") for seg in segs))


def units_dir_for(work_key):
    return os.path.join(WORK_DIR, f"basil_{work_key.lower()}_units")


# --- Parsing ------------------------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")
FOOTNOTE_REF_RE = re.compile(r'<sup><a href="#fn(\d+)" id="r\d+">\d+</a></sup>')
NOTES_RE = re.compile(r'<section class="notes">(.*?)</section>\s*', re.S)
NOTE_RE = re.compile(r'<span id="fn(\d+)"><a href="#r\d+">\d+</a>(?:&nbsp;|\s)*(.*?)</span>', re.S)
# An NPNF paragraph number opening a paragraph: "2. " (all regular in the Hexaemeron).
PARA_NO_RE = re.compile(r"(^|<br/><br/>\n)\s*\d{1,2}\.\s+")


def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s))).strip()


def _notes(text):
    m = NOTES_RE.search(text)
    return {int(k): _clean(t) for k, t in NOTE_RE.findall(m.group(1))} if m else {}


def load_work(work):
    """Return (preamble_html, sections): ONE section per homily. Its heading is the passage
    from PASSAGES ("1:14-19"); its html is what the agent sees (the text with the notes inline as
    [note: ...] hints); its body is the text alone (no notes or paragraph numbers); `chapter` is
    the passage's first chapter."""
    path = os.path.join(WRITINGS_DIR, work["html"])
    with open(path, encoding="utf-8") as f:
        text = f.read()
    notes = _notes(text)
    text = NOTES_RE.sub("", text).replace("</article>", "")
    head_end = text.index("</h1>") + len("</h1>\n")
    preamble, rest = text[:head_end], text[head_end:]
    heading = work["passage"]
    nums = re.findall(r"(?:^|<br/><br/>\n)\s*(\d{1,2})\.\s", rest)
    if nums != [str(i) for i in range(1, len(nums) + 1)] or not nums:
        raise SystemExit(f"{work['html']}: paragraph numbers not 1..n: {nums}")
    rest = PARA_NO_RE.sub(r"\1", rest).rstrip() + "\n"
    refs = [int(r) for r in re.findall(r'href="#fn(\d+)"', rest)]
    if len(FOOTNOTE_REF_RE.findall(rest)) != len(refs) or set(refs) - set(notes):
        raise SystemExit(f"{work['html']}: a note marker the regex misses or without a note")
    def hint(r):
        n = int(r.group(1))
        return f"<sup>[note: {html.escape(notes[n], quote=False)}]</sup>" if n in notes else ""
    hinted = FOOTNOTE_REF_RE.sub(hint, rest)
    # Homilies 2, 7 and 8 have a note marker in the <h1> title ("Gen. i. 2, LXX."): hinted too.
    preamble = FOOTNOTE_REF_RE.sub(hint, preamble)
    section = {
        "heading": heading,
        "chapter": int(heading.split(":")[0]),
        "html": hinted,
        "body": FOOTNOTE_REF_RE.sub("", rest),
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
    """One piece per homily, named by its number ("Hom06.html")."""
    n = int(re.search(r"<h1>Homily (\d+)", preamble).group(1))
    return [{"name": f"Hom{n:02d}.html", "chapter": sections[0]["chapter"],
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
    "We have Basil of Caesarea's Hexaemeron here: nine homilies on the six days of creation "
    "(Genesis 1), each a file of its own. This piece is Homily {number}, "
    "\"{units_dir}/{unit_name}\", cut from our PUBLIC-DOMAIN English translation (Blomfield "
    "Jackson's, NPNF 2nd series vol. 8), \"{html_path}\" (consult it if you need surrounding "
    "context; the other homilies are in the same folder). The homilies are sermons preached on "
    "the book of {book}, one day's work after another -- file everything under the book "
    "\"{book}\", in the \"{father}/\" folder.\n\n"
    "Your task is to process the following file:\n"
    "{unit_name}  (its passage, by our guess: {book} {heading})\n\n"
    "Read the WHOLE file and import its commentary IN FULL into our commentaries db. The piece "
    "repeats the homily's title at the top -- that is not commentary; don't import it.\n\n"
    "VERSE KEYS. There are no verse labels or lemmas: Basil works through his passage, quoting "
    "each verse (often in italics) as he reaches it and expounding it, often with long "
    "digressions -- on the Greek philosophers and astronomers, on the nature of the elements, "
    "on plants, fishes, birds and beasts, and moral lessons drawn from them -- that arise from "
    "the verse in hand. Jackson's notes are shown inline as \"[note: ...]\" in superscript after "
    "the words they refer to: Scripture references (\"[note: Gen. i. 6.]\", \"[note: Ps. lxxv. "
    "3.]\"), and many parallels from Aristotle, Plato, Cicero, Philo and others, manuscript "
    "readings and Greek words; they are hints, not text to import. For each stretch of "
    "commentary, work out which KJV verse(s) of {book} it actually expounds -- compare the "
    "Scripture Basil quotes and discusses with the KJV text, looking it up with `" + KJV_LOOKUP
    + "` -- and file it there, under KJV chapter/verse numbering. A digression goes with the "
    "verse it arises from.{notes}\n\n"
    "Wherever possible, we want to use smaller verse ranges / individual verses. Do NOT simply "
    "file the homily under its whole passage: break it up wherever the exposition moves from "
    "one verse to the next, e.g. if a stretch comments on 1:16, insert it in 1:16, not in "
    "1:14-19. It's ok to use a range if necessary to avoid breaking up a coherent thought/piece "
    "(Basil sometimes expounds several verses as one argument), just prefer smaller "
    "ranges/individual verses -- but don't chop the sermon into tiny fragments either. The "
    "sermon's opening (a word to the hearers, a recap of the last sermon) stays at the start of "
    "the first block; its close (an exhortation, a prayer, a word about the next sermon) stays "
    "at the end of the last block. When you split the homily, its blocks together must still "
    "contain the WHOLE of it, every word -- and you split ONLY by cutting the text into "
    "consecutive stretches: each block must be one continuous stretch of Basil, in his order, "
    "from a sentence boundary to a sentence boundary. Do NOT duplicate the same stretch of "
    "commentary across several {book} verses -- put it ONCE, at its smallest accurate "
    "verse/range.\n\n"
    "CROSS-BOOK PARALLELS ARE WELCOME (and distinct from the within-{book} duplication "
    "forbidden above). Basil often quotes and expounds other Scripture (the Psalms, Job, "
    "Isaiah, the Gospels, Paul). Whenever a stretch genuinely QUOTES AND EXPOUNDS a specific "
    "verse from another book, you may ALSO file that portion under that verse in its own file "
    "(e.g. \"Psalms 104_24\", \"Romans 1_20\"), in addition to its {book} placement. File a "
    "cross-parallel only where Basil genuinely expounds the passage, not for a passing mention "
    "or a bare one-line proof-text. Use KJV book/verse numbering for the target file. Jackson's "
    "Psalm references follow the English (KJV) numbering (\"Ps. lxxv. 3\" = Psalms 75:3), but "
    "Basil quotes the Psalms from the Greek, so check the verse by its wording against the "
    "KJV.\n\n"
    "THE TEXT. Copy Basil's words VERBATIM -- nothing abridged, paraphrased, corrected, added "
    "or rearranged. Drop the html tags (italics simply become plain text; don't turn them into "
    "quotation marks) and separate paragraphs with a single blank line. Keep the translation's "
    "punctuation and spelling as printed: its curly quotation marks and apostrophes, em dashes, "
    "ellipses, the ligatures (\"Manichæans\", \"Anomœan\"), the translator's parentheses "
    "(\"(shadowed-on-both-sides )\", with its space), and the Greek words. Leave out the title "
    "and the \"[note: ...]\" hints. (The NPNF paragraph numbers have been removed from the "
    "piece; don't add them back.) Don't add headings, verse numbers or notes of your own. Don't "
    "write a python script to do this; process the file yourself manually.\n\n"
    "SOURCE FIELDS. For EVERY commentary you import from this homily, set:\n"
    "  source_url   = {source_url}\n"
    "  source_title = \"{source_title}\"\n"
    "(the same url and title for all of them -- this homily is one page).\n\n"
    "EXISTING BLOCKS. The old imports of these homilies have ALREADY been deleted, so you are "
    "only ADDING: if a verse file exists, append your [[commentary]] after its existing blocks; "
    "otherwise create it (with no blank line before its first [[commentary]]). Some {book} files "
    "hold blocks from Basil's other works (letters, homilies, On the Spirit, the monastic "
    "Rules): they stay first, untouched -- don't remove, merge or \"deduplicate\" them. Earlier "
    "runs of THIS import have already filed other homilies, so you will also find blocks titled "
    "\"The Hexaemeron, Homily N: ...\" for other homilies (another url) in the files you write "
    "to: those are NOT old imports or duplicates either; leave them exactly as they are and "
    "append yours after them."
)

PROMPT2 = "Double check, was this fully imported properly?"


def build_prompt1(work, units_dir, units, unit):
    notes = " ".join(x for x in (COMMON_NOTES, work.get("notes", "")) if x)
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
    # NFC, in case an agent retypes accented Greek in another code point form.
    s = unicodedata.normalize("NFC", s)
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
            raw = f.read()
        if url not in raw:
            continue
        # (The agents of the Athanasius run created 42 files opening with a blank line.)
        if raw.startswith("\n"):
            problems.append(f"{fn}: file starts with a blank line")
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
    """Cross-homily order: in each file, the Hexaemeron's blocks (all appended after the files'
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
            secs = load_work(WORKS[f"Hex{n:02d}"])[1]
            sources[n] = _norm(" ".join(" ".join(paragraphs_of(s)) for s in secs))
        return sources[n].find(_norm(quote))

    bad = []
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml") or fn == "metadata.toml":
            continue
        path = os.path.join(folder, fn)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if "The%2520Hexaemeron" not in text:
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
    """Work keys from the arguments: keys ("Hex05") and ranges ("Hex02-Hex09")."""
    keys = sorted(WORKS)
    out = []
    for spec in specs:
        a, _, b = spec.partition("-")
        if a not in WORKS or (b and b not in WORKS):
            raise SystemExit(f"unknown work {spec!r} (keys run Hex01 .. Hex09)")
        out += keys[keys.index(a):keys.index(b) + 1] if b else [a]
    return out


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "works", nargs="+",
        help="Homilies to import, run one after another: keys (Hex05) and/or ranges "
             "(Hex02-Hex09).",
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
                      help="Check that every file holds the Hexaemeron's blocks in homily order "
                           "(any works argument; all files are checked).")
    mode.add_argument("--fix-order", metavar="BASE",
                      help="As --order, and reorder the out-of-order files' appended blocks, "
                           "keeping their content at BASE (the deletion commit) unchanged.")
    args = parser.parse_args()
    if args.order or args.fix_order:
        sys.exit(1 if check_order(args.fix_order) and not args.fix_order else 0)
    keys = expand_works(args.works)

    with open(BOOK_NAMES_PATH, encoding="utf-8") as f:
        assert "Genesis" in json.load(f)["canonical_names"]

    loaded = {}
    for k in keys:
        pre, secs = load_work(WORKS[k])
        loaded[k] = (pre, secs, make_units(pre, secs, SPLIT_CHARS))

    if args.check:
        bad = [k for k in keys if run_check(WORKS[k], loaded[k][1], quiet=len(keys) > 1)]
        print(f"\n{len(keys) - len(bad)} of {len(keys)} homily(ies) pass the check"
              + (f"; failing: {', '.join(bad)}" if bad else ""))
        sys.exit(1 if bad else 0)

    print(f"Work:       {FATHER}, The Hexaemeron ({len(keys)} homily(ies))")
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

    log_dir = os.path.join(WORK_DIR, "basil_hexaemeron_import_logs")
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
