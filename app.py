"""
TikTok Sampling Backtest - Method Comparison dashboard.

Two pages selected by a segmented control:
  - "Overview & Context": static explainer (universe, budget, coverage and
    cost per method, method glossary, metric glossary). No filters.
  - "Dashboard": inline filter panel + engagement KPIs + radar + per-metric
    ranking + hashtag word cloud + paginated video table with optional
    TikTok oEmbed thumbnails.

Style follows reference/style_reference.png: blue top navbar, light
blue-gray canvas, white cards with hairline borders, uppercase card labels,
Poppins font, compact SaaS layout.

Run:
    streamlit run app.py
"""

import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "dashboard"
LOGO_PATH = ROOT / "img" / "paragon-logo.png"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
METHOD_ORDER = [
    "M1 Broad (Rank Position)",
    "M2 Narrow (Ranking)",
    "M3 Top-K (Growth)",
    "M4 Top-K (Popular)",
    "M5 Top-K (Avg Score)",
    "Random Baseline",
]
METHOD_SHORT = {
    "M1 Broad": "M1 Broad (Rank Position)",
    "M2 Narrow": "M2 Narrow (Ranking)",
    "M3 Growth": "M3 Top-K (Growth)",
    "M4 Popular": "M4 Top-K (Popular)",
    "M5 Avg Score": "M5 Top-K (Avg Score)",
    "Random": "Random Baseline",
}
METHOD_COLOR = {
    "M1 Broad (Rank Position)": "#2a78d6",
    "M2 Narrow (Ranking)": "#1baf7a",
    "M3 Top-K (Growth)": "#eda100",
    "M4 Top-K (Popular)": "#008300",
    "M5 Top-K (Avg Score)": "#4a3aa7",
    "Random Baseline": "#726f68",
}
FAMILY_COLOR = {
    "Top-K per hashtag": "#2a78d6",
    "Extract-all": "#e34948",
    "Random": "#726f68",
}
METHOD_FAMILY = {
    "M1 Broad (Rank Position)": "Extract-all",
    "M2 Narrow (Ranking)": "Extract-all",
    "M3 Top-K (Growth)": "Top-K per hashtag",
    "M4 Top-K (Popular)": "Top-K per hashtag",
    "M5 Top-K (Avg Score)": "Top-K per hashtag",
    "Random Baseline": "Random",
}
FAMILY_BADGE = {
    "Top-K per hashtag": ("#e8f1fc", "#1c5cab"),
    "Extract-all": ("#fdecec", "#c03535"),
    "Random": ("#eef0f3", "#55607a"),
    "Random (control)": ("#eef0f3", "#55607a"),
}
CORE_METRICS = {
    "Coverage Ratio": "coverage_ratio",
    "Breadth Coverage": "breadth_coverage",
    "Category Balance": "category_balance",
    "Creator Diversity": "creator_diversity",
    "Popular Ratio": "trending_ratio",
    "Growth Ratio": "virality_ratio",
    "Long-tail Coverage": "long_tail_coverage",
}
ENGAGEMENT_METRIC_SPECS = {
    "Total Views": ("view_count", "sum", lambda v: human_number(v)),
    "Total Likes": ("like_count", "sum", lambda v: human_number(v)),
    "Total Shares": ("share_count", "sum", lambda v: human_number(v)),
    "Avg Engagement Rate": ("engagement_rate", "mean", lambda v: f"{v:.1%}"),
    "Avg View Growth": ("views_growth_short", "mean", lambda v: human_number(v)),
    "Unique Creators": ("uploader", "nunique", lambda v: f"{v:,.0f}"),
}
RANDOM_LABEL = "Random Baseline"
COUNTRIES = ["ID", "MY", "PH", "TH"]
SNAPSHOT_DATE = "2026-06-27"
BLUE_INK = "#14213d"

PAGE_OVERVIEW = "Overview & Context"
PAGE_DASHBOARD = "Dashboard"

