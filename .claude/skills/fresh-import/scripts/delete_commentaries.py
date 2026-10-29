import os
import re
import sys
import tomllib

# Cut whole [[commentary]] blocks out of the file text rather than re-serializing the
# file, so the blocks that stay keep their exact formatting ('''-quoted strings etc.).
# These scripts live in <Commentaries-Database>/.claude/skills/fresh-import/scripts.
PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "..", "..", "..", ".."))
BLOCK_START_RE = re.compile(r"(?m)^\[\[commentary\]\][ \t]*$")


def split_blocks(text):
    """File text -> (preamble, [block texts]); each block starts at its [[commentary]]."""
    starts = [m.start() for m in BLOCK_START_RE.finditer(text)]
    if not starts:
        return text, []
    bounds = starts + [len(text)]
    return text[:starts[0]], [text[a:b] for a, b in zip(bounds, bounds[1:])]


def delete_commentaries(father_name, source_url, dry_run=False, title_prefix=None):
    """Delete every block whose source_url is exactly `source_url` (and, if `title_prefix`
    is given, whose source_title also starts with it)."""
    if not source_url and not title_prefix:
        # An empty url alone would match every url-less block of this father.
        raise SystemExit("Refusing an empty source_url without --title-prefix")

    def matches(c):
        return c.get('source_url') == source_url and (
            title_prefix is None or c.get('source_title', '').startswith(title_prefix))

    base_path = os.path.join(PROJECT_DIR, father_name)
    files = sorted(f for f in os.listdir(base_path) if f.endswith('.toml'))
    total_files = len(files)

    print(f"Total files to process: {total_files}")
    total_removed = files_touched = 0

    for count, filename in enumerate(files, start=1):

        if count % 100 == 0 or count == total_files:
            print(f"Processed {count}/{total_files} files")

        file_path = os.path.join(base_path, filename)

        with open(file_path, 'r', encoding='utf-8') as file:
            text = file.read()
        if source_url not in text or (title_prefix and title_prefix not in text):
            continue

        original = tomllib.loads(text).get('commentary', [])
        preamble, blocks = split_blocks(text)
        if len(blocks) != len(original):
            print(f"SKIPPED (could not split into blocks cleanly): {filename}")
            continue

        kept = [b for b, c in zip(blocks, original) if not matches(c)]
        removed = len(blocks) - len(kept)
        if not removed:
            continue
        total_removed += removed
        files_touched += 1

        if not kept:
            print(f"Deleted {removed} commentary, removed file: {filename}")
            if not dry_run:
                os.remove(file_path)
            continue

        new_text = (preamble + "".join(kept)).rstrip("\n") + "\n"
        # The surviving blocks must parse back to exactly what they were.
        expected = [c for c in original if not matches(c)]
        if tomllib.loads(new_text).get('commentary', []) != expected:
            print(f"SKIPPED (result did not round-trip): {filename}")
            continue

        print(f"Deleted {removed} commentary, kept {len(kept)}: {filename}")
        if not dry_run:
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(new_text)

    verb = "Would delete" if dry_run else "Deleted"
    print(f"{verb} {total_removed} commentary block(s) in {files_touched} file(s)")


if __name__ == "__main__":
    argv = sys.argv[1:]
    title_prefix = None
    if "--title-prefix" in argv:
        i = argv.index("--title-prefix")
        if i + 1 >= len(argv):
            print("--title-prefix needs a value")
            sys.exit(1)
        title_prefix = argv[i + 1]
        del argv[i:i + 2]
    args = [a for a in argv if a != "--dry-run"]
    if len(args) != 2:
        print("Usage: python delete_commentaries.py <father_name> <source_url> "
              "[--title-prefix PREFIX] [--dry-run]")
        print("  --title-prefix: only blocks whose source_title starts with PREFIX "
              "(required when <source_url> is \"\")")
        sys.exit(1)

    father_name = args[0]
    source_url = args[1]

    delete_commentaries(father_name, source_url, dry_run="--dry-run" in argv,
                        title_prefix=title_prefix)
