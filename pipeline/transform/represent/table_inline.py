"""TA1 (user request 10-15) — assemble each table region from every engine that recognized it as a table,
and place it *in the body text* where the table actually is, instead of letting the winning (most-accurate)
engine's own, often table-structure-losing, text stand alone while a second, separate "tables_std" grid
sits unused at the end of the document.

Problem this fixes: represent() picks ONE best engine for a whole document by text accuracy. When the best
engine's own table extraction is weak (e.g. pymupdf prints "one cell per line" instead of a grid), the table
rows/columns are lost from rep["text"] — the thing that actually feeds chunks, search evidence and the
published .md — even though some *other* engine (markitdown, office_stdlib, rapidocr_ko, ...) parsed that
same table with a proper grid. table_std.build_tables() already turns a grid into a clean structure, but it
only ever looked at the winning engine's own tables and render_md() appended it at the very end — so the
table showed up twice (once broken, once correct) and never in place.

What this module does, called from represent() once (see hook comment in represent.py for why there):
  (a) candidates = every grid-bearing table from every engine the document was tried with (ok engines only,
      winner + the already-loaded `other_docs`) — not just the winner's.
  (b) group_tables() — tables that are "the same table region" (same page when both sides know the page,
      else matched purely by cell-token overlap) are grouped together.
  (c) choose_grid() — one grid per group wins by a simple, explainable score: non-empty cell ratio
      (completeness — a table TB6 already filled merged/covered cells into is naturally more complete) +
      average cell-token agreement with the other grids in its group. Ties favor engine stack order.
  (d) find_span() — a conservative, order-preserving substring search for the chosen table's cells inside
      the *winning engine's own* body text (that is what ships) — if (almost) all non-empty cell strings can
      be found in order on the table's page, the span from the first to the last match is the table's text
      region; otherwise nothing is touched (recorded as unmatched, never guessed).
  (e) the matched span is replaced with a GitHub-markdown table rendered from the chosen grid
      (table_std.to_markdown — reused, not reimplemented) — unmatched tables are left alone in the text.
  (f) rep["tables_std"] is rebuilt from the *chosen* grids (table_std.build_tables, same shape as before,
      "source_engine" = whichever engine's grid won) with an added "inline" flag so render_md() knows not to
      append it again.

Merged cells: engines already fill covered (rowspan/colspan) cells with the origin value before this module
ever sees the grid (TB6, PARSE_FILL_MERGED, _common/contract._fill_merged) — some engines also carry an
explicit `merges` list (office_stdlib/anydoc), others (pymupdf/pdfplumber) do not and only leave the filled
duplicates behind. reading_order_cells() below works either way (see its docstring) by detecting fill
duplicates positionally instead of depending on `merges` being present.
"""

from collections import Counter

from common.core.text import normalize_value
from pipeline.transform.represent import table_std

GROUP_JACCARD_MIN = 0.5  # ponytail: simple fixed threshold for "same table region" by content overlap when
# page can't settle it — revisit with a real mis-grouped example before tuning further.
MATCH_MIN_CELLS = 3  # tables with fewer non-empty cells are too easy to "find" by accident anywhere in free text.
MATCH_MIN_RATIO = 0.9  # "(almost) all" cells, per spec — conservative: leave text alone rather than guess.
GAP_MAX_CHARS = 20  # real-world regression (synth-wmf wmf_two_figs.docx, TA1 measure pass) — a short, common
# cell string (e.g. "장비") can also occur earlier in an unrelated sentence/title; without
# a per-gap bound, find_span happily jumped from that decoy match all the way to the
# table's real location and swallowed every paragraph in between. Cells inside one real
# table are packed closely (one line, or a few words apart) — a gap this wide between two
# consecutive *accepted* matches means the earlier one was a decoy, not part of this table.
SPAN_SLACK_CHARS = 200  # fixed slack added to the cell-length budget below, so a short table (little total
# cell text) with one or two skipped/out-of-order cells still passes the ratio check.
SPAN_SLACK_RATIO = 4  # matched span must not be more than this many times the matched cells' own length —
# guards against an accidental match swallowing unrelated surrounding paragraphs.


