import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date
import requests
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# ─────────────────────────────────────────────
# 1. PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(page_title="YouTube Analytics Pro", layout="wide", page_icon="📊")

st.markdown("""
<style>
    /* Main background */
    .stApp { background-color: #f8f9fa; color: #111111; }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #e0e0e0;
    }

    /* Metric cards */
    div[data-testid="metric-container"] {
        background: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }

    /* Inputs */
    input, .stTextInput input {
        background-color: #ffffff !important;
        color: #111111 !important;
        border: 1px solid #cccccc !important;
        border-radius: 8px !important;
    }

    /* Buttons */
    .stButton > button {
        background: #ff0000;
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        padding: 8px 20px;
        transition: background 0.2s;
    }
    .stButton > button:hover { background: #cc0000; }

    /* Download button */
    .stDownloadButton > button {
        background: #ffffff;
        color: #111111;
        border: 1px solid #cccccc;
        border-radius: 8px;
    }

    /* Tables */
    .stDataFrame { border-radius: 12px; overflow: hidden; }

    /* Headings */
    h1, h2, h3 { color: #111111; }

    /* Expander */
    .streamlit-expanderHeader { background: #f0f0f0 !important; border-radius: 8px; }

    /* Info / error boxes */
    .stAlert { border-radius: 10px; }

    div[data-testid="stMetricValue"] { color: #cc0000; font-size: 1.6rem !important; }
    div[data-testid="stMetricDelta"] { font-size: 0.85rem !important; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 2. YOUTUBE API HELPERS
# ─────────────────────────────────────────────

BASE_URL = "https://www.googleapis.com/youtube/v3"

def get_channel_id(api_key: str, handle_or_id: str) -> str | None:
    """
    Accepts a channel ID (starts with UC), a @handle, or a legacy username.
    Returns the channel ID string or None on failure.
    """
    handle_or_id = handle_or_id.strip()

    # Already a channel ID
    if handle_or_id.startswith("UC"):
        return handle_or_id

    # Strip @ if present
    handle = handle_or_id.lstrip("@")

    # Try forHandle (YouTube Data API v3 supports this)
    resp = requests.get(f"{BASE_URL}/channels", params={
        "part": "id",
        "forHandle": handle,
        "key": api_key
    })
    data = resp.json()
    items = data.get("items", [])
    if items:
        return items[0]["id"]

    # Fall back to forUsername (legacy)
    resp = requests.get(f"{BASE_URL}/channels", params={
        "part": "id",
        "forUsername": handle,
        "key": api_key
    })
    data = resp.json()
    items = data.get("items", [])
    if items:
        return items[0]["id"]

    return None


@st.cache_data(ttl=300)
def fetch_channel_stats(api_key: str, channel_id: str) -> dict | None:
    """Fetch basic channel stats."""
    resp = requests.get(f"{BASE_URL}/channels", params={
        "part": "snippet,statistics,brandingSettings",
        "id": channel_id,
        "key": api_key
    })
    data = resp.json()
    items = data.get("items", [])
    if not items:
        return None
    item = items[0]
    stats = item.get("statistics", {})
    snippet = item.get("snippet", {})
    return {
        "title": snippet.get("title", "Unknown"),
        "description": snippet.get("description", ""),
        "country": snippet.get("country", "N/A"),
        "published_at": snippet.get("publishedAt", "")[:10],
        "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
        "subscribers": int(stats.get("subscriberCount", 0)),
        "views": int(stats.get("viewCount", 0)),
        "video_count": int(stats.get("videoCount", 0)),
    }


@st.cache_data(ttl=300)
def fetch_top_videos(api_key: str, channel_id: str, max_results: int = 10) -> pd.DataFrame:
    """Fetch the most recent/popular videos for a channel."""
    # Step 1: get upload playlist ID
    resp = requests.get(f"{BASE_URL}/channels", params={
        "part": "contentDetails",
        "id": channel_id,
        "key": api_key
    })
    data = resp.json()
    items = data.get("items", [])
    if not items:
        return pd.DataFrame()

    playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Step 2: get video IDs from uploads playlist
    resp = requests.get(f"{BASE_URL}/playlistItems", params={
        "part": "contentDetails",
        "playlistId": playlist_id,
        "maxResults": max_results,
        "key": api_key
    })
    pl_data = resp.json()
    video_ids = [i["contentDetails"]["videoId"] for i in pl_data.get("items", [])]

    if not video_ids:
        return pd.DataFrame()

    # Step 3: get stats for those videos
    resp = requests.get(f"{BASE_URL}/videos", params={
        "part": "snippet,statistics",
        "id": ",".join(video_ids),
        "key": api_key
    })
    v_data = resp.json()

    rows = []
    for v in v_data.get("items", []):
        s = v.get("statistics", {})
        rows.append({
            "Title": v["snippet"]["title"][:50] + ("…" if len(v["snippet"]["title"]) > 50 else ""),
            "Published": v["snippet"]["publishedAt"][:10],
            "Views": int(s.get("viewCount", 0)),
            "Likes": int(s.get("likeCount", 0)),
            "Comments": int(s.get("commentCount", 0)),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("Views", ascending=False)
    return df


@st.cache_data(ttl=300)
def fetch_competitor_stats(api_key: str, channel_ids: list[str]) -> pd.DataFrame:
    """Fetch stats for a list of channel IDs."""
    if not channel_ids:
        return pd.DataFrame()

    resp = requests.get(f"{BASE_URL}/channels", params={
        "part": "snippet,statistics",
        "id": ",".join(channel_ids),
        "key": api_key
    })
    data = resp.json()
    rows = []
    for item in data.get("items", []):
        s = item.get("statistics", {})
        rows.append({
            "Channel": item["snippet"]["title"],
            "Subscribers": int(s.get("subscriberCount", 0)),
            "Total Views": int(s.get("viewCount", 0)),
            "Videos": int(s.get("videoCount", 0)),
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# 3. PDF EXPORT
# ─────────────────────────────────────────────

YT_RED   = colors.HexColor("#FF0000")
YT_DARK  = colors.HexColor("#111111")
YT_GREY  = colors.HexColor("#f2f2f2")
YT_MID   = colors.HexColor("#666666")
WHITE    = colors.white

def create_pdf(stats: dict, video_df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=16*mm, bottomMargin=16*mm
    )

    base_styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ReportTitle", parent=base_styles["Normal"],
        fontSize=26, leading=32, textColor=YT_DARK,
        fontName="Helvetica-Bold", spaceAfter=2*mm
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=base_styles["Normal"],
        fontSize=11, textColor=YT_MID,
        fontName="Helvetica", spaceAfter=4*mm
    )
    section_style = ParagraphStyle(
        "Section", parent=base_styles["Normal"],
        fontSize=14, leading=18, textColor=YT_RED,
        fontName="Helvetica-Bold", spaceBefore=6*mm, spaceAfter=3*mm
    )
    body_style = ParagraphStyle(
        "Body", parent=base_styles["Normal"],
        fontSize=10, leading=15, textColor=YT_DARK,
        fontName="Helvetica"
    )
    small_style = ParagraphStyle(
        "Small", parent=base_styles["Normal"],
        fontSize=9, textColor=YT_MID, fontName="Helvetica"
    )
    label_style = ParagraphStyle(
        "Label", parent=base_styles["Normal"],
        fontSize=9, textColor=YT_MID, fontName="Helvetica", spaceAfter=1*mm
    )
    value_style = ParagraphStyle(
        "Value", parent=base_styles["Normal"],
        fontSize=20, leading=24, textColor=YT_DARK,
        fontName="Helvetica-Bold"
    )

    page_w = A4[0] - 36*mm   # usable width
    story  = []

    # ── HEADER ─────────────────────────────────────
    story.append(Paragraph("YouTube Analytics Report", title_style))
    story.append(Paragraph(
        f"Channel: <b>{stats.get('title', 'N/A')}</b> &nbsp;|&nbsp; Generated: {date.today().strftime('%d %B %Y')}",
        subtitle_style
    ))
    story.append(HRFlowable(width="100%", thickness=2, color=YT_RED, spaceAfter=6*mm))

    # ── KPI CARDS (3-column table) ──────────────────
    story.append(Paragraph("Channel Overview", section_style))

    def kpi_cell(label, value):
        return [
            Paragraph(label, label_style),
            Paragraph(value, value_style),
        ]

    kpi_data = [
        [kpi_cell("SUBSCRIBERS",  f"{stats['subscribers']:,}"),
         kpi_cell("TOTAL VIEWS",  f"{stats['views']:,}"),
         kpi_cell("VIDEOS UPLOADED", f"{stats['video_count']:,}")],
    ]

    col_w = page_w / 3
    kpi_table = Table(kpi_data, colWidths=[col_w, col_w, col_w])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,-1), YT_GREY),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [YT_GREY]),
        ("BOX",         (0,0), (0,0),  1, colors.HexColor("#e0e0e0")),
        ("BOX",         (1,0), (1,0),  1, colors.HexColor("#e0e0e0")),
        ("BOX",         (2,0), (2,0),  1, colors.HexColor("#e0e0e0")),
        ("LEFTPADDING",  (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING",   (0,0), (-1,-1), 8),
        ("BOTTOMPADDING",(0,0), (-1,-1), 10),
        ("ROUNDEDCORNERS", (0,0), (-1,-1), [6]),
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 4*mm))

    # Channel details row
    details_data = [[
        Paragraph(f"<b>Country:</b> {stats.get('country','N/A')}", body_style),
        Paragraph(f"<b>Channel since:</b> {stats.get('published_at','N/A')}", body_style),
    ]]
    details_table = Table(details_data, colWidths=[page_w/2, page_w/2])
    details_table.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
    ]))
    story.append(details_table)

    # ── ENGAGEMENT RATE ─────────────────────────────
    if not video_df.empty:
        avg_views = video_df["Views"].mean()
        avg_likes = video_df["Likes"].mean()
        avg_comments = video_df["Comments"].mean()
        eng_rate = (avg_likes / avg_views * 100) if avg_views > 0 else 0

        story.append(Paragraph("Engagement Summary", section_style))

        eng_data = [[
            kpi_cell("AVG VIEWS / VIDEO",    f"{avg_views:,.0f}"),
            kpi_cell("AVG LIKES / VIDEO",    f"{avg_likes:,.0f}"),
            kpi_cell("AVG COMMENTS / VIDEO", f"{avg_comments:,.0f}"),
            kpi_cell("LIKE / VIEW RATE",     f"{eng_rate:.2f}%"),
        ]]
        cw = page_w / 4
        eng_table = Table(eng_data, colWidths=[cw, cw, cw, cw])
        eng_table.setStyle(TableStyle([
            ("BACKGROUND",   (0,0), (-1,-1), YT_GREY),
            ("BOX",          (0,0), (0,0),  1, colors.HexColor("#e0e0e0")),
            ("BOX",          (1,0), (1,0),  1, colors.HexColor("#e0e0e0")),
            ("BOX",          (2,0), (2,0),  1, colors.HexColor("#e0e0e0")),
            ("BOX",          (3,0), (3,0),  1, colors.HexColor("#e0e0e0")),
            ("LEFTPADDING",  (0,0), (-1,-1), 10),
            ("RIGHTPADDING", (0,0), (-1,-1), 10),
            ("TOPPADDING",   (0,0), (-1,-1), 8),
            ("BOTTOMPADDING",(0,0), (-1,-1), 10),
        ]))
        story.append(eng_table)

    # ── TOP VIDEOS TABLE ────────────────────────────
    if not video_df.empty:
        story.append(Paragraph("Top Videos Performance", section_style))

        header = ["#", "Title", "Published", "Views", "Likes", "Comments"]
        tbl_data = [header]
        for i, (_, row) in enumerate(video_df.head(10).iterrows(), 1):
            tbl_data.append([
                str(i),
                Paragraph(str(row["Title"]), small_style),
                str(row["Published"]),
                f"{row['Views']:,}",
                f"{row['Likes']:,}",
                f"{row['Comments']:,}",
            ])

        col_widths = [8*mm, 75*mm, 22*mm, 24*mm, 20*mm, 24*mm]
        vid_table  = Table(tbl_data, colWidths=col_widths, repeatRows=1)
        vid_table.setStyle(TableStyle([
            # Header row
            ("BACKGROUND",   (0,0), (-1,0), YT_RED),
            ("TEXTCOLOR",    (0,0), (-1,0), WHITE),
            ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",     (0,0), (-1,0), 9),
            ("BOTTOMPADDING",(0,0), (-1,0), 6),
            ("TOPPADDING",   (0,0), (-1,0), 6),
            # Data rows
            ("FONTNAME",     (0,1), (-1,-1), "Helvetica"),
            ("FONTSIZE",     (0,1), (-1,-1), 9),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [WHITE, YT_GREY]),
            ("TOPPADDING",   (0,1), (-1,-1), 5),
            ("BOTTOMPADDING",(0,1), (-1,-1), 5),
            ("LEFTPADDING",  (0,0), (-1,-1), 5),
            ("RIGHTPADDING", (0,0), (-1,-1), 5),
            ("ALIGN",        (0,0), (0,-1), "CENTER"),
            ("ALIGN",        (3,0), (-1,-1), "RIGHT"),
            ("GRID",         (0,0), (-1,-1), 0.25, colors.HexColor("#dddddd")),
            ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(vid_table)

    # ── AI INSIGHTS ────────────────────────────────
    if not video_df.empty:
        story.append(PageBreak())
        story.append(Paragraph("AI-Powered Insights", section_style))
        story.append(HRFlowable(width="100%", thickness=1, color=YT_RED, spaceAfter=4*mm))

        insights = []

        if "Published" in video_df.columns and len(video_df) >= 2:
            dates    = pd.to_datetime(video_df["Published"]).sort_values()
            avg_gap  = (dates.max() - dates.min()).days / max(len(dates)-1, 1)
            if avg_gap > 7:
                insights.append(("🔴 Upload Consistency",
                    f"Your average upload gap is {avg_gap:.0f} days. "
                    "Posting weekly or more frequently significantly improves retention and growth."))
            else:
                insights.append(("✅ Upload Consistency",
                    f"You're uploading every {avg_gap:.0f} days on average — great cadence!"))

        eng_rate_val = (video_df["Likes"].mean() / video_df["Views"].mean() * 100) if video_df["Views"].mean() > 0 else 0
        if eng_rate_val < 2:
            insights.append(("🔴 Low Engagement Rate",
                f"Like/view ratio is {eng_rate_val:.2f}%. Healthy channels average 3–7%. "
                "Try stronger calls-to-action and A/B testing thumbnails."))
        elif eng_rate_val >= 5:
            insights.append(("✅ Strong Engagement",
                f"Engagement rate of {eng_rate_val:.2f}% is well above average — keep it up!"))
        else:
            insights.append(("🟡 Engagement Rate",
                f"Engagement rate is {eng_rate_val:.2f}%. "
                "There is room to grow with better CTAs and community interaction."))

        best = video_df.iloc[0]
        insights.append(("💡 Best Performing Video",
            f"'{best['Title']}' has {best['Views']:,} views. "
            "Analyse what made it successful and replicate those elements."))

        for heading, body in insights:
            insight_data = [[
                Paragraph(f"<b>{heading}</b>", body_style),
                Paragraph(body, body_style),
            ]]
            ins_tbl = Table(insight_data, colWidths=[50*mm, page_w - 50*mm])
            ins_tbl.setStyle(TableStyle([
                ("BACKGROUND",   (0,0), (0,0), YT_GREY),
                ("LEFTPADDING",  (0,0), (-1,-1), 8),
                ("RIGHTPADDING", (0,0), (-1,-1), 8),
                ("TOPPADDING",   (0,0), (-1,-1), 6),
                ("BOTTOMPADDING",(0,0), (-1,-1), 6),
                ("VALIGN",       (0,0), (-1,-1), "TOP"),
                ("GRID",         (0,0), (-1,-1), 0.25, colors.HexColor("#dddddd")),
            ]))
            story.append(ins_tbl)
            story.append(Spacer(1, 2*mm))

    # ── FOOTER ─────────────────────────────────────
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=YT_MID))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        f"Generated by YouTube Analytics Pro &nbsp;|&nbsp; {date.today().strftime('%d %B %Y')} &nbsp;|&nbsp; Data sourced from YouTube Data API v3",
        small_style
    ))

    doc.build(story)
    return buf.getvalue()


# ─────────────────────────────────────────────
# 4. SIDEBAR — API KEY & CHANNEL INPUT
# ─────────────────────────────────────────────

st.sidebar.title("📊 YT Analytics Pro")
st.sidebar.markdown("---")

api_key = st.sidebar.text_input(
    "🔑 YouTube API Key",
    type="password",
    placeholder="Paste your API key here",
    help="Get one free at console.cloud.google.com → YouTube Data API v3"
)

channel_input = st.sidebar.text_input(
    "📺 Your Channel",
    placeholder="@MrBeast  or  UC... ID",
    help="Enter your channel handle (e.g. @MrBeast) or full channel ID"
)

fetch_btn = st.sidebar.button("🔍 Load Channel", use_container_width=True)

st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Content Performance", "Audience Engagement", "AI Insights", "Competitors"]
)

# ─────────────────────────────────────────────
# 5. FETCH DATA ON BUTTON PRESS
# ─────────────────────────────────────────────

# Store in session state so data persists across page switches
if fetch_btn:
    if not api_key or not channel_input:
        st.sidebar.error("Please enter both your API key and channel.")
    else:
        with st.spinner("Fetching channel data..."):
            ch_id = get_channel_id(api_key, channel_input)
            if not ch_id:
                st.sidebar.error("Channel not found. Check the handle/ID and try again.")
            else:
                stats = fetch_channel_stats(api_key, ch_id)
                if not stats:
                    st.sidebar.error("Could not load channel stats. Check your API key.")
                else:
                    st.session_state["channel_id"] = ch_id
                    st.session_state["stats"] = stats
                    st.session_state["api_key"] = api_key
                    st.session_state["video_df"] = fetch_top_videos(api_key, ch_id)
                    st.sidebar.success(f"✅ Loaded: {stats['title']}")

# Grab from session state
stats = st.session_state.get("stats")
video_df = st.session_state.get("video_df", pd.DataFrame())
stored_api_key = st.session_state.get("api_key", "")
stored_channel_id = st.session_state.get("channel_id", "")

# ─────────────────────────────────────────────
# 6. HELPER — NO DATA STATE
# ─────────────────────────────────────────────

def no_data_prompt():
    st.info("👈 Enter your API key and channel handle in the sidebar, then click **Load Channel**.")
    st.markdown("""
    **Don't have an API key yet?**
    1. Go to [console.cloud.google.com](https://console.cloud.google.com)
    2. Create a project → Enable **YouTube Data API v3**
    3. Go to **Credentials → Create API Key**
    4. Paste it in the sidebar
    """)

# ─────────────────────────────────────────────
# 7. PAGES
# ─────────────────────────────────────────────

# ── DASHBOARD ──────────────────────────────
if page == "Dashboard":
    st.title("📊 Channel Overview")

    if not stats:
        no_data_prompt()
    else:
        # Channel header
        col_img, col_info = st.columns([1, 5])
        with col_img:
            if stats.get("thumbnail"):
                st.image(stats["thumbnail"], width=80)
        with col_info:
            st.subheader(stats["title"])
            st.caption(f"📍 {stats['country']}  •  🗓 Since {stats['published_at']}")

        st.markdown("---")

        # Key metrics
        c1, c2, c3 = st.columns(3)
        c1.metric("👥 Subscribers", f"{stats['subscribers']:,}")
        c2.metric("👁️ Total Views", f"{stats['views']:,}")
        c3.metric("🎬 Total Videos", f"{stats['video_count']:,}")

        st.markdown("---")

        # Views per video chart (from top videos)
        if not video_df.empty:
            st.subheader("📈 Views by Recent Video")
            fig = px.bar(
                video_df.head(10),
                x="Title", y="Views",
                color_discrete_sequence=["#ff4444"],
                template="plotly_white"
            )
            fig.update_layout(
                plot_bgcolor="#ffffff",
                paper_bgcolor="#ffffff",
                xaxis_tickangle=-30,
                margin=dict(b=120)
            )
            st.plotly_chart(fig, use_container_width=True)

        # Engagement ratio gauge
        if not video_df.empty:
            avg_likes = video_df["Likes"].mean()
            avg_views = video_df["Views"].mean()
            eng_rate = (avg_likes / avg_views * 100) if avg_views > 0 else 0

            st.subheader("💡 Estimated Engagement Rate (Likes / Views)")
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number",
                value=round(eng_rate, 2),
                number={"suffix": "%"},
                gauge={
                    "axis": {"range": [0, 15]},
                    "bar": {"color": "#ff4444"},
                    "steps": [
                        {"range": [0, 3], "color": "#f5f5f5"},
                        {"range": [3, 7], "color": "#ececec"},
                        {"range": [7, 15], "color": "#e0e0e0"},
                    ],
                    "threshold": {"line": {"color": "#111111", "width": 2}, "value": eng_rate}
                }
            ))
            fig_gauge.update_layout(
                paper_bgcolor="#ffffff",
                font_color="#111111",
                height=280
            )
            st.plotly_chart(fig_gauge, use_container_width=True)

        # ── GENERATE PDF BUTTON ──────────────────────
        st.markdown("---")
        st.subheader("📄 Export Report")
        st.write("Download a full PDF report including channel stats, top video performance, and AI-powered insights.")

        col_btn, col_info = st.columns([2, 5])
        with col_btn:
            if st.button("⬇️ Generate PDF Report", use_container_width=True):
                with st.spinner("Building your report..."):
                    try:
                        pdf_bytes = create_pdf(stats, video_df)
                        safe_name = stats["title"].replace(" ", "_").replace("/", "_")
                        st.session_state["pdf_ready"] = pdf_bytes
                        st.session_state["pdf_filename"] = f"YouTube_Report_{safe_name}_{date.today()}.pdf"
                        st.success("✅ Report ready! Click Download below.")
                    except Exception as e:
                        st.error(f"PDF generation failed: {e}")

        if st.session_state.get("pdf_ready"):
            with col_btn:
                st.download_button(
                    label="📥 Download PDF",
                    data=st.session_state["pdf_ready"],
                    file_name=st.session_state.get("pdf_filename", "YouTube_Report.pdf"),
                    mime="application/pdf",
                    use_container_width=True
                )
        with col_info:
            st.info("The PDF includes: Channel overview · KPI cards · Engagement summary · Top 10 videos table · AI insights")


# ── CONTENT PERFORMANCE ────────────────────
elif page == "Content Performance":
    st.title("🎬 Content Performance")

    if not stats:
        no_data_prompt()
    elif video_df.empty:
        st.warning("No video data found for this channel.")
    else:
        st.subheader(f"Top {len(video_df)} Most Recent Videos")
        st.dataframe(
            video_df.style.format({
                "Views": "{:,}",
                "Likes": "{:,}",
                "Comments": "{:,}"
            }),
            use_container_width=True
        )

        st.markdown("---")

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Views Breakdown")
            fig = px.bar(
                video_df, x="Views", y="Title", orientation="h",
                color_discrete_sequence=["#ff4444"],
                template="plotly_white"
            )
            fig.update_layout(
                plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
                yaxis=dict(autorange="reversed"), height=400
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Likes vs Comments")
            fig2 = px.scatter(
                video_df, x="Likes", y="Comments", text="Title",
                color_discrete_sequence=["#ff4444"],
                template="plotly_white"
            )
            fig2.update_traces(textposition="top center", marker_size=10)
            fig2.update_layout(
                plot_bgcolor="#ffffff", paper_bgcolor="#ffffff", height=400
            )
            st.plotly_chart(fig2, use_container_width=True)

        # Best posting day
        if "Published" in video_df.columns:
            st.markdown("---")
            st.subheader("📅 Upload Day Distribution")
            video_df["Day"] = pd.to_datetime(video_df["Published"]).dt.day_name()
            day_counts = video_df["Day"].value_counts().reset_index()
            day_counts.columns = ["Day", "Count"]
            fig3 = px.bar(
                day_counts, x="Day", y="Count",
                color_discrete_sequence=["#3B82F6"],
                template="plotly_white"
            )
            fig3.update_layout(plot_bgcolor="#ffffff", paper_bgcolor="#ffffff")
            st.plotly_chart(fig3, use_container_width=True)


# ── AUDIENCE ENGAGEMENT ────────────────────
elif page == "Audience Engagement":
    st.title("👥 Audience Engagement")

    st.info(
        "ℹ️ **Note:** YouTube's API restricts demographic data (age, gender, geography) "
        "to channel owners via OAuth. The fields below let you enter your own data "
        "from YouTube Studio manually."
    )

    st.markdown("---")

    # ── Geographic ─────────────────────────
    st.subheader("🌍 Geographic Distribution")
    st.caption("Enter your top countries and their viewer percentages from YouTube Studio → Analytics → Audience.")

    geo_countries = []
    geo_pcts = []
    geo_cols = st.columns(5)
    defaults_country = ["United States", "United Kingdom", "Canada", "Australia", "India"]
    defaults_pct = [42, 18, 12, 8, 5]

    for i, col in enumerate(geo_cols):
        with col:
            c = col.text_input(f"Country {i+1}", value=defaults_country[i], key=f"geo_c_{i}")
            p = col.number_input(f"% {i+1}", min_value=0, max_value=100, value=defaults_pct[i], key=f"geo_p_{i}")
            geo_countries.append(c)
            geo_pcts.append(p)

    geo_df = pd.DataFrame({"Country": geo_countries, "Viewers %": geo_pcts})
    fig_geo = px.bar(
        geo_df, x="Viewers %", y="Country", orientation="h",
        color_discrete_sequence=["#3B82F6"], template="plotly_white"
    )
    fig_geo.update_layout(plot_bgcolor="#ffffff", paper_bgcolor="#ffffff", yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig_geo, use_container_width=True)

    st.markdown("---")

    # ── Age & Gender ───────────────────────
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🎂 Age Distribution")
        st.caption("Enter percentages from YouTube Studio → Audience.")
        age_labels = ["13-17", "18-24", "25-34", "35-44", "45-54", "55+"]
        age_defaults = [8, 28, 35, 18, 8, 3]
        age_vals = []
        for label, default in zip(age_labels, age_defaults):
            age_vals.append(st.slider(label, 0, 100, default, key=f"age_{label}"))
        age_df = pd.DataFrame({"Age": age_labels, "Value": age_vals})
        fig_age = px.pie(age_df, values="Value", names="Age", hole=0.5, template="plotly_white",
                         color_discrete_sequence=px.colors.sequential.Reds_r)
        fig_age.update_layout(paper_bgcolor="#ffffff")
        st.plotly_chart(fig_age, use_container_width=True)

    with col2:
        st.subheader("⚧ Gender Distribution")
        st.caption("Enter percentages from YouTube Studio → Audience.")
        male = st.slider("Male %", 0, 100, 62, key="gen_male")
        female = st.slider("Female %", 0, 100, 36, key="gen_female")
        other = max(0, 100 - male - female)
        st.caption(f"Other: {other}%")
        gen_df = pd.DataFrame({"Gender": ["Male", "Female", "Other"], "Value": [male, female, other]})
        fig_gen = px.pie(gen_df, values="Value", names="Gender", hole=0.5, template="plotly_white",
                         color_discrete_sequence=["#3B82F6", "#EC4899", "#6B7280"])
        fig_gen.update_layout(paper_bgcolor="#ffffff")
        st.plotly_chart(fig_gen, use_container_width=True)


# ── AI INSIGHTS ────────────────────────────
elif page == "AI Insights":
    st.title("🤖 AI-Powered Insights")

    if not stats or video_df.empty:
        no_data_prompt()
    else:
        recommendations = []

        # Analyse data to generate real recommendations
        avg_views = video_df["Views"].mean()
        avg_likes = video_df["Likes"].mean()
        avg_comments = video_df["Comments"].mean()
        eng_rate = (avg_likes / avg_views * 100) if avg_views > 0 else 0

        # Upload frequency
        if "Published" in video_df.columns and len(video_df) >= 2:
            dates = pd.to_datetime(video_df["Published"]).sort_values()
            avg_gap = (dates.max() - dates.min()).days / max(len(dates) - 1, 1)
            if avg_gap > 7:
                recommendations.append((
                    "🔴 High",
                    "Upload Consistency",
                    f"Your average upload gap is {avg_gap:.0f} days. "
                    "Channels posting weekly or more frequently see significantly better retention. "
                    "Try to post at least once a week."
                ))
            else:
                recommendations.append((
                    "🟢 Good",
                    "Upload Consistency",
                    f"You're uploading every {avg_gap:.0f} days on average. Keep it up!"
                ))

        # Engagement rate
        if eng_rate < 2:
            recommendations.append((
                "🔴 High",
                "Low Engagement Rate",
                f"Your like/view ratio is {eng_rate:.2f}%. A healthy rate is 3–7%. "
                "Consider stronger calls-to-action and engaging thumbnails."
            ))
        elif eng_rate >= 5:
            recommendations.append((
                "🟢 Good",
                "Strong Engagement",
                f"Your engagement rate is {eng_rate:.2f}% — well above average!"
            ))
        else:
            recommendations.append((
                "🟡 Medium",
                "Engagement Rate",
                f"Your engagement rate is {eng_rate:.2f}%. "
                "There's room to improve with better CTAs and community interaction."
            ))

        # Best performing video
        best = video_df.iloc[0]
        worst = video_df.iloc[-1]
        recommendations.append((
            "💡 Tip",
            f"Double Down on '{best['Title']}'",
            f"Your best video has {best['Views']:,} views. "
            "Analyse what made it successful (topic, title, thumbnail) and replicate those elements."
        ))

        # Comment engagement
        comment_ratio = (avg_comments / avg_views * 100) if avg_views > 0 else 0
        if comment_ratio < 0.1:
            recommendations.append((
                "🟡 Medium",
                "Boost Comments",
                f"Your comment rate is {comment_ratio:.2f}%. Ask questions in your videos "
                "and pin a comment to encourage discussion."
            ))

        # Show count
        high = sum(1 for r in recommendations if "🔴" in r[0])
        medium = sum(1 for r in recommendations if "🟡" in r[0])
        st.error(f"**{high} High Priority** · **{medium} Medium Priority** recommendations based on your live data")

        for priority, title, body in recommendations:
            with st.expander(f"{priority} — {title}", expanded=("🔴" in priority)):
                st.write(body)

        st.markdown("---")
        st.subheader("📊 Quick Stats Summary")
        s1, s2, s3 = st.columns(3)
        s1.metric("Avg Views / Video", f"{avg_views:,.0f}")
        s2.metric("Avg Likes / Video", f"{avg_likes:,.0f}")
        s3.metric("Avg Comments / Video", f"{avg_comments:,.0f}")


# ── COMPETITORS ────────────────────────────
elif page == "Competitors":
    st.title("⚔️ Competitor Analysis")

    if not stored_api_key:
        no_data_prompt()
    else:
        st.info("Enter up to 4 competitor channel IDs or @handles to compare.")

        comp_inputs = []
        cc = st.columns(4)
        for i, col in enumerate(cc):
            val = col.text_input(f"Competitor {i+1}", placeholder="@handle or UC...", key=f"comp_{i}")
            comp_inputs.append(val)

        if st.button("🔍 Compare Competitors"):
            ids_to_lookup = [v.strip() for v in comp_inputs if v.strip()]

            if not ids_to_lookup:
                st.warning("Enter at least one competitor.")
            else:
                with st.spinner("Looking up competitors..."):
                    resolved_ids = []
                    for handle in ids_to_lookup:
                        cid = get_channel_id(stored_api_key, handle)
                        if cid:
                            resolved_ids.append(cid)
                        else:
                            st.warning(f"Could not find: {handle}")

                    # Add your own channel
                    if stored_channel_id:
                        all_ids = [stored_channel_id] + resolved_ids
                    else:
                        all_ids = resolved_ids

                    comp_df = fetch_competitor_stats(stored_api_key, all_ids)

                    if not comp_df.empty:
                        # Highlight your channel
                        your_title = stats["title"] if stats else ""

                        st.markdown("---")
                        st.subheader("📋 Side-by-Side Comparison")
                        st.dataframe(
                            comp_df.style.format({
                                "Subscribers": "{:,}",
                                "Total Views": "{:,}",
                                "Videos": "{:,}"
                            }),
                            use_container_width=True
                        )

                        # Bar chart
                        fig = px.bar(
                            comp_df, x="Channel", y="Subscribers",
                            color_discrete_sequence=["#ff4444"],
                            template="plotly_white",
                            title="Subscribers Comparison"
                        )
                        fig.update_layout(plot_bgcolor="#ffffff", paper_bgcolor="#ffffff")
                        st.plotly_chart(fig, use_container_width=True)

                        # Ranking
                        if your_title:
                            rank_df = comp_df.sort_values("Subscribers", ascending=False).reset_index(drop=True)
                            rank_df.index += 1
                            your_rank = rank_df[rank_df["Channel"] == your_title].index
                            if len(your_rank) > 0:
                                st.info(f"📍 Your channel ranks **#{your_rank[0]}** out of {len(rank_df)} channels by subscribers.")
