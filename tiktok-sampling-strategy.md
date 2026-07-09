# TikTok Video Sampling Strategy for Content Extraction — v2

**Status:** Implemented. Backtest notebook: `notebook/tiktok_sampling_strategy_v2.ipynb` (built from `notebook/build_notebook_v2.py`). Dashboard export: `data/dashboard/` (see `data/dashboard/README.md` for the column-level data dictionary).
**Supersedes:** `tiktok-sampling-strategy-proposal.md` (v1) — this document keeps v1's core philosophy (budget-constrained sampling, multi-metric coverage scorecard, backtest-first evaluation) but replaces its universe definition, method set, and metric design with a version grounded in the actual multi-country / BPC-aware dataset now available.
**Author's note:** every quantitative claim in this document (row counts, correlations, cell sizes, etc.) was verified directly against the data files listed in Section 2, not assumed from the source schema. Numbers are as of the 2026-06-27 TCC snapshot. This document is kept in sync with the notebook as it evolves — where the two diverge, the notebook is the source of truth for what actually ran; this document explains *why*.

---

## 1. Overview

### 1.1 Background

Paragon runs a content-extraction pipeline that uses an LLM (Gemini Flash) to watch TikTok videos and extract structured attributes (hook type, content format, claim type, visual style, etc.). This structured data is the foundation for trend analysis and, eventually, relevance scoring against Beauty & Personal Care (BPC) content — internally referred to as **BPC vs Non-BPC**.

Source videos come from TikTok Creative Center (TCC), which publishes trending-hashtag leaderboards and the videos associated with them, across four Southeast Asian markets: **Indonesia (ID), Malaysia (MY), the Philippines (PH), and Thailand (TH)**.

### 1.2 Problem Statement

Watching a video with Gemini Flash costs approximately **Rp200/video**. Running this against the full TCC universe every week is cost-prohibitive. The problem decomposes into three parts, unchanged from v1:

1. **Cost constraint** — a hard ceiling on how many videos can be watched per run.
2. **Volume & selection problem** — how to choose the most representative subset of videos from a much larger population.
3. **Evaluation problem** — how to compare sampling mechanisms objectively, on equal footing (same budget).

### 1.3 Objective

Design and backtest several sampling mechanisms, compare them via a coverage scorecard on identical budget, and produce a recommendation-ready comparison for the data & marketing teams. **No single method is selected in this document** — that decision is deferred to a later stage, after this backtest is reviewed.

### 1.4 What Changed from v1