def _cell_str(c):
    return str(c if c is not None else "").strip()


def reading_order_cells(grid):
    """Row-major non-empty cell strings, collapsing the duplicates TB6's merge-fill (_fill_merged) leaves
    behind: a cell equal to its immediate left neighbor (colspan fill, copied left-to-right) or to the cell
    directly above it (rowspan fill, copied top-to-bottom) is treated as a filled duplicate, not a second
    real cell — this is exactly the fill order _fill_merged uses, so it reverses cleanly. Works whether or
    not the table carries an explicit `merges` list (pymupdf/pdfplumber grids never do; office_stdlib/anydoc
    grids do, but this function does not need it).
    A real, independent cell that *happens* to repeat its neighbor's text (coincidence, not a merge) can be
    under-counted here — that only drops one target from the span-matching list (find_span, below), it never
    causes a wrong replacement; being lenient this way is intentionally conservative in the safe direction."""
    out = []
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            s = _cell_str(cell)
            if not s:
                continue
            left = _cell_str(row[c - 1]) if c > 0 else ""
            above = _cell_str(grid[r - 1][c]) if r > 0 and c < len(grid[r - 1]) else ""
            if s == left or s == above:
                continue
            out.append(s)
    return out


def _token_set(grid):
    return {t for t in (normalize_value(_cell_str(c)) for row in grid for c in row) if t}


