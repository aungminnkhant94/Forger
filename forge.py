#!/usr/bin/env python3
"""
Forge CLI - Unified command-line interface for RolloForge

Usage:
    forge [COMMAND] [OPTIONS]

Commands:
    add <url>          Add a bookmark from URL
    stats              Show dashboard statistics
    digest             Generate weekly digest
    health             Run health checks
    search <query>     Search bookmarks
    export             Export data to various formats
    sync               Sync data to web dashboard
    config             Show/edit configuration

Examples:
    forge add https://x.com/user/status/123
    forge stats
    forge digest --send-telegram
    forge health --watch
    forge search "multi-agent"
    forge export --format json --output bookmarks.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rolloforge.storage import load_bookmarks, load_analysis_results
from rolloforge.digest import generate_weekly_digest
from config.settings import DATA_DIR, REPORTS_DIR, BASE_DIR

# ANSI colors
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    END = "\033[0m"
    BOLD = "\033[1m"


def color(text: str, color_code: str) -> str:
    """Apply color to text if terminal supports it."""
    if os.getenv("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"{color_code}{text}{Colors.END}"


def print_header(title: str) -> None:
    """Print a styled header."""
    width = 60
    print()
    print(color("=" * width, Colors.CYAN))
    print(color(f"  {title}", Colors.BOLD + Colors.CYAN))
    print(color("=" * width, Colors.CYAN))


def print_success(message: str) -> None:
    """Print a success message."""
    print(f"{color('✓', Colors.GREEN)} {message}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    print(f"{color('⚠', Colors.YELLOW)} {message}")


def print_error(message: str) -> None:
    """Print an error message."""
    print(f"{color('✗', Colors.RED)} {message}", file=sys.stderr)


def print_info(message: str) -> None:
    """Print an info message."""
    print(f"{color('ℹ', Colors.BLUE)} {message}")


# ============================================================================
# COMMAND: add
# ============================================================================
def cmd_add(args: argparse.Namespace) -> int:
    """Add a bookmark from URL."""
    from rolloforge.bookmark_workflow import process_bookmark_url

    url = args.url
    print_header("Adding Bookmark")
    print(f"URL: {url}")
    print()

    success, message, bookmark, analysis = process_bookmark_url(url, analyze=not getattr(args, "agent", False))

    if success:
        print_success("Bookmark saved successfully")
        print()
        print(f"  Title:    {bookmark.title[:60]}..." if bookmark.title and len(bookmark.title) > 60 else f"  Title:    {bookmark.title}")
        print(f"  Bucket:   {color(analysis.recommendation_bucket, Colors.YELLOW)}")
        print(f"  Priority: {analysis.priority_score:.1f}")
        print(f"  Tags:     {', '.join(bookmark.tags[:5])}")
        print()
        print(message)

        if getattr(args, "agent", False):
            pending_dir = DATA_DIR / "pending"
            pending_dir.mkdir(parents=True, exist_ok=True)
            content_path = pending_dir / f"{bookmark.id}.content.md"
            content_path.write_text(
                f"# {bookmark.title}\n\nURL: {bookmark.url}\n\n{bookmark.text}\n",
                encoding="utf-8",
            )
            print()
            print_info(f"Agent mode: content saved to {content_path}")
            print_info(
                "Write your analysis JSON to "
                f"{pending_dir / (bookmark.id + '.analysis.json')} then run: "
                f"python forge resolve {bookmark.id}"
            )
    else:
        print_error(message)
        return 1

    return 0


# ============================================================================
# COMMAND: stats
# ============================================================================
def cmd_stats(args: argparse.Namespace) -> int:
    """Show dashboard statistics."""
    bookmarks = load_bookmarks()
    analyses = load_analysis_results()
    
    print_header("RolloForge Statistics")
    
    # Basic counts
    print(color("\n📊 Bookmark Counts", Colors.BOLD))
    print(f"  Total bookmarks:  {len(bookmarks)}")
    print(f"  With analysis:    {len(analyses)}")
    print(f"  Pending analysis: {max(0, len(bookmarks) - len(analyses))}")
    
    # Bucket distribution
    bucket_counts = {}
    for a in analyses:
        bucket = a.recommendation_bucket
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    
    print(color("\n📁 Bucket Distribution", Colors.BOLD))
    bucket_emojis = {
        "test_this_week": "⚡",
        "build_later": "📚",
        "archive": "📁",
        "ignore": "🗑️"
    }
    for bucket, count in sorted(bucket_counts.items(), key=lambda x: -x[1]):
        emoji = bucket_emojis.get(bucket, "📄")
        bar = "█" * min(count, 20)
        print(f"  {emoji} {bucket:20} {count:3} {bar}")
    
    # Average scores
    if analyses:
        avg_worth = sum(a.worth_score for a in analyses) / len(analyses)
        avg_priority = sum(a.priority_score for a in analyses) / len(analyses)
        avg_effort = sum(a.effort_score for a in analyses) / len(analyses)
        
        print(color("\n⭐ Average Scores", Colors.BOLD))
        print(f"  Worth:    {avg_worth:.1f}/10")
        print(f"  Priority: {avg_priority:.1f}/10")
        print(f"  Effort:   {avg_effort:.1f}/10")
    
    # Top tags
    tag_counts = {}
    for b in bookmarks:
        for tag in b.tags:
            if tag != "general":
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    
    if tag_counts:
        print(color("\n🏷️ Top Tags", Colors.BOLD))
        for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"  #{tag:20} {count}")
    
    # Recent activity
    if bookmarks:
        recent = sorted(bookmarks, key=lambda b: b.bookmarked_at or "", reverse=True)[:5]
        print(color("\n🕐 Recent Bookmarks", Colors.BOLD))
        for b in recent:
            title = b.title or b.text[:50]
            if len(title) > 50:
                title = title[:47] + "..."
            date = b.bookmarked_at[:10] if b.bookmarked_at else "Unknown"
            print(f"  [{date}] {title}")
    
    print()
    return 0


# ============================================================================
# COMMAND: digest
# ============================================================================
def cmd_digest(args: argparse.Namespace) -> int:
    """Generate weekly digest."""
    from rolloforge.digest_render import (
        render_html_digest,
        render_markdown_digest,
        save_digest,
        print_console_summary
    )
    
    print_header("Generating Weekly Digest")
    print(f"Period: Last {args.days} days")
    print()
    
    try:
        digest = generate_weekly_digest(days=args.days)
        
        if not args.quiet:
            print_console_summary(digest)
        
        # Render outputs
        html_content = None
        md_content = None
        
        if args.output in ("html", "both"):
            html_content = render_html_digest(digest)
        
        if args.output in ("md", "markdown", "both"):
            md_content = render_markdown_digest(digest)
        
        # Save to files
        if args.save:
            saved = save_digest(html_content, md_content, digest)
            print()
            for fmt, path in saved.items():
                print_success(f"Saved {fmt.upper()}: {path}")
        
        # Send to Telegram
        if args.send_telegram:
            print()
            print_info("Sending to Telegram...")
            
            # Import here to avoid circular imports
            from integrations.telegram.send_digest import main as send_main
            
            # Set up args for send_digest_telegram
            send_args = argparse.Namespace(
                days=args.days,
                format=args.telegram_format,
                dry_run=False,
                bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
                chat_id=os.getenv("TELEGRAM_CHAT_ID"),
                save=False
            )
            
            # Check credentials
            if not send_args.bot_token or not send_args.chat_id:
                print_warning("Telegram credentials not configured")
                print("  Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
                return 1
            
            result = send_main()
            if result == 0:
                print_success("Digest sent to Telegram")
            else:
                print_error("Failed to send digest to Telegram")
                return 1
        
        print()
        return 0
        
    except Exception as e:
        print_error(f"Failed to generate digest: {e}")
        import traceback
        traceback.print_exc()
        return 1


# ============================================================================
# COMMAND: resolve
# ============================================================================
def cmd_resolve(args: argparse.Namespace) -> int:
    """Ingest an agent-written analysis for a pending bookmark (agent mode)."""
    from rolloforge.bookmark_workflow import resolve_pending_analysis

    print_header("Resolving Pending Analysis")

    analysis_path = DATA_DIR / "pending" / f"{args.bookmark_id}.analysis.json"
    if not analysis_path.exists():
        print_error(f"Analysis file not found: {analysis_path}")
        return 1

    try:
        payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON in {analysis_path}: {e}")
        return 1

    success, message, analysis = resolve_pending_analysis(args.bookmark_id, payload)
    if not success:
        print_error(message)
        return 1

    print_success(message)

    for stale in (analysis_path, DATA_DIR / "pending" / f"{args.bookmark_id}.content.md"):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass

    return 0


# ============================================================================
# COMMAND: health
# ============================================================================
def cmd_health(args: argparse.Namespace) -> int:
    """Run health checks."""
    if args.watch:
        # Continuous monitoring mode
        import time
        try:
            while True:
                os.system("clear" if os.name != "nt" else "cls")
                result = run_health_check()
                print(f"\n{color('Last updated:', Colors.CYAN)} {datetime.now().strftime('%H:%M:%S')}")
                print(color(f"Refreshing in {args.interval}s... (Ctrl+C to exit)", Colors.YELLOW))
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n")
            return 0
    else:
        return run_health_check()


def run_health_check() -> int:
    """Execute health check and return exit code."""
    print_header("RolloForge Health Check")
    
    bookmarks = load_bookmarks()
    analyses = load_analysis_results()
    
    issues = []
    warnings = []
    
    # Check 1: Bookmark/Analysis parity
    print(color("\n1. Data Consistency", Colors.BOLD))
    if len(bookmarks) == len(analyses):
        print_success(f"All bookmarks analyzed ({len(bookmarks)})")
    else:
        diff = abs(len(bookmarks) - len(analyses))
        if diff <= 5:
            print_warning(f"{diff} bookmarks pending analysis")
            warnings.append(f"{diff} bookmarks without analysis")
        else:
            print_error(f"{diff} bookmarks without analysis")
            issues.append("Large analysis backlog")
    
    # Check 2: Git status
    print(color("\n2. Git Repository", Colors.BOLD))
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            if result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                print_warning(f"{len(lines)} uncommitted change(s)")
                warnings.append(f"{len(lines)} uncommitted changes")
            else:
                print_success("Working directory clean")
            
            # Check last push
            result = subprocess.run(
                ["git", "log", "origin/main..HEAD", "--oneline"],
                cwd=BASE_DIR,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0 and result.stdout.strip():
                commits = len(result.stdout.strip().split("\n"))
                print_warning(f"{commits} unpushed commit(s)")
                warnings.append(f"{commits} unpushed commits")
            else:
                print_success("All commits pushed")
    except Exception as e:
        print_error(f"Git check failed: {e}")
        issues.append("Git repository issue")
    
    # Check 3: Data files
    print(color("\n3. Data Files", Colors.BOLD))
    for filename in ["bookmarks_raw.json", "analysis_results.json", "seen_bookmarks.json"]:
        filepath = DATA_DIR / filename
        if filepath.exists():
            size_mb = filepath.stat().st_size / (1024 * 1024)
            if size_mb > 10:
                print_warning(f"{filename}: {size_mb:.1f}MB (large)")
            else:
                print_success(f"{filename}: {size_mb:.1f}MB")
        else:
            print_error(f"{filename}: MISSING")
            issues.append(f"Missing file: {filename}")
    
    # Check 4: Environment
    print(color("\n4. Environment", Colors.BOLD))
    required_vars = ["DEEPSEEK_API_KEY"]
    optional_vars = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    
    for var in required_vars:
        if os.getenv(var):
            print_success(f"{var}: set")
        else:
            print_error(f"{var}: NOT SET")
            issues.append(f"Missing required env var: {var}")
    
    for var in optional_vars:
        if os.getenv(var):
            print_success(f"{var}: set (optional)")
        else:
            print_info(f"{var}: not set (optional)")
    
    # Summary
    print()
    print("=" * 60)
    if issues:
        print(color(f"✗ Health Check Failed: {len(issues)} issue(s), {len(warnings)} warning(s)", Colors.RED))
        return 2
    elif warnings:
        print(color(f"⚠ Health Check Warning: {len(warnings)} warning(s)", Colors.YELLOW))
        return 1
    else:
        print(color("✓ Health Check Passed", Colors.GREEN))
        return 0


# ============================================================================
# COMMAND: search
# ============================================================================
def cmd_search(args: argparse.Namespace) -> int:
    """Search bookmarks."""
    query = args.query.lower()
    bookmarks = load_bookmarks()
    analyses = load_analysis_results()
    analysis_map = {a.bookmark_id: a for a in analyses}
    
    print_header(f"Search Results: \"{args.query}\"")
    
    results = []
    for b in bookmarks:
        score = 0
        matches = []
        
        # Search in title
        if b.title and query in b.title.lower():
            score += 10
            matches.append("title")
        
        # Search in text
        if query in b.text.lower():
            score += 5
            matches.append("text")
        
        # Search in tags
        for tag in b.tags:
            if query in tag.lower():
                score += 8
                matches.append("tag")
                break
        
        # Search in analysis
        if b.id in analysis_map:
            a = analysis_map[b.id]
            if query in a.summary.lower():
                score += 3
                matches.append("summary")
            for insight in a.key_insights:
                if query in insight.lower():
                    score += 2
                    matches.append("insight")
                    break
        
        if score > 0:
            results.append((score, b, analysis_map.get(b.id), matches))
    
    # Sort by score
    results.sort(key=lambda x: -x[0])
    
    if not results:
        print(f"\nNo results found for \"{args.query}\"")
        print("\nTry searching for:")
        # Suggest some tags
        all_tags = set()
        for b in bookmarks:
            all_tags.update(b.tags)
        common_tags = [t for t in all_tags if t != "general"][:5]
        for tag in common_tags:
            print(f"  • {tag}")
        return 0
    
    print(f"\nFound {len(results)} result(s):\n")
    
    for i, (score, b, a, matches) in enumerate(results[:args.limit], 1):
        title = b.title or b.text[:60]
        if len(title) > 60:
            title = title[:57] + "..."
        
        bucket = a.recommendation_bucket if a else "unknown"
        priority = a.priority_score if a else 0
        
        bucket_colors = {
            "test_this_week": Colors.GREEN,
            "build_later": Colors.YELLOW,
            "archive": Colors.BLUE,
            "ignore": Colors.RED
        }
        bucket_color = bucket_colors.get(bucket, Colors.END)
        
        print(f"{color(f'{i}.', Colors.BOLD)} {title}")
        print(f"   URL: {b.url}")
        print(f"   Bucket: {color(bucket, bucket_color)} | Priority: {priority:.1f} | Tags: {', '.join(b.tags[:3])}")
        print(f"   Matched in: {', '.join(matches)}")
        print()
    
    return 0


# ============================================================================
# COMMAND: export
# ============================================================================
def cmd_export(args: argparse.Namespace) -> int:
    """Export data to various formats."""
    bookmarks = load_bookmarks()
    analyses = load_analysis_results()
    
    print_header("Exporting Data")
    print(f"Format: {args.format}")
    print(f"Output: {args.output}")
    print()
    
    # Build export data
    export_data = []
    analysis_map = {a.bookmark_id: a for a in analyses}
    
    for b in bookmarks:
        item = {
            "id": b.id,
            "url": b.url,
            "title": b.title,
            "text": b.text,
            "source": b.source,
            "tags": b.tags,
            "bookmarked_at": b.bookmarked_at,
        }
        
        if b.id in analysis_map:
            a = analysis_map[b.id]
            item["analysis"] = {
                "summary": a.summary,
                "bucket": a.recommendation_bucket,
                "worth_score": a.worth_score,
                "priority_score": a.priority_score,
                "key_insights": a.key_insights,
            }
        
        export_data.append(item)
    
    # Export based on format
    if args.format == "json":
        output = json.dumps(export_data, indent=2, ensure_ascii=False)
    elif args.format == "csv":
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["URL", "Title", "Source", "Bucket", "Priority", "Tags", "Bookmarked At"])
        
        for item in export_data:
            bucket = item.get("analysis", {}).get("bucket", "")
            priority = item.get("analysis", {}).get("priority_score", "")
            writer.writerow([
                item["url"],
                item["title"] or "",
                item["source"],
                bucket,
                priority,
                ", ".join(item["tags"]),
                item["bookmarked_at"] or ""
            ])
        
        output = output.getvalue()
    elif args.format == "markdown":
        lines = ["# RolloForge Bookmarks Export\n"]
        lines.append(f"*Generated: {datetime.now().isoformat()}*\n")
        
        for item in export_data:
            title = item["title"] or item["url"]
            lines.append(f"## {title}\n")
            lines.append(f"- **URL:** {item['url']}")
            lines.append(f"- **Source:** {item['source']}")
            lines.append(f"- **Tags:** {', '.join(item['tags'])}")
            
            if "analysis" in item:
                a = item["analysis"]
                lines.append(f"- **Bucket:** {a['bucket']}")
                lines.append(f"- **Priority:** {a['priority_score']}")
                lines.append(f"\n**Summary:** {a['summary'][:200]}...")
            
            lines.append("")
        
        output = "\n".join(lines)
    else:
        print_error(f"Unknown format: {args.format}")
        return 1
    
    # Write output
    if args.output == "-":
        print(output)
    else:
        output_path = Path(args.output)
        output_path.write_text(output, encoding="utf-8")
        print_success(f"Exported {len(export_data)} bookmarks to {output_path}")
    
    return 0


# ============================================================================
# COMMAND: sync
# ============================================================================
def cmd_sync(args: argparse.Namespace) -> int:
    """Sync data to web dashboard (copies JSON into web/lib and web/public)."""
    print_header("Syncing to Web Dashboard")

    try:
        from rolloforge.dashboard_sync import sync_dashboard_data

        if sync_dashboard_data():
            print_success("bookmarks_raw.json + analysis_results.json -> web/lib + web/public")
        else:
            print_warning("Some files failed to sync (see log)")

        if args.push:
            print_info("Pushing to GitHub...")
            subprocess.run(["git", "add", "web/lib", "web/public"], cwd=BASE_DIR, capture_output=True)
            result = subprocess.run(
                ["git", "commit", "-m", "Sync dashboard data"], cwd=BASE_DIR, capture_output=True
            )
            result = subprocess.run(["git", "push"], cwd=BASE_DIR, capture_output=True)
            if result.returncode == 0:
                print_success("Pushed to GitHub")
            else:
                print_warning("Git push may have failed (no remote configured?)")

        print()
        print_info("Dashboard data updated. View it with: cd web && npm install && npm run dev")
        return 0

    except Exception as e:
        print_error(f"Sync failed: {e}")
        return 1


# ============================================================================
# COMMAND: config
# ============================================================================
def cmd_config(args: argparse.Namespace) -> int:
    """Show/edit configuration."""
    print_header("RolloForge Configuration")
    
    env_file = BASE_DIR / ".env"
    
    if args.show:
        print(color("\n📁 Project Paths", Colors.BOLD))
        print(f"  Base directory: {BASE_DIR}")
        print(f"  Data directory: {DATA_DIR}")
        print(f"  Reports directory: {REPORTS_DIR}")
        
        print(color("\n🔧 Environment Variables", Colors.BOLD))
        vars_to_show = [
            "DEEPSEEK_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "TELEGRAM_CHAT_ID",
            "X_USER_ACCESS_TOKEN",
            "X_USER_ID"
        ]
        
        for var in vars_to_show:
            value = os.getenv(var)
            if value:
                # Mask sensitive values
                if "TOKEN" in var or "KEY" in var:
                    display = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
                else:
                    display = value
                print(f"  {var}: {color(display, Colors.GREEN)}")
            else:
                print(f"  {var}: {color('(not set)', Colors.YELLOW)}")
        
        print(color("\n📊 Current Stats", Colors.BOLD))
        bookmarks = load_bookmarks()
        analyses = load_analysis_results()
        print(f"  Total bookmarks: {len(bookmarks)}")
        print(f"  Analyses: {len(analyses)}")
        
    elif args.edit:
        editor = os.getenv("EDITOR", "nano")
        subprocess.run([editor, str(env_file)])
    
    print()
    return 0


# ============================================================================
# MAIN
# ============================================================================
def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="forge",
        description="Forge CLI - Unified interface for RolloForge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  forge add https://x.com/user/status/123     Add a bookmark
  forge stats                                  Show statistics
  forge status                                 Show project status
  forge status --format html -o status.html    Generate HTML report
  forge digest --send-telegram                 Generate & send digest
  forge stale --send-telegram                  Alert on stale bookmarks
  forge health                                 Check system health
  forge search "multi-agent"                   Search bookmarks
  forge export --format json -o export.json    Export data
  forge sync --push                            Sync & push to GitHub

For more help on a command:
  forge <command> --help
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # add
    add_parser = subparsers.add_parser("add", help="Add a bookmark from URL")
    add_parser.add_argument("url", help="URL to bookmark")
    add_parser.add_argument(
        "--agent",
        action="store_true",
        help="Agent mode: save without an API key; content is written to data/pending/ for the agent to analyze, then resolved with `forge resolve`",
    )
    add_parser.set_defaults(func=cmd_add)

    # resolve
    resolve_parser = subparsers.add_parser("resolve", help="Ingest an agent-written analysis for a pending bookmark")
    resolve_parser.add_argument("bookmark_id", help="Bookmark id from `forge add --agent`")
    resolve_parser.set_defaults(func=cmd_resolve)
    
    # stats
    stats_parser = subparsers.add_parser("stats", help="Show dashboard statistics")
    stats_parser.set_defaults(func=cmd_stats)
    
    # digest
    digest_parser = subparsers.add_parser("digest", help="Generate weekly digest")
    digest_parser.add_argument("--days", type=int, default=7, help="Number of days (default: 7)")
    digest_parser.add_argument("--output", choices=["html", "md", "both"], default="both", help="Output format")
    digest_parser.add_argument("--save", action="store_true", help="Save to reports directory")
    digest_parser.add_argument("--send-telegram", action="store_true", help="Send via Telegram")
    digest_parser.add_argument("--telegram-format", choices=["concise", "full", "stats_only"], default="concise")
    digest_parser.add_argument("--quiet", action="store_true", help="Don't print summary")
    digest_parser.set_defaults(func=cmd_digest)
    
    # health
    health_parser = subparsers.add_parser("health", help="Run health checks")
    health_parser.add_argument("--watch", action="store_true", help="Continuous monitoring mode")
    health_parser.add_argument("--interval", type=int, default=30, help="Refresh interval in seconds (default: 30)")
    health_parser.set_defaults(func=cmd_health)
    
    # search
    search_parser = subparsers.add_parser("search", help="Search bookmarks")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    search_parser.set_defaults(func=cmd_search)
    
    # export
    export_parser = subparsers.add_parser("export", help="Export data")
    export_parser.add_argument("--format", choices=["json", "csv", "markdown"], default="json", help="Export format")
    export_parser.add_argument("-o", "--output", default="-", help="Output file (use - for stdout)")
    export_parser.set_defaults(func=cmd_export)
    
    # sync
    sync_parser = subparsers.add_parser("sync", help="Sync data to web dashboard")
    sync_parser.add_argument("--push", action="store_true", help="Also push to GitHub")
    sync_parser.set_defaults(func=cmd_sync)
    
    # config
    config_parser = subparsers.add_parser("config", help="Show/edit configuration")
    config_parser.add_argument("--show", action="store_true", default=True, help="Show configuration")
    config_parser.add_argument("--edit", action="store_true", help="Edit .env file")
    config_parser.set_defaults(func=cmd_config)
    
    return parser


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