# ---------------------------------------------------------------------------
# Page config + global CSS
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Sampling Backtest",
    page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');

    html, body, [class*="st-"] {
        font-family: 'Poppins', sans-serif;
    }
    span[data-testid="stIconMaterial"], .material-symbols-rounded {
        font-family: 'Material Symbols Rounded' !important;
    }
    .stApp { background-color: #f4f6fb; }
    header[data-testid="stHeader"] { display: none; }
    .block-container {
        padding-top: 6rem;
        padding-bottom: 2rem;
        padding-left: 2rem;
        padding-right: 2rem;
        max-width: 100%;
    }

    /* Sidebar: permanent (collapse control hidden), clears the fixed navbar */
    section[data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid #e4e9f2;
        width: 300px !important;
        min-width: 300px !important;
    }
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 5rem;
    }
    [data-testid="stSidebarCollapseButton"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"] {
        display: none !important;
    }

    /* Top navbar */
    .topnav {
        position: fixed;
        top: 0; left: 0; right: 0;
        height: 64px;
        background: linear-gradient(90deg, #1c4e9c 0%, #2a78d6 100%);
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 28px;
        z-index: 9999999;
        box-shadow: 0 1px 6px rgba(16, 24, 40, 0.18);
    }
    .topnav-left { display: flex; align-items: center; gap: 14px; }
    .logo-chip {
        background: #ffffff;
        border-radius: 8px;
        padding: 4px 10px;
        display: inline-flex;
        align-items: center;
    }
    .logo-chip img { height: 20px; display: block; }
    .topnav-title { color: #ffffff; font-size: 15px; font-weight: 600; }
    .topnav-sub { color: rgba(255,255,255,0.75); font-size: 12px; font-weight: 400; }
    .topnav-right { display: flex; align-items: center; gap: 10px; }
    .nav-pill {
        background: rgba(255,255,255,0.16);
        border-radius: 8px;
        padding: 5px 12px;
        font-size: 12px;
        color: #ffffff;
    }
    .nav-dot {
        display: inline-block;
        width: 7px; height: 7px;
        border-radius: 50%;
        background: #57d98a;
        margin-right: 7px;
        vertical-align: middle;
    }

    /* Cards */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #ffffff;
        border: 1px solid #e4e9f2 !important;
        border-radius: 12px;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    }
    div[data-testid="stHorizontalBlock"] { align-items: stretch; }
    div[data-testid="stColumn"] > div,
    div[data-testid="stColumn"] div[data-testid="stVerticalBlockBorderWrapper"] {
        height: 100%;
    }

    h1, h2, h3, h4 { color: #14213d; }
    h4 { font-size: 16px !important; margin: 0 !important; padding: 0 !important; }

    /* KPI grid */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(6, 1fr);
        gap: 12px;
    }
    .kpi-card {
        background: #ffffff;
        border: 1px solid #e4e9f2;
        border-radius: 12px;
        padding: 14px 16px 12px 16px;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        display: flex;
        flex-direction: column;
    }
    .kpi-label {
        font-size: 10.5px;
        font-weight: 600;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        color: #8a94a6;
        margin-bottom: 4px;
    }
    .kpi-value {
        font-size: 24px;
        font-weight: 600;
        color: #14213d;
        line-height: 1.15;
    }
    .kpi-sub { font-size: 11.5px; color: #8a94a6; margin-top: 4px; }
    .kpi-sub.pos { color: #0e9f4f; font-weight: 500; }
    .kpi-sub.neg { color: #d03b3b; font-weight: 500; }

    .section-title {
        font-size: 11.5px;
        font-weight: 600;
        letter-spacing: 0.09em;
        text-transform: uppercase;
        color: #8a94a6;
        margin: 18px 0 8px 2px;
    }

    /* Clean tables */
    table.clean-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
        background: #ffffff;
    }
    .clean-table thead th { background: #ffffff; }
    .clean-table th {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #8a94a6;
        font-weight: 600;
        padding: 8px 12px;
        border-bottom: 1px solid #edf0f6;
    }
    .clean-table td {
        padding: 9px 12px;
        border-bottom: 1px solid #f1f3f8;
        color: #2b3450;
        vertical-align: top;
    }
    .clean-table tr:last-child td { border-bottom: none; }
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 8px;
        font-size: 11px;
        font-weight: 500;
        white-space: nowrap;
    }
    .dot {
        display: inline-block;
        width: 8px; height: 8px;
        border-radius: 50%;
        margin-right: 8px;
    }
    div[data-testid="stDataFrame"] { background: #ffffff; border-radius: 12px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_data():
    videos = pd.read_csv(DATA_DIR / "selected_videos.csv", dtype={"video_id": str})
    scorecard = pd.read_csv(DATA_DIR / "coverage_scorecard.csv")
    summary = pd.read_csv(DATA_DIR / "method_summary.csv")
    # Display-name normalization. The CSVs keep the original naming from the
    # backtest notebook (M7 Random Baseline, Virality, Trending); the app
    # displays Random Baseline / Growth / Popular instead. Mapping here keeps
    # the exported data and the notebook untouched.
    label_map = {
        "M7 Random Baseline": "Random Baseline",
        "M3 Top-K (Virality)": "M3 Top-K (Growth)",
        "M4 Top-K (Trending)": "M4 Top-K (Popular)",
    }
    for df in (videos, scorecard, summary):
        df["method_label"] = df["method_label"].replace(label_map)
        df["method_key"] = df["method_key"].replace({"M7": "Random"})
    return videos, scorecard, summary


@st.cache_data(show_spinner=False)
def logo_b64() -> str:
    return base64.b64encode(LOGO_PATH.read_bytes()).decode() if LOGO_PATH.exists() else ""


videos_df, scorecard_df, summary_df = load_data()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def human_number(value: float, prefix: str = "") -> str:
    if pd.isna(value):
        return "-"
    for suffix, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(value) >= div:
            return f"{prefix}{value / div:,.1f}{suffix}"
    if float(value).is_integer():
        return f"{prefix}{value:,.0f}"
    return f"{prefix}{value:,.2f}"


def kpi_card(label: str, value: str, sub: str = "", sub_class: str = "") -> str:
    sub_html = f'<div class="kpi-sub {sub_class}">{sub}</div>' if sub else ""
    return (
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div>{sub_html}</div>'
    )


def render_kpi_grid(cards: list[str]) -> None:
    st.markdown(f'<div class="kpi-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def delta_sub(value: float, baseline: float, fmt) -> tuple[str, str]:
    if pd.isna(value) or pd.isna(baseline):
        return "", ""
    diff = value - baseline
    sign = "+" if diff >= 0 else "-"
    return f"{sign}{fmt(abs(diff))} vs Random", "pos" if diff >= 0 else "neg"


def family_badge(family: str) -> str:
    bg, fg = FAMILY_BADGE.get(family, ("#eef0f3", "#55607a"))
    return f'<span class="badge" style="background:{bg};color:{fg}">{family}</span>'


def method_cell(label: str) -> str:
    color = METHOD_COLOR.get(label, "#8a94a6")
    return f'<span class="dot" style="background:{color}"></span>{label}'


def clean_table(headers: list[str], rows: list[list[str]], right_from: int | None = None) -> str:
    def align(i: int) -> str:
        return "right" if right_from is not None and i >= right_from else "left"

    th = "".join(f'<th style="text-align:{align(i)}">{h}</th>' for i, h in enumerate(headers))
    body = ""
    for row in rows:
        tds = "".join(f'<td style="text-align:{align(i)}">{c}</td>' for i, c in enumerate(row))
        body += f"<tr>{tds}</tr>"
    return f'<table class="clean-table"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def plotly_base_layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        font=dict(family="Poppins, sans-serif", color=BLUE_INK, size=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=20, r=20, t=16, b=16),
    )
    return fig


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{alpha})"


def method_color(method_label: str, group_by_family: bool) -> str:
    if group_by_family:
        return FAMILY_COLOR.get(METHOD_FAMILY.get(method_label, ""), "#2a78d6")
    return METHOD_COLOR.get(method_label, "#8a94a6")


TAG_TIER_STYLE = {
    1: (11, 400, "#c9def7"),
    2: (14, 400, "#8fbeed"),
    3: (19, 500, "#2a78d6"),
    4: (27, 600, "#1c5cab"),
    5: (38, 700, "#0d366b"),
}


def compute_tag_tiers(counts: pd.Series) -> pd.Series:
    ranks = counts.rank(pct=True, method="first")
    return ranks.apply(
        lambda p: 5 if p > 0.85 else 4 if p > 0.65 else 3 if p > 0.4 else 2 if p > 0.15 else 1
    )


def safe_css_key(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in text)[:40]


def render_hashtag_cloud(frame: pd.DataFrame, key_prefix: str, max_tags: int = 60) -> None:
    """Clickable hashtag cloud: plain '#tag' text sized/colored by frequency
    tier, flowed inline (like wrapped text) so big and small tags sit
    together the way a real word cloud does, instead of a plain list.
    Clicking a tag toggles it as the active filter for the video table
    (st.session_state['active_hashtag'])."""
    tags = frame["all_hashtag_names"].dropna().str.split("|").explode().str.strip()
    tags = tags[tags != ""]
    if tags.empty:
        st.caption("No hashtags in the current filter.")
        return

    counts = tags.value_counts().head(max_tags)
    tiers = compute_tag_tiers(counts)
    active = st.session_state.get("active_hashtag")

    # Zigzag biggest/smallest so large and small tags interleave across the
    # flow instead of all the big ones clumping at the start.
    ranked = list(counts.sort_values(ascending=False).items())
    order = []
    lo, hi = 0, len(ranked) - 1
    take_low = True
    while lo <= hi:
        order.append(ranked[lo if take_low else hi])
        if take_low:
            lo += 1
        else:
            hi -= 1
        take_low = not take_low

    css_rules = [
        f'div[data-testid="stVerticalBlock"].st-key-{key_prefix} '
        '{ display: flex !important; flex-direction: row !important; flex-wrap: wrap !important; '
        'align-items: baseline !important; row-gap: 6px; column-gap: 16px; }',
        f'.st-key-{key_prefix} div[data-testid="stElementContainer"] '
        '{ width: auto !important; }',
        f'.st-key-{key_prefix} div[data-testid="stButton"] button '
        '{ border: none !important; background: transparent !important; '
        'padding: 0 !important; box-shadow: none !important; height: auto !important; '
        'min-height: 0 !important; line-height: 1.15 !important; }',
    ]
    with st.container(key=key_prefix):
        for tag, count in order:
            size, weight, color = TAG_TIER_STYLE[int(tiers[tag])]
            btn_key = f"{key_prefix}_{safe_css_key(tag)}"
            if st.button(f"#{tag}", key=btn_key, type="tertiary", help=f"{count:,} selected videos"):
                st.session_state["active_hashtag"] = None if active == tag else tag
            is_active = st.session_state.get("active_hashtag") == tag
            decoration = "underline" if is_active else "none"
            # Target the deeply nested <p> too: Streamlit sets its own
            # font-size on it, which otherwise overrides the button's.
            css_rules.append(
                f'.st-key-{btn_key} button, .st-key-{btn_key} p '
                f'{{ font-size: {size}px !important; font-weight: {weight} !important; '
                f'color: {color} !important; text-decoration: {decoration} !important; '
                f'line-height: 1.15 !important; }}'
            )
        st.markdown(f"<style>{''.join(css_rules)}</style>", unsafe_allow_html=True)


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def fetch_thumbnails(urls: tuple[str, ...]) -> dict[str, str]:
    def one(url: str) -> tuple[str, str]:
        try:
            r = requests.get(
                "https://www.tiktok.com/oembed", params={"url": url}, timeout=5
            )
            r.raise_for_status()
            return url, r.json().get("thumbnail_url", "")
        except Exception:
            return url, ""

    with ThreadPoolExecutor(max_workers=10) as pool:
        return dict(pool.map(one, urls))


# ---------------------------------------------------------------------------
# Top navbar (fixed, blue) + page switcher
# ---------------------------------------------------------------------------
logo_img = (
    f'<span class="logo-chip"><img src="data:image/png;base64,{logo_b64()}" /></span>'
    if logo_b64()
    else '<span class="topnav-title">PARAGON CORP</span>'
)
st.markdown(
    f"""
    <div class="topnav">
      <div class="topnav-left">
        {logo_img}
        <span class="topnav-title">TikTok Sampling Backtest</span>
        <span class="topnav-sub">Method comparison for budget-constrained video sampling</span>
      </div>
      <div class="topnav-right">
        <span class="nav-pill"><span class="nav-dot"></span>12,000 selected videos</span>
        <span class="nav-pill">Snapshot {SNAPSHOT_DATE}</span>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

page = st.segmented_control(
    "Page",
    [PAGE_OVERVIEW, PAGE_DASHBOARD],
    default=PAGE_OVERVIEW,
    label_visibility="collapsed",
)
if page is None:
    page = PAGE_OVERVIEW

# ===========================================================================
# PAGE 1 - OVERVIEW & CONTEXT
# ===========================================================================
if page == PAGE_OVERVIEW:
    st.markdown('<div class="section-title">The Backtest at a Glance</div>', unsafe_allow_html=True)
    render_kpi_grid(
        [
            kpi_card("Raw Universe", "13,143", "videos from TCC snapshot"),
            kpi_card("Effective Universe", "10,196", "78% reachable via ranked hashtags"),
            kpi_card("Markets", "4", "ID, MY, PH, TH"),
            kpi_card("Quota Cells", "8", "4 countries x Beauty / Non-Beauty"),
            kpi_card("Budget per Method", "2,000", "videos, Rp200 each"),
            kpi_card("Quota Rule", "50 / 80", "50% Indonesia, 80% Beauty"),
        ]
    )

    st.markdown('<div class="section-title">Coverage &amp; Cost per Method</div>', unsafe_allow_html=True)
    with st.container(border=True):
        rows = []
        for label in METHOD_ORDER:
            r = summary_df[summary_df["method_label"] == label].iloc[0]
            rows.append(
                [
                    method_cell(label),
                    family_badge(r["method_family"]),
                    f"{r['total_selected']:,.0f}",
                    human_number(r["est_total_cost_rupiah"], "Rp"),
                    f"{r['overall_fill_rate']:.0%}",
                    f"{r['coverage_ratio']:.1f}x",
                    f"{r['breadth_coverage']:.2f}",
                    f"{r['category_balance']:.2f}",
                    f"{r['long_tail_coverage']:.1%}",
                ]
            )
        st.markdown(
            clean_table(
                ["Method", "Family", "Videos", "Est. Cost", "Fill Rate",
                 "Coverage Ratio", "Breadth", "Category Balance", "Long-tail"],
                rows,
                right_from=2,
            ),
            unsafe_allow_html=True,
        )
        st.caption(
            "Macro-averaged across all 8 quota cells (4 countries x Beauty / "
            "Non-Beauty), so smaller Beauty cells weigh the same as larger "
            "Non-Beauty cells."
        )

    col_methods, col_glossary = st.columns(2)
    with col_methods:
        st.markdown('<div class="section-title">The 6 Methods</div>', unsafe_allow_html=True)
        with st.container(border=True):
            method_rows = [
                [method_cell("M1 Broad (Rank Position)"), family_badge("Extract-all"),
                 "Takes every video from the top-ranked hashtags in each category. Breadth-first."],
                [method_cell("M2 Narrow (Ranking)"), family_badge("Extract-all"),
                 "Takes every video from the best-ranked hashtags overall. Depth-first, fewer hashtags touched."],
                [method_cell("M3 Top-K (Growth)"), family_badge("Top-K per hashtag"),
                 "Best few videos per hashtag, ranked by growth (emerging) score."],
                [method_cell("M4 Top-K (Popular)"), family_badge("Top-K per hashtag"),
                 "Same mechanism, ranked by popular score instead."],
                [method_cell("M5 Top-K (Avg Score)"), family_badge("Top-K per hashtag"),
                 "Same mechanism, ranked by the average of popular and growth."],
                [method_cell("Random Baseline"), family_badge("Random (control)"),
                 "Uniform random pick. The control group every other method should beat."],
            ]
            st.markdown(
                clean_table(["Method", "Family", "What it does"], method_rows),
                unsafe_allow_html=True,
            )
            st.caption(
                "A sixth Top-K variant ranked by raw view count was tested and "
                "dropped during the design phase."
            )

    with col_glossary:
        st.markdown('<div class="section-title">The 7 Coverage Metrics</div>', unsafe_allow_html=True)
        with st.container(border=True):
            glossary_rows = [
                ["<b>Coverage Ratio</b>",
                 "For the hashtags touched, how much of their total view volume the selected videos represent."],
                ["<b>Breadth Coverage</b>",
                 "Of all the hashtags available in a cell, what fraction did this method actually touch."],
                ["<b>Category Balance</b>",
                 "How evenly the selection spreads across content categories. Touching every category but dumping the budget into one still scores low."],
                ["<b>Creator Diversity</b>",
                 "The same evenness idea, for creators: many creators represented lightly, or a few dominating the picks."],
                ["<b>Popular / Growth Ratio</b>",
                 "Two numbers on purpose: does the selection skew toward already-established content (popular) or still-emerging content (growth)?"],
                ["<b>Long-tail Coverage</b>",
                 "The % of picks not found via an obviously top-ranked hashtag. Uses TikTok's own ranking, so it is method-independent."],
                ["<b>Fill Rate</b>",
                 "Did the method reach its target count in every cell. Only a real risk for M1/M2, which extract every video of a hashtag."],
            ]
            st.markdown(
                clean_table(["Metric", "What it tells you"], glossary_rows),
                unsafe_allow_html=True,
            )

# ===========================================================================
# PAGE 2 - DASHBOARD
# ===========================================================================
else:
    # -- Filter sidebar (permanent on this page: collapse control is hidden
    #    via CSS, and this block only runs on the Dashboard page) -------------
    with st.sidebar:
        st.markdown("**Method**")
        sel_short = []
        method_cols = st.columns(2)
        for i, short in enumerate(METHOD_SHORT):
            with method_cols[i % 2]:
                if st.checkbox(short, value=True, key=f"flt_method_{short}"):
                    sel_short.append(short)
        group_by_family = st.toggle(
            "Group colors by family",
            value=False,
            help="When on, methods are colored by mechanism: M1+M2 (Extract-all), "
            "M3-M5 (Top-K per hashtag), Random Baseline, instead of one color per method.",
        )
        st.markdown("**Country**")
        sel_countries = []
        country_cols = st.columns(2)
        for i, country in enumerate(COUNTRIES):
            with country_cols[i % 2]:
                if st.checkbox(country, value=True, key=f"flt_country_{country}"):
                    sel_countries.append(country)
        sel_bpc = st.segmented_control(
            "BPC Type", ["All", "Beauty", "Non-Beauty"], default="All"
        )
        st.divider()
        exclude_topup = st.toggle("Exclude top-up picks", value=False)
        long_tail_only = st.toggle("Long-tail only", value=False)
        load_thumbs = st.toggle(
            "Load thumbnails",
            value=False,
            help="Fetches thumbnails from TikTok for the visible table page. Needs internet access.",
        )
        st.divider()
        st.caption(
            "All KPIs, charts, and the video table below follow these filters. "
            f"Data dictionary: data/dashboard/README.md. Snapshot {SNAPSHOT_DATE}."
        )

    sel_methods = [METHOD_SHORT[s] for s in (sel_short or [])]
    if not sel_methods or not sel_countries:
        st.warning("Select at least one method and one country.")
        st.stop()
    if sel_bpc is None:
        sel_bpc = "All"

    # -- Apply filters ---------------------------------------------------------
    bpc_value = {"Beauty": "BEAUTY", "Non-Beauty": "NON BEAUTY"}.get(sel_bpc)

    vids = videos_df[
        videos_df["method_label"].isin(sel_methods)
        & videos_df["country"].isin(sel_countries)
    ]
    if bpc_value:
        vids = vids[vids["bpc_type"] == bpc_value]

    vids_kpi = vids[~vids["is_topup"]] if exclude_topup else vids
    vids_table = vids_kpi[vids_kpi["is_long_tail"]] if long_tail_only else vids_kpi

    # Same filters, but ignores the Method checkboxes: used for cross-method
    # comparisons where every method must stay visible regardless of selection.
    vids_all_methods = videos_df[videos_df["country"].isin(sel_countries)]
    if bpc_value:
        vids_all_methods = vids_all_methods[vids_all_methods["bpc_type"] == bpc_value]
    if exclude_topup:
        vids_all_methods = vids_all_methods[~vids_all_methods["is_topup"]]
    if long_tail_only:
        vids_all_methods = vids_all_methods[vids_all_methods["is_long_tail"]]

    # Same filters as vids_all_methods, but ignores the Method checkboxes: the
    # Per-metric ranking chart always compares all 6 methods.
    score_all_methods = scorecard_df[scorecard_df["country"].isin(sel_countries)]
    if bpc_value:
        score_all_methods = score_all_methods[score_all_methods["bpc_type"] == bpc_value]

    single_method = len(sel_methods) == 1 and sel_methods[0] != RANDOM_LABEL

    # -- Engagement & growth KPIs ----------------------------------------------
    st.markdown('<div class="section-title">Engagement &amp; Growth</div>', unsafe_allow_html=True)

    if vids_kpi.empty:
        st.info("No videos match the current filters.")
        st.stop()

    def eng_delta(col, agg, fmt):
        if not single_method:
            return "", ""
        base = videos_df[
            (videos_df["method_label"] == RANDOM_LABEL)
            & videos_df["country"].isin(sel_countries)
        ]
        if bpc_value:
            base = base[base["bpc_type"] == bpc_value]
        if base.empty:
            return "", ""
        return delta_sub(agg(vids_kpi[col]), agg(base[col]), fmt)

    eng_specs = [
        ("Total Views", "view_count", "sum", lambda v: human_number(v)),
        ("Total Likes", "like_count", "sum", lambda v: human_number(v)),
        ("Total Shares", "share_count", "sum", lambda v: human_number(v)),
        ("Avg Engagement", "engagement_rate", "mean", lambda v: f"{v:.1%}"),
        ("Avg View Growth", "views_growth_short", "mean", lambda v: human_number(v)),
        ("Unique Creators", "uploader", "nunique", lambda v: f"{v:,.0f}"),
    ]
    cards = []
    for label, col, how, fmt in eng_specs:
        agg = {"sum": pd.Series.sum, "mean": pd.Series.mean, "nunique": pd.Series.nunique}[how]
        value = agg(vids_kpi[col])
        sub, sub_class = eng_delta(col, agg, fmt)
        if not sub:
            sub = f"across {len(sel_methods)} method{'s' if len(sel_methods) > 1 else ''}"
        cards.append(kpi_card(label, fmt(value), sub, sub_class))
    render_kpi_grid(cards)

    # -- Radar + per-metric ranking ---------------------------------------------
    st.markdown('<div class="section-title">Method Comparison</div>', unsafe_allow_html=True)
    chart_left, chart_right = st.columns([1.35, 1])

    CHART_H = 360
    # Radar gets the extra height the right card spends on its bottom caption,
    # so both cards land at the same total height.
    RADAR_H = 440

    with chart_left:
        with st.container(border=True):
            h1, h2 = st.columns([2, 1.4], vertical_alignment="center")
            with h1:
                st.markdown("#### Coverage profile")
            with h2:
                st.caption("Normalized across all 6 methods")
            norm = summary_df.set_index("method_label")[list(CORE_METRICS.values())]
            norm = (norm - norm.min()) / (norm.max() - norm.min())
            fig = go.Figure()
            theta = list(CORE_METRICS.keys())
            for method in METHOD_ORDER:
                if method not in sel_methods:
                    continue
                values = norm.loc[method].tolist()
                mcolor = method_color(method, group_by_family)
                fig.add_trace(
                    go.Scatterpolar(
                        r=values + values[:1],
                        theta=theta + theta[:1],
                        name=method,
                        line=dict(color=mcolor, width=2),
                        fill="toself",
                        fillcolor=hex_to_rgba(mcolor, 0.06),
                    )
                )
            fig.update_layout(
                polar=dict(
                    bgcolor="rgba(0,0,0,0)",
                    radialaxis=dict(range=[0, 1], showticklabels=False, gridcolor="#e4e9f2"),
                    angularaxis=dict(gridcolor="#e4e9f2", tickfont=dict(size=10)),
                ),
                legend=dict(orientation="h", yanchor="bottom", y=-0.24, font=dict(size=10)),
                showlegend=True,
            )
            plotly_base_layout(fig, height=RADAR_H)
            st.plotly_chart(fig, width="stretch")

    with chart_right:
        with st.container(border=True):
            h1, h2 = st.columns([2, 1.4], vertical_alignment="center")
            with h1:
                st.markdown("#### Per-metric ranking")
            with h2:
                metric_label = st.selectbox(
                    "Metric", list(CORE_METRICS.keys()), label_visibility="collapsed"
                )
            metric_col = CORE_METRICS[metric_label]
            ranked = (
                score_all_methods.groupby(["method_label", "method_family"], as_index=False)[metric_col]
                .mean()
                .sort_values(metric_col)
            )
            fig = go.Figure(
                go.Bar(
                    x=ranked[metric_col],
                    y=ranked["method_label"],
                    orientation="h",
                    marker=dict(
                        color=[method_color(m, group_by_family) for m in ranked["method_label"]],
                        cornerradius=4,
                    ),
                    text=[f"{v:.2f}" for v in ranked[metric_col]],
                    textposition="outside",
                    textfont=dict(size=11),
                )
            )
            fig.update_layout(
                xaxis=dict(showgrid=True, gridcolor="#eef1f7", zeroline=False),
                yaxis=dict(showgrid=False, tickfont=dict(size=11)),
                bargap=0.38,
            )
            plotly_base_layout(fig, height=CHART_H)
            st.plotly_chart(fig, width="stretch")
            base_caption = (
                "Averaged over cells matching the Country / BPC filters. Always "
                "shows all 6 methods regardless of the Method checkboxes above."
            )
            if group_by_family:
                st.caption(f"Blue: Top-K per hashtag. Red: Extract-all. Gray: Random. {base_caption}")
            else:
                st.caption(f'{base_caption} Turn on "Group colors by family" to color by mechanism.')

    # -- Engagement & Growth by method (always shows all 6 methods) ------------
    st.markdown('<div class="section-title">Engagement &amp; Growth by Method</div>', unsafe_allow_html=True)
    with st.container(border=True):
        e1, e2 = st.columns([2.5, 1.4], vertical_alignment="center")
        with e1:
            st.markdown("#### Engagement & growth across all methods")
        with e2:
            eng_metric_label = st.selectbox(
                "Metric",
                list(ENGAGEMENT_METRIC_SPECS.keys()),
                label_visibility="collapsed",
                key="eng_by_method_metric",
            )

        col, how, fmt = ENGAGEMENT_METRIC_SPECS[eng_metric_label]
        agg_fn = {"sum": pd.Series.sum, "mean": pd.Series.mean, "nunique": pd.Series.nunique}[how]
        by_method = (
            vids_all_methods.groupby("method_label")[col]
            .apply(agg_fn)
            .reindex(METHOD_ORDER)
            .sort_values()
        )
        fig = go.Figure(
            go.Bar(
                x=by_method.values,
                y=by_method.index,
                orientation="h",
                marker=dict(
                    color=[method_color(m, group_by_family) for m in by_method.index],
                    cornerradius=4,
                ),
                text=[fmt(v) for v in by_method.values],
                textposition="outside",
                textfont=dict(size=11),
            )
        )
        fig.update_layout(
            xaxis=dict(showgrid=True, gridcolor="#eef1f7", zeroline=False),
            yaxis=dict(showgrid=False, tickfont=dict(size=11)),
            bargap=0.38,
        )
        plotly_base_layout(fig, height=320)
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Follows the Country / BPC Type / Exclude top-up / Long-tail "
            "filters, but always shows all 6 methods regardless of the "
            "Method checkboxes above."
        )

    # -- Hashtag word cloud -------------------------------------------------------
    st.markdown('<div class="section-title">Hashtag Landscape</div>', unsafe_allow_html=True)
    with st.container(border=True):
        h1, h2 = st.columns([4, 1], vertical_alignment="center")
        with h1:
            st.markdown("#### Hashtag word cloud")
        with h2:
            group_mode = st.selectbox(
                "Group by", ["Combined", "Per method"], label_visibility="collapsed"
            )

        if group_mode == "Combined":
            render_hashtag_cloud(vids_kpi, "tagcloud_combined", max_tags=60)
            st.caption(
                f"Word size scales with how many of the {len(vids_kpi):,} filtered "
                "video picks carry that hashtag. Click a hashtag to filter the video "
                "table below."
            )
        else:
            methods_present = [m for m in METHOD_ORDER if m in vids_kpi["method_label"].unique()]
            for i in range(0, len(methods_present), 3):
                row = methods_present[i : i + 3]
                cols = st.columns(3)
                for col, method in zip(cols, row):
                    with col:
                        st.markdown(f"**{method}**")
                        render_hashtag_cloud(
                            vids_kpi[vids_kpi["method_label"] == method],
                            f"tagcloud_{safe_css_key(method)}",
                            max_tags=25,
                        )

        if st.session_state.get("active_hashtag"):
            b1, b2 = st.columns([5, 1], vertical_alignment="center")
            with b1:
                st.caption(
                    f"Filtering the video table by #{st.session_state['active_hashtag']}"
                )
            with b2:
                if st.button("Clear tag", key="clear_hashtag_filter"):
                    st.session_state["active_hashtag"] = None

    active_hashtag = st.session_state.get("active_hashtag")
    if active_hashtag:
        def _has_hashtag(cell: str) -> bool:
            if pd.isna(cell):
                return False
            return active_hashtag in [t.strip() for t in cell.split("|")]

        vids_table = vids_table[vids_table["all_hashtag_names"].apply(_has_hashtag)]

    # -- Video table ----------------------------------------------------------------
    st.markdown('<div class="section-title">Selected Videos</div>', unsafe_allow_html=True)
    with st.container(border=True):
        n_rows = len(vids_table)

        t1, t2, t3, t4, t5 = st.columns([2.4, 1.3, 0.8, 0.8, 1.2], vertical_alignment="center")
        with t1:
            if active_hashtag:
                st.markdown(
                    '<div style="display:flex; align-items:center; gap:10px;">'
                    '<h4 style="margin:0 !important;">Video explorer</h4>'
                    f'<span class="badge" style="background:#e8f1fc;color:#1c5cab;">'
                    f'Filtered by #{active_hashtag}</span></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown("#### Video explorer")
        with t2:
            sort_by = st.selectbox(
                "Sort by",
                ["View Count", "Like Count", "Popular Score", "Growth Score", "View Growth"],
                label_visibility="collapsed",
            )
        with t3:
            page_size = st.selectbox("Rows", [25, 50, 100], label_visibility="collapsed")
        with t4:
            n_pages = max(1, -(-n_rows // page_size))
            page_num = st.number_input(
                "Page", min_value=1, max_value=n_pages, value=1, step=1,
                label_visibility="collapsed",
            )
        with t5:
            st.download_button(
                "Download CSV",
                data=vids_table.to_csv(index=False).encode("utf-8"),
                file_name="filtered_videos.csv",
                mime="text/csv",
                width="stretch",
            )

        sort_col = {
            "View Count": "view_count",
            "Like Count": "like_count",
            "Popular Score": "trending_score",
            "Growth Score": "virality_score",
            "View Growth": "views_growth_short",
        }[sort_by]

        table = vids_table.sort_values(sort_col, ascending=False).reset_index(drop=True)
        start = (page_num - 1) * page_size
        page_slice = table.iloc[start : start + page_size].copy()

        if page_slice.empty:
            st.info("No videos match the current filters.")
        else:
            def tag_row(row) -> str:
                tags = []
                if row["is_long_tail"]:
                    tags.append("Long-tail")
                if row["is_topup"]:
                    tags.append("Top-up")
                return ", ".join(tags)

            page_slice["tags"] = page_slice.apply(tag_row, axis=1)

            display_cols = {
                "video_url": "Link",
                "uploader": "Creator",
                "method_key": "Method",
                "primary_category": "Category",
                "view_count": "Views",
                "like_count": "Likes",
                "views_growth_short": "View Growth",
                "trending_score": "Popular",
                "virality_score": "Growth",
                "tags": "Tags",
            }
            col_config = {
                "Link": st.column_config.LinkColumn("Link", display_text="Open video"),
                "Views": st.column_config.NumberColumn("Views", format="localized"),
                "Likes": st.column_config.NumberColumn("Likes", format="localized"),
                "View Growth": st.column_config.NumberColumn(
                    "View Growth", format="localized",
                    help="Short-window view growth (views_growth_short)",
                ),
                "Popular": st.column_config.NumberColumn(
                    "Popular", format="%.2f",
                    help="Popular score (trending_score in the source data)",
                ),
                "Growth": st.column_config.NumberColumn(
                    "Growth", format="%.2f",
                    help="Growth score (virality_score in the source data)",
                ),
            }

            if load_thumbs:
                with st.spinner("Fetching thumbnails from TikTok..."):
                    thumbs = fetch_thumbnails(tuple(page_slice["video_url"].tolist()))
                page_slice["thumbnail"] = page_slice["video_url"].map(thumbs)
                display_cols = {"thumbnail": "Preview", **display_cols}
                col_config["Preview"] = st.column_config.ImageColumn("Preview", width="small")

            shown = page_slice[list(display_cols.keys())].rename(columns=display_cols)
            st.dataframe(
                shown,
                column_config=col_config,
                hide_index=True,
                width="stretch",
                height=min(660, 60 + 36 * len(shown)),
            )

        hashtag_note = f" Hashtag filter: #{active_hashtag}." if active_hashtag else ""
        st.caption(
            f"Showing {len(page_slice):,} of {n_rows:,} filtered rows "
            f"(page {page_num} of {n_pages}). Full dataset: {len(videos_df):,} rows."
            f"{hashtag_note}"
        )