def _jaccard(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def group_tables(candidates):
    """candidates: [{"engine", "table", "grid"(padded), "tokens", "page"}, ...] from every ok engine's own
    `tables` (grid-bearing ones only — gridless tables, same as table_std, are left out entirely: there is
    no structure to score or inline). Returns a list of groups (each a list of candidates) — two candidates
    join the same group when either their page numbers agree (both known, same number) or at least one side
    doesn't know its page, AND their normalized cell-token sets overlap by >= GROUP_JACCARD_MIN (Jaccard).
    Simple greedy pass (compare against each group's first member) — good enough for the handful of tables
    a real document has; not meant for documents with hundreds of near-identical tables."""
    groups = []
    for cand in candidates:
        placed = False
        for g in groups:
            head = g[0]
            same_page = head["page"] is not None and cand["page"] is not None and head["page"] == cand["page"]
            page_unknown = head["page"] is None or cand["page"] is None
            if (same_page or page_unknown) and _jaccard(cand["tokens"], head["tokens"]) >= GROUP_JACCARD_MIN:
                g.append(cand)
                placed = True
                break
        if not placed:
            groups.append([cand])
    return groups


def choose_grid(group):
    """One grid per group — score = 0.5*completeness (non-empty cell ratio; TB6 merge-fill already pushes
    this up for tables with real merged cells) + 0.5*agreement (average cell-token Jaccard with the group's
    other grids — how much the other engines that also saw this table "agree" with this one). Ties keep the
    group's original (stack/engine-loop) order. Returns (chosen_candidate, score_record)."""
    scored = []
    for cand in group:
        total = sum(len(row) for row in cand["grid"])
        nonempty = sum(1 for row in cand["grid"] for c in row if _cell_str(c))
        completeness = (nonempty / total) if total else 0.0
        others = [o["tokens"] for o in group if o is not cand]
        agreement = (sum(_jaccard(cand["tokens"], o) for o in others) / len(others)) if others else 1.0
        score = round(0.5 * completeness + 0.5 * agreement, 4)
        scored.append({"engine": cand["engine"], "score": score, "completeness": round(completeness, 4), "agreement": round(agreement, 4)})
    best_i = max(range(len(group)), key=lambda i: scored[i]["score"])
    return group[best_i], {"chosen": scored[best_i]["engine"], "candidates": scored}


def _page_slice(text, page):
    """Narrow `text` to its 1-based `page` (split on \\f, same page-break convention as the rest of
    represent.py) when the page number is known and in range — otherwise search the whole text (unknown page,
    or a page count that doesn't line up with the \\f breaks; same "don't guess boundaries" posture as
    represent._page_texts, just without needing boxes here). Returns (offset, slice)."""
    if page is None:
        return 0, text
    pages = text.split("\f")
    if page < 1 or page > len(pages):
        return 0, text
    offset = sum(len(p) + 1 for p in pages[: page - 1])
    return offset, pages[page - 1]


MAX_ANCHOR_TRIES = 50  # ponytail: cap on how many occurrences of the first cell we try as a start — plenty for
# any real document, just a safety bound against a pathological one repeating it hundreds of times.


def _walk(hay, cells, anchor):
    """Starting from `cells[0]` already found at `anchor`, walk the rest of `cells` in order with the same
    gap rule as find_span (below): a cell found more than GAP_MAX_CHARS past the last *accepted* one is
    treated as not found this round (not counted, search position not advanced to it). Returns
    (matched_count, matched_char_len, start, end, bounds) — bounds is the (start, end) pair for every
    *accepted* cell in order, used by find_span to recover any real text sitting in the gaps between them."""
    pos = anchor + len(cells[0])
    start, end, matched, matched_len = anchor, pos, 1, len(cells[0])
    bounds = [(anchor, pos)]
    for cell in cells[1:]:
        idx = hay.find(cell, pos)
        if idx == -1:
            continue
        if idx - end > GAP_MAX_CHARS:
            continue  # too far from the last accepted cell — likely a decoy match, not this table
        matched += 1
        matched_len += len(cell)
        end = idx + len(cell)
        pos = end
        bounds.append((idx, end))
    return matched, matched_len, start, end, bounds


_TABLE_PUNCT = set(" \t\r\n|-–—·•:")  # whitespace + common table/decorative separators ("|", dashes, middots,
# ":") — ignored when judging whether text sitting between two matched
# cells is real content (a footnote) or just layout glue.


def _gap_residues(hay, bounds):
    """Review item 5 (engine-qa, 10-21) — GAP_MAX_CHARS lets up to that many characters between two matched
    cells ride along inside the replaced span; most of the time that is just whitespace/newlines, but it can
    be a short caption or footnote that would otherwise be silently deleted. Returns the stripped text of
    every gap between consecutive *accepted* cells (bounds, from _walk) that is not empty and is not made up
    only of `_TABLE_PUNCT` — i.e. the residue text find_span's caller must keep, in original order."""
    out = []
    for (_, prev_end), (next_start, _) in zip(bounds, bounds[1:]):
        gap = hay[prev_end:next_start].strip()
        if gap and (set(gap) - _TABLE_PUNCT):
            out.append(gap)
    return out


def find_span(text, page, cells):
    """Conservative, order-preserving search for `cells` (reading_order_cells of the winning grid) inside
    the (page-scoped, see _page_slice) text. The first cell can be a short, common string that also occurs
    earlier in an unrelated sentence/title (real example: a doc titled "Equipment Checklist ..." whose table
    also starts with the word "Equipment") — trying every occurrence of cells[0] as a start (_walk, capped at
    MAX_ANCHOR_TRIES) and keeping whichever start matches the most cells is what tells the real table's start
    from that kind of decoy, instead of latching onto the first (wrong) occurrence and then rejecting every
    cell after it because they all look "too far" from that wrong anchor. Returns (start, end, residues) —
    start/end are absolute offsets into `text` covering the first matched cell through the last for the
    best-scoring start, residues is the list of non-trivial gap text (see _gap_residues) the caller must not
    drop when it replaces that span — or None if too few cells matched there (ratio or absolute count) or the
    span is still implausibly loose (secondary guard against a decoy start that still "wins" by having the
    most, but still too few, matches)."""
    if len(cells) < MATCH_MIN_CELLS:
        return None
    offset, hay = _page_slice(text, page)
    best, search_from, tries = None, 0, 0
    while tries < MAX_ANCHOR_TRIES:
        anchor = hay.find(cells[0], search_from)
        if anchor == -1:
            break
        tries += 1
        result = _walk(hay, cells, anchor)
        if best is None or result[0] > best[0]:
            best = result
        search_from = anchor + 1
    if best is None:
        return None
    matched, matched_len, start, end, bounds = best
    if matched < MATCH_MIN_CELLS or matched / len(cells) < MATCH_MIN_RATIO:
        return None
    if (end - start) > matched_len * SPAN_SLACK_RATIO + SPAN_SLACK_CHARS:
        return None
    return offset + start, offset + end, _gap_residues(hay, bounds)


def _build_candidates(rep, best_engine, other_docs):
    cands = []
    for engine, doc in [(best_engine, rep), *other_docs.items()]:
        for t in doc.get("tables") or []:
            grid = t.get("grid")
            if not grid:
                continue  # no structure to group/score/inline — same rule table_std already uses
            padded = table_std._pad(grid)
            cands.append({"engine": engine, "table": t, "grid": padded, "tokens": _token_set(padded), "page": t.get("page")})
    return cands


def inline_tables(rep, best_engine, other_docs):
    """Entry point (represent() calls this — see the hook comment in represent.py for where/why).
    Mutates rep["text"] in place (span replacements only — nothing else about the text changes) and sets
    rep["tables_std"]. Returns the info block for rep["rep"]["table_inline"].
    Review item 5 (engine-qa, 10-21) — a replaced span can contain a short caption/footnote squeezed between
    two matched cells (within GAP_MAX_CHARS); that text is kept, not dropped. It is put as plain line(s)
    right after the markdown table, in the order it appeared — appending (not e.g. dropping the whole table
    to be safe) is the one deterministic place for it: the table's own cell order is already settled by the
    chosen grid, so there is no ambiguous "where exactly inside the table" to reinsert free text into, but
    "right after, in original order" needs no judgment call and never reorders anything else in the document."""
    candidates = _build_candidates(rep, best_engine, other_docs)
    if not candidates:
        return {"on": True, "groups": 0, "inlined": 0, "unmatched": 0, "sources": {}, "residue": 0}

    text = rep.get("text") or ""
    groups = group_tables(candidates)
    replacements, built, sources, unmatched, residue_n = [], [], Counter(), 0, 0
    taken = []  # already-claimed (start, end) ranges — guards against two groups fighting over the same text
    for group in groups:
        chosen, _score = choose_grid(group)
        sources[chosen["engine"]] += 1
        match_cand = next((c for c in group if c["engine"] == best_engine), chosen)
        cells = reading_order_cells(match_cand["grid"])
        span = find_span(text, match_cand["table"].get("page"), cells)
        if span and any(not (span[1] <= s or span[0] >= e) for s, e in taken):
            span = None  # overlap with an already-placed table — conservative: don't touch it either
        entry = table_std.build_tables([chosen["table"]], chosen["engine"])
        entry = entry[0] if entry else None
        inline_ok = bool(span and entry)
        if inline_ok:
            start, end, residues = span
            known = {normalize_value(c) for row in ([entry["header"]] + entry["rows"]) for c in row}
            residues = [r for r in residues if normalize_value(r) not in known]  # real example (merged_table.pdf,
            # synth-realpat): reading_order_cells' merge-dedup heuristic can under-count a genuinely repeated cell
            # (e.g. a batch id that legitimately appears twice, not from a merge) and leave it unmatched in a gap —
            # that text is still a duplicate of a cell already shown in the table, not lost information, so it is
            # dropped here rather than appended as a confusing stray line; only residue text that matches none of
            # the table's own cells is kept (a real caption/footnote would not match any cell).
            md = table_std.to_markdown(entry)
            if residues:
                md = md + "\n\n" + "\n".join(residues)  # blank line required — GFM reads lines up to a blank line as table rows (fb review)
                residue_n += len(residues)
            replacements.append((start, end, md))
            taken.append((start, end))
        else:
            unmatched += 1
        if entry is not None:
            entry["inline"] = inline_ok
            built.append(entry)

    for start, end, md in sorted(replacements, key=lambda r: -r[0]):
        text = text[:start] + md + text[end:]
    rep["text"] = text
    for i, entry in enumerate(built):
        entry["id"] = f"t{i}"
    rep["tables_std"] = built

    return {
        "on": True,
        "groups": len(groups),
        "inlined": len(groups) - unmatched,
        "unmatched": unmatched,
        "sources": dict(sources),
        "residue": residue_n,
    }
