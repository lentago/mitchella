#!/usr/bin/env python3
"""docs-check: relative-link resolver for a repo's git-tracked markdown.

Resolves relative markdown links and images against the filesystem and fails
on genuinely broken ones, while skipping two link classes that resolve at a
layer this checker cannot see:

  site-absolute  Router routes such as `/library/` or `/guides/stormwater/` in
                 a site with client-side routing. The site router resolves
                 these at build time; they are not filesystem paths. Skipped
                 by rule.

  github-nav     GitHub's repo-relative navigation convention, e.g.
                 `../../issues/5`. These resolve on github.com and, because
                 they escape the repo root, can never point at a tracked file
                 anyway. Any relative link that resolves outside the repo root
                 is skipped by rule.

What remains after those two rules is handled by an explicit per-repo ignore
list: `--ignore GLOB` (repeatable), `--ignore-file FILE` (repeatable), and an
auto-loaded `<root>/.docs-check-ignore` if present. Precision is the
priority — the default posture is to skip anything unverifiable and flag only
links that unambiguously point at nothing.

Usage:
  check_docs_links.py [--root DIR] [--paths PATHSPEC ...]
                      [--ignore GLOB ...] [--ignore-file FILE ...]

Discovery is `git ls-files` over the pathspecs (default `*.md` / `*.markdown`),
so only tracked markdown is scanned — untracked scratch never reds the build.
Exit status is 0 only when every checked link resolves; broken links are all
listed in one run rather than failing on the first.
"""
import argparse
import fnmatch
import os
import re
import subprocess
import sys

# Inline links and images: [text](target) / ![alt](target), with an optional
# "title" after the target. Reference-style *definitions* ([label]: target) are
# picked up separately below; reference *usages* need no path check.
INLINE_RE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)>\s]+)>?(?:\s+[\"'(][^\"')]*[\"')])?\s*\)")
REFDEF_RE = re.compile(r"^\s{0,3}\[([^\]^][^\]]*)\]:\s*<?([^>\s]+)>?")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
SKIP_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)  # http:, mailto:, tel:, data:, …


def tracked_markdown(root, pathspecs):
    """git-tracked files matching the pathspecs, relative to root."""
    out = subprocess.run(
        ["git", "-C", root, "ls-files", "-z", "--", *pathspecs],
        capture_output=True, text=True, check=True)
    return [p for p in out.stdout.split("\0") if p.strip()]


def load_ignores(root, ignore_args, ignore_files):
    """Assemble the ignore glob list: CLI globs + files + repo .docs-check-ignore."""
    patterns = list(ignore_args)
    files = list(ignore_files)
    default_file = os.path.join(root, ".docs-check-ignore")
    if os.path.exists(default_file):
        files.append(default_file)
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    return patterns


def is_ignored(relfile, target, bare, patterns):
    """A link is ignored if any glob matches the source file OR the link target."""
    for pat in patterns:
        if (fnmatch.fnmatch(relfile, pat)
                or fnmatch.fnmatch(target, pat)
                or fnmatch.fnmatch(bare, pat)):
            return True
    return False


def iter_targets(lines):
    """Yield (lineno, target) for every checkable link, skipping fenced and
    inline code so example markdown in prose is never flagged."""
    in_fence = False
    fence_marker = ""
    for lineno, line in enumerate(lines, 1):
        stripped = line.lstrip()
        # Fenced code blocks open/close on ``` or ~~~ (length >= the opener).
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[0] * 3
            if not in_fence:
                in_fence, fence_marker = True, marker
            elif marker == fence_marker:
                in_fence, fence_marker = False, ""
            continue
        if in_fence:
            continue

        clean = INLINE_CODE_RE.sub("", line)
        for target in INLINE_RE.findall(clean):
            yield lineno, target
        m = REFDEF_RE.match(clean)
        if m:
            yield lineno, m.group(2)


def check_file(root, relfile, root_abs, patterns, failures):
    path = os.path.join(root, relfile)
    abs_dir = os.path.dirname(os.path.abspath(path))
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()

    for lineno, target in iter_targets(lines):
        if SKIP_SCHEME.match(target):          # http:, mailto:, tel:, data:, …
            continue
        if target.startswith("#"):             # in-page anchor
            continue
        if target.startswith("//"):            # protocol-relative //host/path
            continue
        if target.startswith("/"):             # site-absolute router route
            continue

        bare = target.split("#", 1)[0].split("?", 1)[0]
        if not bare:                           # pure #anchor / ?query
            continue
        if is_ignored(relfile, target, bare, patterns):
            continue

        resolved = os.path.normpath(os.path.join(abs_dir, bare))
        # GitHub repo-relative nav (../../issues/N) and any other link that
        # escapes the repo root cannot point at a tracked file — don't guess.
        if resolved != root_abs and not resolved.startswith(root_abs + os.sep):
            continue
        if not os.path.exists(resolved):
            failures.append(f"{relfile}:{lineno} → {target} (no such path)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Resolve relative markdown links.")
    ap.add_argument("--root", default=".", help="Repo root to scan (default: .)")
    ap.add_argument("--paths", nargs="*", default=["*.md", "*.markdown"],
                    help="git pathspecs to discover (default: *.md *.markdown)")
    ap.add_argument("--ignore", action="append", default=[],
                    help="Glob matched against source file path or link target (repeatable)")
    ap.add_argument("--ignore-file", action="append", default=[], dest="ignore_file",
                    help="File of ignore globs, one per line, # comments (repeatable)")
    args = ap.parse_args(argv)

    root = args.root
    root_abs = os.path.abspath(root)
    patterns = load_ignores(root, args.ignore, args.ignore_file)

    try:
        files = tracked_markdown(root, args.paths)
    except subprocess.CalledProcessError as exc:
        print(f"docs-check: `git ls-files` failed in {root!r} — "
              f"is it a git checkout?\n{exc.stderr}", file=sys.stderr)
        return 2

    failures = []
    for relfile in files:
        check_file(root, relfile, root_abs, patterns, failures)

    print(f"docs-check: scanned {len(files)} markdown file(s)"
          f"{f', {len(patterns)} ignore rule(s)' if patterns else ''}")
    if failures:
        print(f"\n{len(failures)} broken relative link(s):\n", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        print("\nFix the target, or — if this is a false positive — add a glob to "
              "`.docs-check-ignore` or the workflow's `ignore:` input.", file=sys.stderr)
        return 1
    print("all relative markdown links resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
