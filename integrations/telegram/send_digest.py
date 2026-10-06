#!/usr/bin/env python3
r"""
Telegram Digest Sender for Forger

Sends weekly bookmark digests via Telegram. Can be scheduled via cron.

Usage:
    python send_digest_telegram.py                    # Send digest for last 7 days
    python send_digest_telegram.py --days 14          # Send digest for last 14 days
    python send_digest_telegram.py --dry-run          # Generate but don't send
    python send_digest_telegram.py --format concise   # concise, full, or stats_only

Environment Variables:
    TELEGRAM_BOT_TOKEN - Your Telegram bot token
    TELEGRAM_CHAT_ID   - Target chat ID (user or group)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from forger.digest import generate_weekly_digest, WeeklyDigest


class TelegramFormatter:
    """Format digest for Telegram messages."""
    
    @staticmethod
    def escape_markdown(text: str | None) -> str:
        """Escape special characters for Telegram MarkdownV2."""
        if not text:
            return ""
        # Characters to escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
        chars_to_escape = r'_*[]()~`>#+-=|{}.!'
        for char in chars_to_escape:
            text = text.replace(char, '\\' + char)
        return text
    
    @staticmethod
    def truncate(text: str, max_len: int = 200) -> str:
        """Truncate text with ellipsis."""
        if len(text) <= max_len:
            return text
        return text[:max_len-3].rsplit(' ', 1)[0] + "..."
    
    @classmethod
    def format_concise(cls, digest: WeeklyDigest) -> str:
        """Format a concise digest for Telegram."""
        lines = []
        
        # Header
        week_start = digest.week_start.strftime("%b %d")
        week_end = digest.week_end.strftime("%b %d")
        week_range = cls.escape_markdown(f"{week_start} - {week_end}")
        lines.append("📚 *Forger Weekly Digest*")
        lines.append(f"📅 {week_range}")
        lines.append("")
        
        # Stats
        stats = digest.stats
        lines.append("📊 *Summary*")
        lines.append(f"• New bookmarks: {stats.total_new}")
        lines.append(f"• ⚡ Test this week: {stats.test_this_week}")
        lines.append(f"• 📚 Build later: {stats.build_later}")
        lines.append(f"• 📁 Archive: {stats.archive}")
        if stats.avg_priority_score > 0:
            lines.append(f"• Avg priority: {stats.avg_priority_score:.1f}/10")
        lines.append("")
        
        # Top 3 priority items
        if digest.test_this_week:
            lines.append("⚡ *Top Priority Items*")
            for i, item in enumerate(digest.test_this_week[:3], 1):
                title = cls.escape_markdown(cls.truncate(item.bookmark.title or item.bookmark.text, 50))
                priority = item.analysis.priority_score
                escaped_i = cls.escape_markdown(str(i))
                lines.append(f"{escaped_i}\\. [{title}]({item.bookmark.url})")
                lines.append(f"   Priority: {priority:.1f}")
                if item.action_items:
                    action = cls.escape_markdown(cls.truncate(item.action_items[0], 60))
                    lines.append(f"   👉 {action}")
                lines.append("")
        
        # Insights
        if digest.insights:
            lines.append("💡 *Insights*")
            for insight in digest.insights[:3]:
                # Remove emoji for cleaner look
                clean_insight = insight.lstrip("⚡📚📱✅🤔🎯💡📝 ")
                lines.append(f"• {cls.escape_markdown(clean_insight)}")
            lines.append("")
        
        # Trends
        if digest.trends.get('quality_trend'):
            trend = digest.trends['quality_trend']
            delta = digest.trends.get('quality_delta', 0)
            trend_emoji = "📈" if trend == 'up' else "📉" if trend == 'down' else "➡️"
            lines.append(f"{trend_emoji} *Trend:* Quality is {trend}")
            if delta != 0:
                lines.append(f"   Change: {delta:+.2f} vs historical avg")
        
        # Footer
        lines.append("")
        lines.append(f"_Generated: {digest.generated_at.strftime('%H:%M')}_")
        
        return "\n".join(lines)
    
    @classmethod
    def format_full(cls, digest: WeeklyDigest) -> list[str]:
        """Format full digest (may be split into multiple messages)."""
        messages = []
        
        # First message: Overview
        week_start = digest.week_start.strftime("%b %d")
        week_end = digest.week_end.strftime("%b %d")
        week_range = cls.escape_markdown(f"{week_start} - {week_end}")
        
        lines = [
            "📚 *Forger Weekly Digest*",
            f"📅 {week_range}",
            f"⏰ Generated: {digest.generated_at.strftime('%H:%M')}",
            "",
            "📊 *Statistics*",
            f"• Total new: {digest.stats.total_new}",
            f"• Analyzed: {digest.stats.analyzed}",
            f"• ⚡ Test this week: {digest.stats.test_this_week}",
            f"• 📚 Build later: {digest.stats.build_later}",
            f"• 📁 Archive: {digest.stats.archive}",
        ]
        
        if digest.stats.avg_worth_score > 0:
            lines.append(f"• Avg worth: {digest.stats.avg_worth_score:.1f}/10")
            lines.append(f"• Avg priority: {digest.stats.avg_priority_score:.1f}/10")
        
        if digest.stats.top_sources:
            lines.append("")
            lines.append("📱 *Top Sources*")
            for source, count in digest.stats.top_sources[:3]:
                lines.append(f"• {cls.escape_markdown(source)}: {count}")
        
        messages.append("\n".join(lines))
        
        # Second message: Test this week items
        if digest.test_this_week:
            lines = ["⚡ *Test This Week*", ""]
            for i, item in enumerate(digest.test_this_week[:5], 1):
                title = cls.escape_markdown(cls.truncate(item.bookmark.title or item.bookmark.text, 45))
                escaped_i = cls.escape_markdown(str(i))
                lines.append(f"*{escaped_i}\\.* [{title}]({item.bookmark.url})")
                lines.append(f"   Worth: {item.analysis.worth_score:.1f} | Priority: {item.analysis.priority_score:.1f}")
                if item.bookmark.tags:
                    tags = ", ".join(item.bookmark.tags[:3])
                    lines.append(f"   🏷 {cls.escape_markdown(tags)}")
                if item.action_items:
                    action = cls.escape_markdown(cls.truncate(item.action_items[0], 55))
                    lines.append(f"   👉 {action}")
                lines.append("")
            messages.append("\n".join(lines))
        
        # Third message: Build later items
        if digest.build_later:
            lines = ["📚 *Build Later*", ""]
            for i, item in enumerate(digest.build_later[:3], 1):
                title = cls.escape_markdown(cls.truncate(item.bookmark.title or item.bookmark.text, 50))
                escaped_i = cls.escape_markdown(str(i))
                lines.append(f"{escaped_i}\\. [{title}]({item.bookmark.url})")
                lines.append(f"   Priority: {item.analysis.priority_score:.1f}")
            lines.append("")
            if len(digest.build_later) > 3:
                more = len(digest.build_later) - 3
                lines.append(f"_\\+ {more} more items_")
            messages.append("\n".join(lines))
        
        # Fourth message: Insights and trends
        lines = []
        if digest.insights:
            lines.append("💡 *Insights*")
            for insight in digest.insights[:5]:
                clean_insight = insight.lstrip("⚡📚📱✅🤔🎯💡📝 ")
                lines.append(f"• {cls.escape_markdown(clean_insight)}")
            lines.append("")
        
        if digest.trends.get('quality_trend'):
            trend = digest.trends['quality_trend']
            delta = digest.trends.get('quality_delta', 0)
            trend_emoji = "📈" if trend == 'up' else "📉" if trend == 'down' else "➡️"
            lines.append(f"{trend_emoji} *Quality Trend:* {trend}")
            if delta != 0:
                lines.append(f"   Change: {delta:+.2f} vs historical average")
            
            if digest.trends.get('topic_distribution'):
                lines.append("")
                lines.append("📊 *Topic Distribution*")
                for topic, data in list(digest.trends['topic_distribution'].items())[:3]:
                    lines.append(f"• {topic}: {data['percentage']}%")
        
        if lines:
            messages.append("\n".join(lines))
        
        return messages
    
    @classmethod
    def format_stats_only(cls, digest: WeeklyDigest) -> str:
        """Format just the statistics."""
        week_start = digest.week_start.strftime("%b %d")
        week_end = digest.week_end.strftime("%b %d")
        stats = digest.stats
        
        week_range = cls.escape_markdown(f"{week_start}-{week_end}")
        lines = [
            f"📚 *Forger Digest* | {week_range}",
            "",
            f"📊 New: {stats.total_new} | ⚡ {stats.test_this_week} | 📚 {stats.build_later} | 📁 {stats.archive}",
        ]
        
        if stats.avg_priority_score > 0:
            lines.append(f"⭐ Avg priority: {stats.avg_priority_score:.1f}/10")
        
        if digest.trends.get('quality_trend'):
            trend_emoji = "📈" if digest.trends['quality_trend'] == 'up' else "📉"
            lines.append(f"{trend_emoji} Trend: {digest.trends['quality_trend']}")
        
        return "\n".join(lines)


async def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    """Send a message via Telegram Bot API."""
    try:
        import aiohttp
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": False,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                result = await response.json()
                if result.get("ok"):
                    return True
                else:
                    print(f"Telegram API error: {result.get('description')}")
                    return False
    except ImportError:
        print("Error: aiohttp not installed. Run: pip install aiohttp")
        return False
    except Exception as e:
        print(f"Error sending message: {e}")
        return False


def print_to_console(text: str, label: str = "Message") -> None:
    """Print formatted message to console."""
    print(f"\n{'='*50}")
    print(f"📨 {label}")
    print('='*50)
    print(text)
    print('='*50)


async def main_async() -> int:
    parser = argparse.ArgumentParser(
        description="Send Forger weekly digest via Telegram"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to include (default: 7)"
    )
    parser.add_argument(
        "--format",
        choices=["concise", "full", "stats_only"],
        default="concise",
        help="Output format (default: concise)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate but don't send to Telegram"
    )
    parser.add_argument(
        "--bot-token",
        default=os.getenv("TELEGRAM_BOT_TOKEN"),
        help="Telegram bot token (or set TELEGRAM_BOT_TOKEN env var)"
    )
    parser.add_argument(
        "--chat-id",
        default=os.getenv("TELEGRAM_CHAT_ID"),
        help="Telegram chat ID (or set TELEGRAM_CHAT_ID env var)"
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Also save digest to reports directory"
    )
    
    args = parser.parse_args()
    
    # Generate digest
    print(f"Generating {args.days}-day digest...")
    digest = generate_weekly_digest(days=args.days)
    
    # Format based on requested format
    formatter = TelegramFormatter()
    
    if args.format == "concise":
        message = formatter.format_concise(digest)
        messages = [message]
    elif args.format == "stats_only":
        message = formatter.format_stats_only(digest)
        messages = [message]
    else:  # full
        messages = formatter.format_full(digest)
    
    # Save if requested
    if args.save:
        from config.settings import REPORTS_DIR
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        
        week_start = digest.week_start.strftime("%Y%m%d")
        week_end = digest.week_end.strftime("%Y%m%d")
        
        # Save as markdown
        md_path = REPORTS_DIR / f"telegram_digest_{week_start}_{week_end}.md"
        full_text = "\n\n---\n\n".join(messages)
        md_path.write_text(full_text.replace('\\', '').replace('\\_', '_'), encoding="utf-8")
        print(f"✓ Saved to: {md_path}")
    
    # Send or print
    if args.dry_run:
        for i, msg in enumerate(messages, 1):
            print_to_console(msg, f"Message {i}/{len(messages)}")
        print(f"\n📝 Dry run complete. Would send {len(messages)} message(s).")
        return 0
    
    # Check for credentials
    if not args.bot_token or not args.chat_id:
        print("\n❌ Error: Telegram credentials not configured.")
        print("\nOptions:")
        print("1. Set environment variables:")
        print("   export TELEGRAM_BOT_TOKEN='your_bot_token'")
        print("   export TELEGRAM_CHAT_ID='your_chat_id'")
        print("\n2. Pass as arguments:")
        print("   python send_digest_telegram.py --bot-token TOKEN --chat-id ID")
        print("\n3. Use --dry-run to see output without sending")
        return 1
    
    # Send messages
    print(f"\nSending {len(messages)} message(s) to Telegram...")
    success_count = 0
    
    for i, msg in enumerate(messages, 1):
        print(f"  Sending message {i}/{len(messages)}...", end=" ")
        if await send_telegram_message(args.bot_token, args.chat_id, msg):
            print("✓")
            success_count += 1
        else:
            print("✗")
        
        # Small delay between messages
        if i < len(messages):
            await asyncio.sleep(0.5)
    
    print(f"\n✓ Sent {success_count}/{len(messages)} message(s) successfully.")
    return 0 if success_count == len(messages) else 1


def main() -> int:
    """Entry point."""
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
