"""Render and save weekly digests (HTML via Jinja templates, Markdown, console)."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from config.settings import REPORTS_DIR, TEMPLATES_DIR
from forger.digest import WeeklyDigest


def render_html_digest(digest: WeeklyDigest) -> str:
    """Render digest as HTML."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("digest.html.j2")

    week_start_str = digest.week_start.strftime("%b %d")
    week_end_str = digest.week_end.strftime("%b %d, %Y")
    week_range = f"{week_start_str} - {week_end_str}"

    return template.render(
        week_range=week_range,
        generated_at=digest.generated_at.strftime("%B %d, %Y at %H:%M"),
        stats=digest.stats,
        test_this_week=digest.test_this_week,
        build_later=digest.build_later,
        archive=digest.archive,
        trends=digest.trends,
        insights=digest.insights,
    )


def render_markdown_digest(digest: WeeklyDigest) -> str:
    """Render digest as Markdown."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("digest.md.j2")

    week_start_str = digest.week_start.strftime("%b %d")
    week_end_str = digest.week_end.strftime("%b %d, %Y")
    week_range = f"{week_start_str} - {week_end_str}"

    return template.render(
        week_range=week_range,
        generated_at=digest.generated_at.strftime("%B %d, %Y at %H:%M"),
        stats=digest.stats,
        test_this_week=digest.test_this_week,
        build_later=digest.build_later,
        archive=digest.archive,
        trends=digest.trends,
        insights=digest.insights,
    )


def save_digest(html_content: str | None, md_content: str | None, digest: WeeklyDigest) -> dict[str, Path]:
    """Save digest to reports directory."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    week_start_str = digest.week_start.strftime("%Y%m%d")
    week_end_str = digest.week_end.strftime("%Y%m%d")
    base_name = f"weekly_digest_{week_start_str}_{week_end_str}"

    saved_paths = {}

    if html_content:
        html_path = REPORTS_DIR / f"{base_name}.html"
        html_path.write_text(html_content, encoding="utf-8")
        saved_paths["html"] = html_path
        print(f"✓ Saved HTML: {html_path}")

    if md_content:
        md_path = REPORTS_DIR / f"{base_name}.md"
        md_path.write_text(md_content, encoding="utf-8")
        saved_paths["md"] = md_path
        print(f"✓ Saved Markdown: {md_path}")

    return saved_paths


def print_console_summary(digest: WeeklyDigest) -> None:
    """Print a brief summary to console."""
    week_start_str = digest.week_start.strftime("%b %d")
    week_end_str = digest.week_end.strftime("%b %d")

    print("\n" + "=" * 60)
    print("📚 ROLLOFORGE WEEKLY DIGEST")
    print(f"   {week_start_str} - {week_end_str}")
    print("=" * 60)

    print("\n📊 SUMMARY")
    print(f"   New bookmarks:     {digest.stats.total_new}")
    print(f"   Analyzed:          {digest.stats.analyzed}")
    print(f"   ⚡ Test this week: {digest.stats.test_this_week}")
    print(f"   📚 Build later:    {digest.stats.build_later}")
    print(f"   📁 Archive:        {digest.stats.archive}")

    if digest.stats.avg_worth_score > 0:
        print(f"\n   Avg worth score:   {digest.stats.avg_worth_score:.1f}/10")
        print(f"   Avg priority:      {digest.stats.avg_priority_score:.1f}/10")

    if digest.insights:
        print("\n💡 INSIGHTS")
        for insight in digest.insights[:5]:
            print(f"   {insight}")

    if digest.test_this_week:
        print("\n⚡ TOP PRIORITY ITEMS")
        for i, item in enumerate(digest.test_this_week[:3], 1):
            title = item.bookmark.title or item.bookmark.text[:50] + "..."
            print(f"   {i}. {title}")
            print(f"      Worth: {item.analysis.worth_score:.1f} | Priority: {item.analysis.priority_score:.1f}")
            if item.action_items:
                print(f"      → {item.action_items[0]}")

    if digest.trends.get("quality_trend"):
        trend = digest.trends["quality_trend"]
        delta = digest.trends.get("quality_delta", 0)
        print("\n📈 TRENDS")
        print(f"   Quality trend: {'📈 Up' if trend == 'up' else '📉 Down' if trend == 'down' else '➡️ Stable'}", end="")
        if delta != 0:
            print(f" ({delta:+.2f})")
        else:
            print()

    print("\n" + "=" * 60)
