#!/usr/bin/env python3
"""Review aid for process_jerome_commentary.py imports (written during the Isaiah import, #35).

    python3 audit_jerome_import.py <Work> --headings                 # BEFORE importing: headings vs KJV
    python3 audit_jerome_import.py <Work> <BASE> Part001_Ch01a ...   # audit the given pieces
    python3 audit_jerome_import.py <Work> <BASE> --all               # audit the whole work

<Work> is a key of WORKS in process_jerome_commentary.py; <BASE> is the commit that deleted the
old import (everything after it is the new import). Reports, for this work's blocks:
  * verbatim: every block is one exact stretch of the source (text normalised like run_check),
    and matches it only once; overlaps between blocks in the commented book's own files;
  * coverage of the scoped sections, with each gap's section and opening words;
  * append-only: every file changed since BASE has no removed lines and keeps its old text as a
    prefix (a "removed line" whose text reappears is usually a file that lacked a final newline);
  * lemmas: each verse section's first block starts at the section start and runs past the
    lemma (opening italic run(s), plus the LXX run(s) if they follow directly -- CHECK this
    heuristic against the work's lemma layout before trusting it);
  * placement hints: "PLACEMENT?" when the lemma's opening reads like a different KJV verse than
    the first block's file (often a lemma opening with the previous verse's second half, which is
    then correct), blocks far outside their heading, wide ranges and very small blocks;
  * where each non-verse section (Prologue, Book N) went, and a per-section LAYOUT for reading.
"""
import os, re, sys, subprocess, sqlite3, tomllib, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from process_jerome_commentary import (WORKS, load_work, make_units, paragraphs_of, _norm,
                                       _clean, source_url_for, SPLIT_CHARS, PROJECT_DIR, FATHER)

KJV_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kjv.sqlite")
STOP = set("the and of to a in that he shall be his is they for i you your will them their which "
           "with not it are from my by have as on all who but this was me o so at or thee thou thy "
           "ye unto".split())


def words(s):
    return {w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP and len(w) > 2}


def head_range(h):
    """'12:3b-5' -> ((12,3),(12,5)); 'N:N-N:N' crosses chapters; 'ff.' widens by 6."""
    h = h.split(" ¶")[0]  # a paragraph lemma's guessed verse (see paragraph_sections)
    h = re.sub(r"\s*\(Latin [^)]*\)", "", h)  # Hosea: "14:1-3 (Latin 14:2-4)"
    n = list(map(int, re.findall(r"\d+", h)))
    if re.fullmatch(r"\d+:\d+[a-c]?-\d+:\d+.*", h):
        return (n[0], n[1]), (n[2], n[3])
    return (n[0], n[1]), (n[0], max(n[1:]) + (6 if "ff" in h or h.endswith("f.") else 0))


