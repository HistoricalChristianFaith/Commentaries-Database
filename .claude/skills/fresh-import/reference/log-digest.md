# Digesting the run logs

Read this after a run of many pieces (a chunk of 20 or more) or a run of an importer that still
uses the old generic prompt 2 (every importer but Jerome's: `reference/new-importer.md`). For a
small run of Jerome's importer, the check records and prompt answers are short enough to read
yourself (SKILL.md §5).

Don't read the `.events.jsonl` files into your own context. Have a read-only subagent
(`general-purpose`) digest the summary log, with a prompt along these lines:

> Read-only. Read every record's full `output` in `<logs>` (JSON lines: unit, sections, prompt
> 1=import/2=follow-up (`prompt2_kind` fix/review/legacy), output; check records with `check`,
> `counts`, `hard`, `soft`, `lemma_unfiled`, `info`; or unit+error). Digest per piece only what
> a reviewer needs: errors or aborted pieces; the HARD lines and whether prompt 2 fixed them;
> anything prompt 2 found and fixed; every judgment call the agent flagged (placements to check,
> blocks under a verse other than the heading's, fragments, overlapping ranges, ordering
> problems in files); whether each Book preface was skipped or filed (and where); text
> deliberately left out; every cross-book file created or appended, and the cross-references
> considered and not filed, with the reasons; any edit to pre-existing blocks of other works;
> any rename, move or delete of earlier pieces' files. Expected decisions: <list>. End with the
> top issues. Under ~1200 words.

Then verify the digest's top issues yourself before reporting them: an agent's stated reason can
be wrong while its call is right (a passing proof-text skipped "because the KJV lookup has no
such verse").

With the per-piece checks, the check records already list the HARD/SOFT/INFO lines per piece,
which replaces most of this digest's job: the digest then only needs the prompt answers.