v1 was a single-country, single-hashtag-universe proof of concept with no BPC awareness (BPC selection was explicitly deferred as a "chicken-and-egg" problem: BPC relevance can only be known after a video is watched, but watching is the very thing we're trying to ration). Since v1, three things changed:

1. **A hashtag-level BPC signal now exists** (`HASHTAG_TYPE` = `BEAUTY` / `NON BEAUTY`) that requires no content tagging. This breaks part of the circularity — we can bias sampling toward BPC-relevant hashtags without having watched a single video.
2. **The business has defined a fixed allocation rule**: 50% of budget to Indonesia (remainder split across TH/MY/PH), and 80% of budget to Beauty content. This is now a hard constraint on the sampler, not just a metric to observe.
3. **The scoring data is richer** — the combined trending/virality file carries growth, engagement, and reach sub-scores that didn't exist in v1's raw TCC export, enabling better cross-checks.

---

## 2. Data Sources

| File | Rows (relevant snapshot) | Grain | Role |
|---|---|---|---|
| `data/processed/tiktok-video_combined_score_20260627.csv` | 13,143 videos | 1 row / video | Defines the video universe; carries `trending_score`, `virality_score` (= **emerging_score** in v1 terminology — see note below), ranks, and derived growth/engagement features |
| `data/hashtag/hashtag_to_video.csv` | ~1.64M rows across 9 extract dates | 1 row / (video, hashtag, country) per date | Bridges video ↔ hashtag |
| `data/hashtag/hashtag_overview.csv` | ~173K rows across 10 extract dates | 1 row / (hashtag, country, category) per date | Hashtag performance & ranking — the ranking source for two of the six sampling methods |
| `data/user/tiktok-user_detail_20260626.csv` | 11,918 users | 1 row / username | Creator metadata (followers/following/likes) — not required for the core pipeline, retained for optional creator-tier breakdowns |

**Terminology note:** per project convention, **`virality_score` = "emerging_score"** used in v1's language. Both terms refer to the same TCC field; this document uses `virality_score` throughout since that's the actual column name in the current data.

### 2.1 Video universe (`tiktok-video_combined_score_20260627.csv`)

13,143 unique videos, uploaded between 2026-06-10 and 2026-06-22, scored as of the 2026-06-27 TCC snapshot. Columns of note beyond `trending_score`/`virality_score`: `trending_rank`, `virality_rank`, `view_velocity`, `views_growth_short`, `views_growth_long`, `reach_ratio`, `c1`–`c4` composite sub-scores. These are richer than v1's raw 3-day view deltas; they were used for a raw-growth-signal cross-check against `trending_score`/`virality_score` in an earlier notebook iteration (see Appendix A), and remain available in the dashboard export (`selected_videos.csv`) if that check is needed again.

### 2.2 Hashtag-to-video mapping (`hashtag_to_video.csv`)

Covers **9 extract dates**: 2026-06-20 through 06-27, and 06-29 (06-28 is missing from the source entirely). Columns: `COUNTRY_CODE, CATEGORY_NAME, HASHTAG_ID, HASHTAG_NAME, HASHTAG_TYPE, DATA_EXTRACT_DATE, VIDEO_ID, SHARE_URL`. **No rank information lives in this file** — it is purely a membership table (which videos belong to which hashtag).

**Known data-quality issue (same class of bug as v1):** `VIDEO_ID` contains at least one corrupted row where a video ID string got concatenated with a country code, which — if the column is read without forcing string dtype first — silently coerces the whole column to `float64` and destroys precision on 19-digit video IDs. Fix: read as string, strip malformed rows (length check), cast to `int64` only after cleaning.

**Date-filtering finding (material to the design):** if this file is filtered to the single date 2026-06-27 (to match the video snapshot), only **22% of the video universe** (2,959 / 13,143) resolves to any hashtag. Filtered across **all 9 available dates**, resolution reaches **100%**. This means the mapping is cumulative/rolling, not a daily-refreshed 1:1 snapshot — **the union across dates must be used** for video↔hashtag membership, or 78% of the universe becomes artificially unreachable.

### 2.3 Hashtag overview (`hashtag_overview.csv`) — the ranking source

Covers **10 extract dates**: 2026-06-20 through 06-27, 06-29, 06-30 (06-28 missing here too). On **2026-06-27** specifically — the date pinned as the ranking snapshot for this design — there are **16,713 hashtag×country rows**, which is within 8% of the 10-day average (16,700–18,192); i.e., **this file is not sparse on 27 June**, unlike the mapping file above.

Two ranking fields, verified against the data to have distinct partition scopes:

| Field | Partition (verified empirically) | Range | Notes |
|---|---|---|---|
| `RANK_POSITION_NUMBER` | `(COUNTRY_CODE, CATEGORY_NAME, DATA_EXTRACT_DATE)` | 1–200 (hard cap) | TCC's own per-category leaderboard rank. Resets per category, so "top-K by this field" is inherently category-balanced. |
| `RANKING` | `(HASHTAG_TYPE, COUNTRY_CODE, DATA_EXTRACT_DATE)` | 1–5,805 (no cap) | Matches the SQL definition supplied by the user: `ROW_NUMBER() OVER (PARTITION BY hashtag_type, country_code, data_extract_date ORDER BY view_count DESC, rank_change_number DESC, post_count DESC)`. Spans **all categories** within a country+type — the natural ranking field for the BPC/country quota cells defined in Section 3. |

`HASHTAG_TYPE` takes only two values: `BEAUTY` (1,010 hashtag×country rows on 2026-06-27, **6.04%** of that day's universe) and `NON BEAUTY` (the remaining 93.96%). `CATEGORY_NAME` has 61 distinct values overall, but **only 4 of them fall under `BEAUTY`** (`HAIR_CARE`, `BEAUTY`, `BEAUTY_SERVICES`, `OTHER_BEAUTY`) — the remaining 57 are all `NON BEAUTY`. This asymmetry has direct consequences for the Category Balance metric (Section 6.1).

Same-hashtag rank instability across dates is expected and confirmed (e.g. hashtag "juhoon" in ID/ENTERTAINMENT_AND_SPORTS_NEWS moved `RANK_POSITION_NUMBER` 236→232→166→...→90 across 10 consecutive days) — this is exactly what `RANK_CHANGE_NUMBER` is designed to track. **This is why the ranking source must be pinned to a single date (2026-06-27)** rather than unioned like the mapping file — unioning would mix a hashtag's rank on multiple different days into one selection pass, which is not well-defined.

### 2.4 User detail (`tiktok-user_detail_20260626.csv`)

11,918 rows keyed by `username` (there is no numeric creator ID in either this file or the combined-score file — `uploader` in the video file is a username string). Retained as an optional join for creator-tier breakdowns; not required for the core metric set.

### 2.5 Country is a property of the (video, hashtag) edge, not of the video

83% of videos (10,968 / 13,143) appear under hashtags from **more than one country**. A video is not intrinsically "Indonesian" or "Thai" — it becomes associated with a country only through the hashtags it's tagged under. Section 3 defines a deterministic rule to collapse this into a single country per video for quota purposes.

---

## 3. Universe Definition

### 3.1 Effective universe

Starting from the 13,143-video combined-score universe, restrict to videos that have **at least one hashtag edge landing on a hashtag present in `hashtag_overview.csv` on the pinned date (2026-06-27)** — this is required because country/type/rank assignment (Section 3.2) depends on that file. Empirically:

- **10,196 / 13,143 videos (78%) are eligible** and form the effective universe used for all six methods, including Random.
- **2,947 videos (22%) are excluded** — their only hashtag associations point to hashtags that don't appear in the 27-June leaderboard (likely because TCC's per-category leaderboard is capped at the top 200, or the hashtag only ranked on a different day). This is a shortcoming of using a single pinned date for ranking, accepted as a limitation of this backtest snapshot (see Section 8) rather than worked around with a fallback date-window, per the decision to keep the ranking snapshot unambiguous.

All budget, method, and metric definitions below operate on this **10,196-video effective universe**.

### 3.2 Video → cell assignment (Country × BPC Type)

Every video in the effective universe is assigned to exactly one of **8 cells** — `{ID, MY, PH, TH} × {BEAUTY, NON BEAUTY}` — via a two-step deterministic rule:

1. **Type assignment:** a video is labeled `BEAUTY` if **any** of its hashtag edges has `HASHTAG_TYPE = BEAUTY`; otherwise `NON BEAUTY`. This is an inclusive-OR rule, not a "best" rule — a single beauty hashtag is enough to flag a video as BPC-relevant, consistent with the business's priority on not missing BPC content.
2. **Country assignment:** among the video's edges that match its assigned type (from step 1), pick the edge with the **lowest `RANKING`** value; the video is assigned to that edge's `COUNTRY_CODE`. `RANKING` (not `RANK_POSITION_NUMBER`) is used here because it is comparable across categories within a country+type — `RANK_POSITION_NUMBER` resets per category and is not a valid basis for cross-category comparison.

Videos that resolve to zero same-type edges cannot occur by construction (type assignment guarantees at least one qualifying edge exists for country assignment).

**Interesting empirical note:** although `BEAUTY` hashtags are only 6% of the hashtag population, the inclusive-OR video-level rule produces a near-even split: **5,089 videos (50%) assigned BEAUTY, 5,107 (50%) NON BEAUTY**. A small number of highly-connected beauty hashtags touch a disproportionately large slice of the video universe. This means the 80/20 budget quota (Section 4) is a ~1.6× oversample relative to the natural video-level BPC split (50/50) — a more moderate oversample than the 13× figure implied by the hashtag-population share, though still a deliberate, business-driven skew that should be labeled as such in any report.

### 3.3 Empirical cell sizes (videos assigned per cell)

| Country | Beauty | Non-Beauty | Total |
|---|---:|---:|---:|
| ID | 1,379 | 1,716 | 3,095 |
| MY | 1,368 | 1,091 | 2,459 |
| PH | 1,409 | 1,426 | 2,835 |
| TH | 933 | 874 | 1,807 |
| **Total** | **5,089** | **5,107** | **10,196** |

---

## 4. Budget & Quota Design

### 4.1 Fixed business rule (input, not derived)

- **Country split:** 50% Indonesia; remaining 50% split evenly across TH/MY/PH (16.67% each).
- **Type split:** 80% Beauty, 20% Non-Beauty.
- **Crossing:** the two splits are applied as an independent 2D cross (country share × type share) to form 8 quota cells, not sequentially or via a blended weight.
- **Cost model:** unchanged from v1 — Rp200/video, counted per unique video regardless of how many hashtags it satisfies.
- **Total budget:** default **2,000 videos** (~19.6% of the 10,196-video effective universe), carried over from v1 for continuity. This is a parameter, not a fixed law — see the feasibility ceiling below before raising it.

### 4.2 Crossed allocation table (at total budget = 2,000)

| Cell | Share of budget | Target video count |
|---|---:|---:|
| ID – Beauty | 50% × 80% = 40.00% | 800 |
| ID – Non-Beauty | 50% × 20% = 10.00% | 200 |
| MY – Beauty | 16.67% × 80% = 13.33% | 267 |
| MY – Non-Beauty | 16.67% × 20% = 3.33% | 67 |
| PH – Beauty | 16.67% × 80% = 13.33% | 267 |
| PH – Non-Beauty | 16.67% × 20% = 3.33% | 67 |
| TH – Beauty | 16.67% × 80% = 13.33% | 267 |
| TH – Non-Beauty | 16.67% × 20% = 3.33% | 67 |

(Percentages of 267/67 are rounded; the implementation must use the **largest-remainder method** — same helper as v1 — to make the 8 cell targets sum to exactly 2,000, not a naive rounding that could drift by ±1-2 videos.)

### 4.3 Feasibility ceiling

Every cell's target is comfortably below its available population at budget = 2,000 (largest penetration: ID-Beauty at 58%, target 800 of 1,379 available). However, the **80% Beauty quota bounds how far total budget can scale**: total Beauty demand is `0.8 × total_budget`, and the hard ceiling is the smaller of each country's available Beauty pool divided by its share of the Beauty quota. The binding constraint is **ID-Beauty**: `1,379 available ÷ 40% share ≈ 3,447`. Above roughly **3,400 total budget**, the quota as specified becomes infeasible without either relaxing the 80/20 split or extracting every single ID-tagged Beauty video with no headroom left for method differentiation. This ceiling should be documented alongside any future budget increase discussion.

---

## 5. Sampling Methods

### 5.1 Common mechanics

All six methods are run **independently within each of the 8 cells**, using that cell's sub-budget from Section 4.2 and a sub-universe restricted to:

- hashtags whose own `(COUNTRY_CODE, HASHTAG_TYPE)` matches the cell, **and**
- videos whose cell assignment (Section 3.2) matches the cell.

Because every video belongs to exactly one cell, the eight per-cell result sets are **disjoint by construction** — the final selection for a method is simply their union, with no deduplication logic required across cells. (Deduplication *within* a cell is still needed for methods that touch a video through multiple hashtags — see Section 5.2.)

**Consequence to flag:** a hashtag's "available video pool" inside its own cell is not simply its raw `hashtag_to_video.csv` linkage count — it's that count *after* excluding videos whose overall cell assignment resolved elsewhere (because a better-ranked edge of the same type pulled them into a different country). Some hashtags will have a smaller effective pool than their raw linkage suggests; this is expected, not a bug.

### 5.2 Shared helper functions (carried over from v1, unchanged in logic)

```
top_up(selected: set, budget: int, ranked_pool: list) -> set
    # Fills remaining budget from the next-best ranked candidates not yet selected.
    # Used whenever natural dedup leaves a method under its cell's target.

largest_remainder(weights: Series, total: int) -> Series
    # Allocates an integer budget across weighted buckets so the total matches
    # exactly, instead of naive rounding. Used for: (a) the 8-cell budget split,
    # (b) proportional allocation inside cells for Methods 1 and (optionally) 3-6.
```

### 5.3 Method definitions

**A note on numbering:** the method IDs below skip **M6** on purpose. An early draft included a sixth top-K-per-hashtag variant ranked by raw `view_count`; it was dropped after review (Section 8, limitation 7) because it added the least differentiated signal of the four score-based variants and skewed hardest toward already-established content. Rather than renumber M7 (Random) down to M6, the gap is kept — M7 stays M7 everywhere, including the dashboard export, so labels never silently shift meaning between notebook versions.

**Method 1 — Broad hashtag selection by `RANK_POSITION_NUMBER`, extract all videos**

Within a cell, select the top-K hashtags **per category present in that cell** (K found iteratively so the union of "all videos of selected hashtags" stays within the cell's budget, then `top_up` fills any shortfall). Because `RANK_POSITION_NUMBER` resets per category, this mechanically guarantees category breadth within the cell.

*Implication:* in the Beauty cells (only 4 categories), this ceiling on achievable category breadth is structurally low — not a method weakness, just the size of the available category space (see Section 6.1's normalization fix). In Non-Beauty cells (57 categories), the same mechanism spreads much more thinly.

**Method 2 — Narrow hashtag selection by `RANKING`, extract all videos**

Within a cell, select the top-N hashtags **by `RANKING`, across all categories in the cell** (N found the same way, `top_up` for shortfall). `RANKING`'s partition already matches the cell definition exactly, so no further grouping is needed.

*Implication:* this is the direct complement of Method 1 — no forced category spread, so if the top-ranked hashtag in a cell happens to have hundreds of linked videos, it alone can consume most of a small cell's budget (e.g. TH-Beauty, target 267). The number of *hashtags* actually touched per cell must be reported alongside video count, since a "successful" 267-video fill could come from just 1–2 hashtags.

**Methods 3–5 — Top-K video per hashtag, for every hashtag in the cell, ranked by:**

| Method | Ranking signal | Behavioral note |
|---|---|---|
| 3 | `virality_score` (= emerging score) | Skews toward videos with strong relative growth signal; risk of surfacing low-absolute-reach videos with a temporary spike. |
| 4 | `trending_score` | A composite of performance + growth + topic popularity + momentum sub-scores; skews toward content that is both already large *and* still gaining — less exploratory than Method 3. |
| 5 | Average of `trending_score` and `virality_score` | A blended, lower-variance middle ground; less diagnostic on its own but useful as a stability check against 3 and 4. |

K is found the same way as Method 1 (iterative search for the union across *all* hashtags in the cell to stay within budget, plus `top_up`).

*Correlation check (run against the full 13,143-video universe, Spearman):*

| | trending_score | virality_score |
|---|---:|---:|
| trending_score | 1.00 | 0.47 |
| virality_score | 0.47 | 1.00 |

The two underlying signals correlate only moderately (0.47), not highly — confirming Methods 3 and 4 will produce meaningfully different selections rather than near-duplicate outputs, and that Method 5's average is a genuine blend rather than redundant with either input. (A fourth variant ranked by raw `view_count` was tested during design and correlated similarly weakly with both — 0.51 with `trending_score`, 0.44 with `virality_score` — but was dropped for the reasons in Section 5.3's numbering note above, not because it was redundant.)

**Method 7 — Random baseline**

Uniform draw without replacement from each cell's eligible video pool, sized to the cell's target — **still inside the quota structure**, not a fully unconstrained random draw from the whole universe. This is a deliberate choice: it isolates the *within-cell selection mechanism* as the only variable being tested, since the quota itself is a fixed business input applied identically everywhere.

*Consequence:* because all six methods share the same country/type quota by construction, **Country Balance and Beauty/Non-Beauty share will be near-identical across all six methods** — these are not differentiators and should not appear in the core radar/scorecard (see Section 6.2).

---

## 6. Coverage Metrics

Every metric below is computed **per cell first**, then aggregated (Section 6.4).

### 6.1 Core scorecard (7 metrics)

| # | Metric | Definition | What changed from v1 |
|---|---|---|---|
| 1 | **Coverage Ratio** | Mean, over hashtags in the cell, of (Σ views of selected videos in that hashtag ÷ hashtag's `VIEW_COUNT`) | Unchanged formula; now computed per cell before aggregation. |
| 2 | **Breadth Coverage** | Distinct hashtags touched by the selection, within the cell, ÷ total hashtags available in that cell | Unchanged formula; reported per cell (98 hashtags in TH-Beauty behaves very differently from 5,805 in PH-Non-Beauty — pooling would hide this). |
| 3 | **Category Balance** | Shannon entropy of the selected videos' `primary_category` distribution within the cell (one vote per video), normalized by `log(N_categories_in_that_type)` | **Normalizer changed**: `log(4)` for Beauty cells, `log(57)` for Non-Beauty cells — not a single global `log(61)`. **Counting unit corrected**: an early implementation counted every hashtag edge a video touched (so a video linked to 3 in-cell hashtags cast 3 votes, possibly across categories); this was changed to one vote per selected video via its `primary_category`, for consistency with how Creator Diversity counts videos. See worked example below. |
| 4 | **Creator Diversity** | Shannon entropy of selected videos' `uploader` distribution, normalized by `log(unique uploaders in the cell)` | Keyed on `uploader` (username) since no numeric creator ID exists in this dataset; 10,686 unique uploaders across 13,143 videos (1.23 videos/uploader) confirms this is granular enough. |
| 5a/5b | **Trend-stage Balance** (split into two numbers) | (a) mean `trending_score` of sample ÷ mean `trending_score` of the cell; (b) same for `virality_score` | **Split, not averaged**, because the two scores correlate only moderately (0.47) — averaging them can mask a method that overshoots on one axis and undershoots on the other (see worked example below). |
| 6 | **Long-tail / Novelty Coverage** | % of selected videos whose best-ranked hashtag sits outside the top 50th percentile *within its own category* | **Redefined from v1's absolute `RANK_POSITION_NUMBER > 20`** — that threshold doesn't transfer here because the field is capped at 200 and category sizes vary enormously; a relative, category-scoped percentile is required for fairness. |
| 7 | **Fill Rate** | Videos actually selected in the cell ÷ the cell's target from Section 4.2 | New — needed because Methods 1–2 (extract-all) can under-fill a small cell, while 3–5 and Random will almost always hit their target exactly. Without this, an under-filled cell could make other ratio metrics look artificially favorable. |

**Category Balance, worked example.** Say a method selects 800 videos in ID-Beauty (4 possible categories), and each selected video's `primary_category` breaks down as:

| Category | Videos | Share |
|---|---:|---:|
| `HAIR_CARE` | 400 | 0.50 |
| `BEAUTY` | 240 | 0.30 |
| `BEAUTY_SERVICES` | 120 | 0.15 |
| `OTHER_BEAUTY` | 40 | 0.05 |

$H = -\sum p_i \ln p_i = 1.142$. Divide by $\ln(4) = 1.386$ → **category_balance ≈ 0.82**. A perfectly even 25/25/25/25 split would score 1.00; everything landing in one category would score 0.00. This is *not* the same thing as Breadth Coverage — a method can touch every category available and still score low here if it dumps most of its budget into one of them.

**Why entropy / `log`, and why per-cell normalizers:** Shannon entropy $H = -\sum p_i \log p_i$ measures evenness, not just "how many categories were touched" (that's Breadth Coverage). Its maximum value is mathematically $\log(N)$ when the distribution is perfectly even across $N$ categories — so dividing by $\log(N)$ rescales entropy to 0–1, where 1.0 means "as even as structurally possible." Using a single global $\log(61)$ for both cell types would cap Beauty cells at a maximum achievable score of $\log(4)/\log(61) \approx 0.34$ *even in the best possible case* — making Beauty look permanently worse at "balance" for a reason that has nothing to do with method quality. Normalizing each cell type by its own category count fixes this.

**Creator Diversity is not the same thing as "how many creators did we reach."** A metric like *(distinct creators in the sample ÷ distinct creators in the cell's universe)* would measure reach — closer in spirit to Breadth Coverage, but for creators instead of hashtags. Creator Diversity instead measures **concentration**: 800 selected videos from 800 different creators (1 each) scores close to 1.0; 800 videos where one prolific creator contributes 200 of them scores much lower, even though the *count* of distinct creators reached might be identical to some other, more evenly-spread selection. The reach-style ratio can't tell those two scenarios apart; entropy can.

**Long-tail is a property of the video, not of the method that selected it.** The rank used is always TCC's own `RANK_POSITION_NUMBER` — never a method's internal ranking signal (not M2's `RANKING`, not M3-5's scores). For each video: take every in-cell hashtag edge, convert its `RANK_POSITION_NUMBER` to a percentile within its own `(country, category)` group, and keep the *best* (lowest) percentile across all of that video's edges. The video is flagged long-tail if even its best hashtag sits outside the top 50th percentile of its own category. This value is fixed per `video_id` — it doesn't change depending on which of the six methods happened to select that video. What *does* vary by method is simply what fraction of *that method's* selected set happens to be long-tail by this shared yardstick.

**Why Trend-stage Balance is split:** "trend-stage" refers to a trend's lifecycle stage — newly emerging (`virality_score`) vs. already mature/established (`trending_score`). A method could score `trending_ratio = 1.4` (oversampling mature content) and `virality_ratio = 0.6` (undersampling emerging content) and average to a falsely reassuring `1.0`. Reporting both separately exposes directional bias that a blended average would hide — which is exactly the diagnostic needed to tell Methods 3 and 4 apart.

### 6.2 Sanity-check columns (reported, not ranked on)

**Country Balance** (entropy across ID/MY/PH/TH) and **realized Beauty/Non-Beauty share vs. target** — shown to verify the quota was implemented correctly, but excluded from the radar chart / composite ranking since the quota fixes these identically across all six methods by design.

### 6.3 Aggregation strategy

- **Per-cell (finest grain):** method × cell × metric — for technical/audit review.
- **Scorecard / radar (main comparison):** **simple (equal-weight) macro-average across the 8 cells**, not a population- or budget-weighted average. This is a deliberate choice: Beauty cells are structurally smaller than Non-Beauty cells, and a size-weighted average would let Non-Beauty dominate the headline numbers, defeating the purpose of having a BPC-aware design in the first place.
- **Faceted view (for the marketing audience):** two side-by-side radar charts — Beauty-cells-only vs. Non-Beauty-cells-only — since that split is the one stakeholders will ask about first.
- **Per-metric ranking (for exact rank, not just shape):** each of the 7 core metrics also gets its own bar chart ranking all 6 methods — pooled, Beauty-only, and Non-Beauty-only — since a radar's overlapping lines can make the exact ordering ambiguous, and the BPC-only ranking can differ from the pooled one (in the current backtest, 3 of 7 metrics flip which method leads once Beauty cells are isolated).
- **Method-family view:** methods are also grouped into `Extract-all` (M1, M2), `Top-K per hashtag` (M3–M5), and `Random` (M7) for a dedicated Coverage Ratio comparison — the pattern of Top-K-per-hashtag methods beating Extract-all methods by a wide, consistent margin on Coverage Ratio (roughly 2× in the current backtest) is one of the clearest and most consistent findings across the whole scorecard, and is easiest to see when colored by family rather than by individual method.

---

## 7. Implementation Pipeline

1. **Load & clean**
   - Load `tiktok-video_combined_score_20260627.csv` as the base universe (13,143 rows).
   - Load `hashtag_to_video.csv` (all 9 dates), fix the `VIDEO_ID` precision bug, dedup on `(VIDEO_ID, HASHTAG_ID, COUNTRY_CODE)`.
   - Load `hashtag_overview.csv`, filter to `DATA_EXTRACT_DATE = 2026-06-27`, resolve any hashtag with duplicate category rows on that date by keeping the best `RANK_POSITION_NUMBER`.
2. **Build the bridge table** (`edges`): join video ↔ hashtag(country) ↔ hashtag_overview attributes (`RANK_POSITION_NUMBER`, `RANKING`, `HASHTAG_TYPE`, `CATEGORY_NAME`, `HASHTAG_NAME`, `VIEW_COUNT`). Restrict to videos present in the base universe.
3. **Determine the effective universe** (10,196 videos): drop videos with zero edges after the join above; document the 2,947 dropped videos as a limitation.
4. **Assign every video to a cell**: type first (inclusive-OR on `HASHTAG_TYPE = BEAUTY`), then country (min `RANKING` among same-type edges); also record each video's `primary_category` (the category of the same edge that drove its cell assignment), used by the Category Balance metric.
5. **Compute cell budgets**: apply the 50/16.67/16.67/16.67 × 80/20 cross via `largest_remainder`, targeting the chosen total budget (default 2,000).
6. **Run all 6 methods independently per cell**, using only cell-restricted edges/videos as described in Section 5.1; union the 8 per-cell outputs per method. Track which selected videos came from each method's `top_up` fallback vs. its primary ranking logic.
7. **Compute the 7 core metrics + fill rate per cell per method**, then macro-average to the method-level scorecard, and again split by Beauty-only / Non-Beauty-only cells.
8. **Visualize**: per-cell heatmaps (technical), macro-averaged radar (main scorecard), Beauty/Non-Beauty faceted radars (marketing-facing), a per-metric ranking small-multiples grid (pooled + BPC-split), and a method-family Coverage Ratio comparison (Top-K-per-hashtag vs. Extract-all vs. Random).
9. **Write up findings** as descriptive read-outs, not a recommendation (per Section 1.3) — explicit statement that no single composite number should be read as a definitive winner.
10. **Export for dashboard**: write three linked CSVs to `data/dashboard/` — `selected_videos.csv` (1 row per method × video, 12,000 rows), `coverage_scorecard.csv` (1 row per method × cell, 48 rows), and `method_summary.csv` (1 row per method, 6 rows) — filterable by method and country, for a Tableau dashboard aimed at the marketing team. Column-level definitions live in `data/dashboard/README.md`, not duplicated here.

**Note on scope vs. earlier drafts:** an earlier iteration of this pipeline also computed three supplementary diagnostics — pairwise overlap between methods (Jaccard similarity), lift vs. Random baseline per metric, and a raw-growth-signal cross-check against `trending_score`/`virality_score`. These were removed from the shipped notebook after review to keep the deliverable focused on the three-table dashboard export above; see Appendix A for the reasoning. The logic is simple enough to re-add to `notebook/build_notebook_v2.py` if a future review needs it again.

---

## 8. Limitations & Future Work

Carried over / updated from v1:

1. Universe is still bounded by what TCC's leaderboard surfaces — not all of TikTok, and now further bounded by hashtags appearing specifically on the 2026-06-27 leaderboard.
2. **2,947 videos (22% of the raw combined-score universe) are excluded** because their hashtags don't appear in the 27-June `hashtag_overview` snapshot — a direct consequence of pinning the ranking source to a single date. Revisiting this with a fallback date-window is a reasonable next iteration if this exclusion rate proves material to stakeholders.
3. This is still a single-snapshot backtest (no week-over-week stability check yet) — same caveat as v1.
4. The BPC quota (80/20, 50/16.67/16.67/16.67) is a **fixed business input**, not derived from data — it should be labeled explicitly as such in any external-facing report, especially given it's a ~1.6× oversample of Beauty relative to the natural video-level split (50/50) and a much larger oversample relative to the hashtag-population split (6%).
5. Video-level BPC type is still a proxy (inclusive-OR on hashtag tags), not a content-verified label — true BPC relevance still requires the watching step this whole pipeline exists to ration. This remains future work, same circularity as v1 Section 3.3, now partially mitigated but not resolved.
6. `trending_score` / `virality_score` definitions are still not fully known from TCC's side; they continue to be treated as signals, not ground truth. (An earlier notebook version cross-validated them against raw growth fields — `view_velocity`, `views_growth_short`, `reach_ratio` — as a supplementary diagnostic; that check was dropped from the shipped version per Appendix A but the raw fields remain in `selected_videos.csv` if it needs to be redone.)
7. An M6 variant (top-K per hashtag ranked by raw `view_count`) was implemented and backtested, then dropped after review — it added the least differentiated signal among the four score-based top-K variants (Spearman 0.44–0.51 vs. the other two scores, similar to their mutual correlation) and skewed hardest toward already-established, high-follower content, which was judged the least useful direction to explore further. The method numbering keeps the M6 gap rather than renumbering M7 (Random).

---

## Appendix A: Key Design Decisions & Rationale

| Decision | Choice made | Rationale |
|---|---|---|
| Hashtag ranking date | Pinned to 2026-06-27 | Ranking fields are a daily time series; unioning dates would mix a hashtag's rank across multiple days into one undefined value. |
| Video↔hashtag mapping date | Union of all 9 available dates | Same-date-only filtering resolves only 22% of the universe; the mapping is cumulative, not a daily 1:1 snapshot. |
| Budget control | Fixed total video count (2,000) equal across all 6 methods | Cost is a linear function of unique video count, so equal video count = equal cost = fair comparison. |
| Extra baseline | Add Random (method 7) alongside the drafted methods | Needed to prove rule-based methods actually beat chance at equal cost — the most informative comparator in v1's backtest. |
| Country handling | Assign each video to exactly one country (best `RANKING` among same-type edges) | 83% of videos span multiple countries via different hashtags; a hard assignment is required to keep quota cells disjoint. |
| Country quota | 50% ID, remaining 50% split evenly across TH/MY/PH | Business input. |
| BPC quota | 80% Beauty / 20% Non-Beauty | Business input. |
| Quota crossing | 2D cross (country % × type % = 8 cells) | Unambiguous and simplest to reason about; avoids sequential-filter order-dependence. |
| Quota scope | Applies to all 6 methods, including Random | The quota is a business constraint, not a method choice — every method should be judged on its within-cell selection quality, not on whether it respects the quota. |
| BPC video assignment | Inclusive-OR: BEAUTY if any hashtag edge is BEAUTY | Consistent with prioritizing not missing BPC-relevant content, aligned with the business's oversampling intent. |
| Unreachable videos (22%) | Excluded from the effective universe, documented as a limitation | Simpler and more consistent than introducing a fallback date-window; treated the same way v1 treated its universe-definition limitation. |
| Category Balance normalizer | Per-cell-type (`log(4)` Beauty, `log(57)` Non-Beauty) | A single global normalizer structurally caps Beauty's achievable score regardless of method quality. |
| Category Balance counting unit | One vote per selected video (via `primary_category`), not one vote per hashtag edge | Makes it consistent with Creator Diversity's methodology, which already counts one vote per video; the edge-level version let videos with more in-cell hashtags cast disproportionately more votes. |
| Trend-stage Balance | Reported as 2 separate ratios (trending, virality), not averaged | The two scores correlate only moderately (0.47); averaging can hide directional bias. |
| Long-tail definition | Relative percentile within category, not absolute rank threshold; computed once per video from TCC's `RANK_POSITION_NUMBER`, independent of which method selected it | `RANK_POSITION_NUMBER` is capped at 200 and category sizes vary too much for an absolute cutoff to be fair; keeping the definition method-independent means the per-method metric only reflects *which* videos each method selected, not a different yardstick per method. |
| Scorecard aggregation | Equal-weight macro-average across 8 cells | A population-weighted average would let Non-Beauty's much larger cells dominate, defeating the purpose of a BPC-aware design. |
| BPC-split per-metric ranking | Added pooled, Beauty-only, and Non-Beauty-only per-metric ranking bar charts | The pooled ranking can hide a leader swap once Beauty cells are isolated — in the current backtest this happens on 3 of 7 metrics. |
| M6 (Top-K by `view_count`) | Implemented, backtested, then dropped; method numbering keeps the gap rather than renumbering M7 | Added the least differentiated signal among the score-based Top-K variants and skewed hardest toward already-established content — judged the least useful direction to keep exploring. Keeping the gap avoids relabeling M7 (Random) across the notebook and dashboard export. |
| Supplementary diagnostics (overlap, lift-vs-random, growth cross-check) | Removed from the shipped notebook | Kept the deliverable focused on the 3-table dashboard export (Section 7 step 10); the logic is simple to re-add later if a future review needs it. |
| Dashboard export schema | 3 linked CSVs (`selected_videos`, `coverage_scorecard`, `method_summary`), country/BPC as boolean flag columns, category as `primary_category` + `all_categories` (not exploded rows) | Matches how the marketing team's Tableau dashboard needs to filter (method × country), keeps the fact table at a clean 1-row-per-(method, video) grain, and avoids the "SUM a pre-aggregated ratio" trap by keeping raw and aggregated data in separate tables. Full column definitions in `data/dashboard/README.md`. |

## Appendix B: Field Glossary

| Field | File | Meaning |
|---|---|---|
| `virality_score` | combined_score | = "emerging_score" in v1/project terminology |
| `RANK_POSITION_NUMBER` | hashtag_overview | Per (country, category, date) rank, capped at 200 |
| `RANKING` | hashtag_overview | Per (hashtag_type, country, date) rank, uncapped — `ROW_NUMBER() OVER (PARTITION BY hashtag_type, country_code, data_extract_date ORDER BY view_count DESC, rank_change_number DESC, post_count DESC)` |
| `HASHTAG_TYPE` | hashtag_overview, hashtag_to_video | `BEAUTY` or `NON BEAUTY` — the hashtag-level BPC signal |
| `CATEGORY_NAME` | hashtag_overview, hashtag_to_video | Content category (61 values total; only 4 are under `BEAUTY`) |
| `uploader` | combined_score | Creator username (no numeric creator ID available in this dataset) |