def opening_lemma_end(body):
    """html offset where the opening italic run(s) end (Hebrew lemma, then LXX run(s)).
    Handles Isaiah's `LXX: <i>..</i>` and Ezekiel's plain `(LXX: "..")`, plus inline
    alternatives such as `(or <i>..</i>)` and short editorial parentheses."""
    # Habakkuk 1:3b-4 and 3:3b-4 (and Obadiah 1:13b-14): the first paragraph holds only the
    # first half-verse, and the lemma runs on in the next paragraph, followed by the LXX.
    # (Hosea 4:5b-6, 5:2b-4, 10:13b-15 etc.: a period or comma after each italic run.)
    m = re.match(r"\s*<i>[^<]*</i>[.,]?\s*(?:<br\s*/?>\s*){2,}(?=<i>[^<]*</i>\.?\s*LXX:)", body)
    j = end = m.end() if m else 0
    paren = r"\((?!LXX)(?:[^()<]|<i>[^<]*</i>){0,200}\)"
    # Joel 3:4-6 interrupts its LXX run with a dashed gloss: `— for this is what .. means —.`
    # (Hosea 10:11: `— or a cow; for what in Hebrew is called egla, .. signifies both —; <i>Ephraim</i>,
    # then, <i>is a heifer ..`)
    dashed = r"—[^—<]{1,120}—"
    # Zechariah 3:8-9 and 9:5-8 leave a Greek word glossed with "that is" outside the italics:
    # `.. for the men</i> τερατοσκόποι, that is, of portents, <i>are beholders ..`
    greek = r"[Ͱ-Ͽἀ-῿]+(?: [Ͱ-Ͽἀ-῿]+)*, that is, [^<,]{1,40},"
    # Micah 1:1 introduces its LXX with `Or according to the Seventy:`, and 6:1-2 with `: LXX.`;
    # Hosea 13:3 with `LXX: likewise; changing only this, which is at the end:`, and 13:4 with
    # `In place of which one reads in the LXX:`; Amos 1:1 with `But the Seventy, intending I know
    # not what, translated:`.
    pat = (r"(?:\s|[÷※⁚.,;:—\"“”'‘’-]|\[[^\]]{0,40}\]|\bor\b|\bthen\b|LXX: likewise; changing only "
           r"this, which is at the end:|In place of which one reads in the LXX:|LXX[:.]|Or according "
           r"to the Seventy:|But the Seventy, intending I know not what, translated:|" + paren + "|" + dashed + "|" + greek + r")*<i>.*?</i>")
    while True:
        m = re.match(pat, body[j:], re.S)
        if m:
            j += m.end(); end = j
            continue
        # Joel 1:4: the LXX is given in plain text as `LXX: likewise.` (Zephaniah 1:1: no colon)
        m = re.match(r"[\s.]*LXX:? likewise\.", body[j:])
        if m:
            return j + m.end()
        # Ezekiel: `(LXX: "..")`, sometimes running on with Jerome's remarks on the
        # Origenian signs before it closes -- take it to its matching parenthesis.
        m = re.match(r"[\s.,;:]*\(LXX:", body[j:])
        if not m:
            return end
        k, depth = j + m.end(), 1
        while k < len(body) and depth:
            depth += {"(": 1, ")": -1}.get(body[k], 0)
            k += 1
        if depth:
            return end
        k += len(re.match(r"\.?", body[k:]).group())
        j = end = k


def load_kjv(book):
    """{(chapter, verse): text} for one book of the KJV."""
    kdb = sqlite3.connect(KJV_DB)
    kjv = {(l // 1000000, l % 1000000): t for l, t in kdb.execute(
        "select txt_location, txt from bible_kjv where book=?", (book.lower(),))}
    if not kjv:
        sys.exit(f"no KJV rows for book {book.lower()!r}")
    return kjv


PARA_RE = re.compile(r"(?:<br\s*/?>\s*){2,}")
BACKSTEP = 0.5


def paragraph_sections(secs, kjv):
    """For works whose <h2> headings are whole chapters and whose every paragraph opens with
    its own lemma (Matthew, `lemma_paragraphs`): one pseudo-section per paragraph, headed by
    the KJV verse its lemma most likely quotes, e.g. "5:22 ¶17". The guesses come from word
    overlap with the KJV, aligned so that they never go backwards within a chapter; they are
    HINTS for review, never given to the agent. Non-verse sections are kept as they are.
    Each pseudo-section also carries `parent` (its chapter section) and `score` (0-1)."""
    stem = lambda s: {w[:5] for w in words(s)}
    out = []
    for s in secs:
        if not s["chapter"]:
            out.append(dict(s, parent=s, score=None))
            continue
        c = s["chapter"]
        cand = sorted(k for k in kjv if k[0] == c or (k[0] == c + 1 and k[1] <= 3)
                      or (k[0] == c - 1 and k[1] > max(v for cc, v in kjv if cc == c - 1) - 3))
        ks = [stem(kjv[k]) for k in cand]
        paras = [p for p in PARA_RE.split(s["body"]) if _clean(p)]
        sc = []
        for p in paras:
            lw = stem(_clean(p[:opening_lemma_end(p)]) or _clean(p)[:150])
            sc.append([len(lw & k) / max(1, len(lw)) for k in ks])
        # Best path through the candidate verses; a step back costs BACKSTEP (Jerome's order
        # is the Vulgate's, which now and then differs from the KJV's, e.g. Matthew 5:4-5).
        best, back = [], []
        for i, row in enumerate(sc):
            if not i:
                best.append(row[:]); back.append([None] * len(row)); continue
            cur, bk = [], []
            for j, x in enumerate(row):
                pj = max(range(len(row)),
                         key=lambda q: best[-1][q] - (BACKSTEP if q > j else 0))
                cur.append(x + best[-1][pj] - (BACKSTEP if pj > j else 0)); bk.append(pj)
            best.append(cur); back.append(bk)
        j = max(range(len(cand)), key=lambda j: best[-1][j]) if sc else 0
        path = []
        for i in range(len(sc) - 1, -1, -1):
            path.append(j)
            j = back[i][j]
        path.reverse()
        for k, (p, j) in enumerate(zip(paras, path), 1):
            out.append(dict(heading=f"{cand[j][0]}:{cand[j][1]} ¶{k}", chapter=c,
                            body=p + "\n", html=p, parent=s, score=sc[k - 1][j]))
    return out


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    work = WORKS[sys.argv[1]]
    book = work["book"]
    pre, chapter_secs = load_work(work)
    kjv = load_kjv(book)
    secs = (paragraph_sections(chapter_secs, kjv) if work.get("lemma_paragraphs")
            else [dict(s, parent=s) for s in chapter_secs])

    def lemma_opening(s):
        m = re.search(r"<i>(.*?)</i>", s["body"], re.S)
        return _clean(m.group(1)).split("LXX:")[0][:200] if m else ""

    def best_verse(s):
        (c0, v0), _ = head_range(s["heading"])
        lw = words(lemma_opening(s))
        sc = lambda v: len(lw & words(kjv.get((c0, v), ""))) / max(1, len(words(kjv.get((c0, v), ""))))
        return c0, v0, max(range(max(1, v0 - 3), v0 + 4), key=sc), sc

    if sys.argv[2] == "--headings" and work.get("lemma_paragraphs"):
        # No verse headings to check: list each paragraph lemma's guessed verse instead, with
        # the weak matches marked, so the guesses can be checked against the KJV by eye.
        for s in secs:
            if s["chapter"]:
                low = "LOW " if s["score"] < 0.4 else "    "
                print(f"  {low}{s['heading']:>12} {s['score']:.2f} {lemma_opening(s)[:100]!r}")
            else:
                print(f"  [{s['heading']}] (non-verse, {len(_clean(s['body']))} chars)")
        return

    if sys.argv[2] == "--headings":
        count = collections.Counter(c for c, v in kjv)
        print("heading formats:", collections.Counter(
            re.sub(r"\d+", "N", s["heading"]) for s in secs if s["chapter"]).most_common())
        for s in secs:
            if not s["chapter"]:
                continue
            lo, hi = head_range(s["heading"])
            for cv in {lo, hi}:
                if cv not in kjv:
                    print(f"  NOT IN KJV [{s['heading']}] {cv} (chapter has {count[cv[0]]})")
            c0, v0, best, sc = best_verse(s)
            if best != v0 and sc(best) > sc(v0) + 0.15:
                print(f"  [{s['heading']}] lemma opens like KJV {c0}:{best}: {lemma_opening(s)[:90]!r}")
            if not s["body"].strip().startswith("<i>"):
                print(f"  [{s['heading']}] does not open with italics: {_clean(s['body'])[:90]!r}")
            if len(_clean(re.sub(r"<i>.*?</i>", " ", s["body"], flags=re.S))) < 40:
                print(f"  [{s['heading']}] is (almost) lemma-only -- check the piece boundary after it")
        return

    BASE, args = sys.argv[2], sys.argv[3:]
    url = source_url_for(work)
    folder = os.path.join(PROJECT_DIR, FATHER)
    units = make_units(pre, chapter_secs, SPLIT_CHARS)
    parts = [" ".join(paragraphs_of(s)) for s in secs]
    source = _norm(" ".join(parts))
    offs, pos = [], 0
    for p in parts:
        n = _norm(p)
        a = source.index(n, pos) if n else pos
        offs.append((a, a + len(n))); pos = a + len(n)

    def sec_at(i):
        for k, (a, b) in enumerate(offs):
            if a <= i < b:
                return k

    if args == ["--all"]:
        scope = set(range(len(secs)))
    else:
        want = {a.removesuffix(".html") for a in args}
        names = {u["name"].removesuffix(".html") for u in units}
        if want - names:
            sys.exit(f"unknown piece(s): {sorted(want - names)}")
        chosen = [id(s) for u in units if u["name"].removesuffix(".html") in want
                  for s in u["sections"]]
        scope = {i for i, s in enumerate(secs) if id(s["parent"]) in chosen}

    blocks, problems = [], []
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".toml"):
            continue
        t = open(os.path.join(folder, fn), encoding="utf-8").read()
        if url not in t:
            continue
        for k, c in enumerate(tomllib.loads(t)["commentary"]):
            if c.get("source_url") != url:
                continue
            if c.get("source_title") != work["source_title"]:
                problems.append(f"{fn}#{k}: title {c.get('source_title')!r}")
            q = _norm(c["quote"])
            hits = [m.start() for m in re.finditer(re.escape(q), source)]
            if not hits:
                problems.append(f"NOT VERBATIM {fn}#{k}: {q[:90]!r}"); continue
            if len(hits) > 1:
                problems.append(f"MULTI-MATCH {fn}#{k} at {hits}")
            blocks.append(dict(a=hits[0], e=hits[0] + len(q), fn=fn[:-5], k=k,
                               own=fn.startswith(book + " "), sec=sec_at(hits[0])))
    own = sorted((b for b in blocks if b["own"]), key=lambda b: (b["a"], b["e"]))
    print(f"blocks of this work: {len(blocks)} ({len(own)} in {len({b['fn'] for b in own})} {book} "
          f"files, {len(blocks) - len(own)} cross-refs); scope: {len(scope)} sections")

    for x, y in zip(own, own[1:]):
        if y["a"] < x["e"]:
            problems.append(f"OVERLAP {x['fn']}#{x['k']} / {y['fn']}#{y['k']} "
                            f"[{secs[y['sec']]['heading']}]: {source[y['a']:min(x['e'], y['e'])][:100]!r}")

    cov = bytearray(len(source))
    for b in own:
        cov[b["a"]:b["e"]] = b"\1" * (b["e"] - b["a"])
    tot = got = 0
    for i in sorted(scope):
        a, e = offs[i]
        tot += sum(1 for j in range(a, e) if source[j] != " ")
        got += sum(1 for j in range(a, e) if source[j] != " " and cov[j])
        j = a
        while j < e:
            if cov[j]:
                j += 1; continue
            g = j
            while g < e and not cov[g]:
                g += 1
            if source[j:g].strip():
                print(f"  GAP [{secs[i]['heading']}] {g - j} chars: {source[j:g].strip()[:110]!r}")
            j = g
    print(f"coverage of scoped sections: {100 * got / max(1, tot):.2f}%")

    diff = subprocess.run(["git", "-C", PROJECT_DIR, "diff", "--numstat", BASE, "--", FATHER],
                          capture_output=True, text=True, check=True).stdout
    for line in diff.splitlines():
        add, rem, path = line.split("\t")
        old = subprocess.run(["git", "-C", PROJECT_DIR, "show", f"{BASE}:{path}"],
                             capture_output=True, text=True).stdout
        if not os.path.exists(os.path.join(PROJECT_DIR, path)):
            print(f"  note: {path} was deleted since {BASE} -- make sure that was intended")
            continue
        new = open(os.path.join(PROJECT_DIR, path), encoding="utf-8").read()
        if not new.startswith(old.rstrip("\n")):
            problems.append(f"NOT APPEND-ONLY: {path}")
        elif rem != "0":
            print(f"  note: {path} -{rem} line(s) but old text is a prefix (final-newline change)")
    print(f"files added or changed since {BASE}: {len(diff.splitlines())} (pre-existing ones must be append-only)")

    first = {}
    for b in own:
        first.setdefault(b["sec"], b)
    for i in sorted(scope):
        s = secs[i]
        if not s["chapter"]:
            continue
        fb = first.get(i)
        # Matthew: a paragraph whose sentence runs on into this lemma ("For there follows:") is
        # joined with it in one block when both are the same verse.
        prev = _clean(secs[i - 1]["body"]) if i and work.get("lemma_paragraphs") else ""
        if (prev and prev[-1] not in ".?!)'" and (not fb or fb["a"] != offs[i][0])
                and any(b["a"] < offs[i][0] < b["e"] and b["sec"] == i - 1 for b in own)):
            print(f"  joined to lead-in [{s['heading']}]: {prev[-50:]!r}")
            continue
        if not fb or fb["a"] != offs[i][0]:
            problems.append(f"LEMMA [{s['heading']}]: no block starts at the section start"); continue
        lem_end = len(_norm(_clean(s["body"][:opening_lemma_end(s["body"])])))
        if not lem_end:
            problems.append(f"LEMMA? [{s['heading']}]: section does not open with italics")
        elif fb["e"] - fb["a"] < lem_end:
            problems.append(f"LEMMA CUT [{s['heading']}]: first block {fb['fn']} ends inside the lemma")
        c0, v0, best, sc = best_verse(s)
        m = re.fullmatch(rf"{re.escape(book)} (\d+)_(\d+)(?:-(\d+))?(?:_(\d+))?", fb["fn"])
        if m:
            lo = (int(m[1]), int(m[2]))
            hi = (int(m[3]), int(m[4])) if m[4] else (int(m[1]), int(m[3] or m[2]))
            if not lo <= (c0, best) <= hi:
                problems.append(f"PLACEMENT? [{s['heading']}] lemma opens like KJV {c0}:{best}, "
                                f"first block in {fb['fn']}")

    for b in own:
        s = secs[b["sec"]]
        m = re.fullmatch(rf"{re.escape(book)} (\d+)_(\d+)(?:-(\d+))?(?:_(\d+))?", b["fn"])
        lo = (int(m[1]), int(m[2]))
        hi = (int(m[3]), int(m[4])) if m[4] else (int(m[1]), int(m[3] or m[2]))
        if s["chapter"]:
            hlo, hhi = head_range(s["heading"])
            if hi < (hlo[0], hlo[1] - 3) or lo > (hhi[0], hhi[1] + 3):
                problems.append(f"OUTSIDE HEADING [{s['heading']}] {b['fn']}#{b['k']}: "
                                f"{source[b['a']:b['a'] + 70]!r}")
        if lo[0] == hi[0] and hi[1] - lo[1] >= 5:
            print(f"  wide range [{s['heading']}] {b['fn']} ({b['e'] - b['a']} chars)")
        if b["e"] - b["a"] < 250:
            print(f"  small block [{s['heading']}] {b['fn']}#{b['k']} ({b['e'] - b['a']}): "
                  f"{source[b['a']:b['e']][:90]!r}")

    for i in sorted(scope):
        s = secs[i]
        if s["chapter"]:
            continue
        a, e = offs[i]
        where = [f"{b['fn']}#{b['k']}" for b in blocks if b["a"] < e and b["e"] > a]
        print(f"  {s['heading']}: {', '.join(where) or 'SKIPPED'}")
    p11 = os.path.join(folder, f"{book} 1_1.toml")
    if os.path.exists(p11):
        print(f"  {book} 1_1 blocks:", [(c.get("source_title", "")[:30], len(c["quote"]))
                                       for c in tomllib.load(open(p11, "rb"))["commentary"]])

    print("\nLAYOUT")
    by_sec = collections.defaultdict(list)
    for b in sorted(blocks, key=lambda b: b["a"]):
        by_sec[b["sec"]].append(b)
    for i in sorted(scope):
        seq = "  ".join((b["fn"].replace(book + " ", "") if b["own"] else f"[{b['fn']}]")
                        + f"({b['e'] - b['a']})" for b in by_sec.get(i, []))
        print(f"  {secs[i]['heading']:>12}: {seq}")

    print(f"\nPROBLEMS ({len(problems)}):")
    for p in problems:
        print("  -", p)


if __name__ == "__main__":
    main()
