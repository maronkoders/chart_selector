"""Builds a monthly trading calendar (like a GitHub-style P&L heatmap) as HTML.

Each day cell shows net P/L and trade count for that day, colored:
- green  = net profit
- red    = net loss
- gray   = traded but net exactly $0.00
- white  = no trades that day
- dimmed = day belongs to the previous/next month (padding, shown for grid alignment only)
"""
import calendar as _calendar
import datetime as dt
import html


WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    """Returns (first_day_of_month, first_day_of_next_month)."""
    first_day = dt.date(year, month, 1)
    if month == 12:
        next_first = dt.date(year + 1, 1, 1)
    else:
        next_first = dt.date(year, month + 1, 1)
    return first_day, next_first


def build_month_grid(year: int, month: int) -> list[list[tuple[dt.date, bool]]]:
    """Returns a list of weeks; each week is a list of 7 (date, is_in_month) tuples.
    Weeks start on Monday, matching the reference layout.
    """
    first_day, next_first = month_bounds(year, month)
    days_in_month = (next_first - first_day).days
    leading = first_day.weekday()  # Monday = 0

    total_days = leading + days_in_month
    trailing = (7 - total_days % 7) % 7
    total_cells = total_days + trailing
    weeks_count = total_cells // 7

    grid = []
    current = first_day - dt.timedelta(days=leading)
    for _ in range(weeks_count):
        week = []
        for _ in range(7):
            week.append((current, current.month == month and current.year == year))
            current += dt.timedelta(days=1)
        grid.append(week)
    return grid


def build_calendar_html(
    daily_stats: dict,
    year: int,
    month: int,
    week_targets: list[int | None] | None = None,
    freq_label: str = "Trades",
) -> str:
    """daily_stats: {date_obj: {"pnl": float, "count": int}}

    week_targets: optional, one value per week row (same order as
    build_month_grid). When provided, the right-hand frequency column shows
    these *planned/suggested* values instead of summing actual trade counts
    — e.g. a Trading Plan's weekly cadence (3, 3, 2, 2...). A None entry
    means that week falls outside the plan's schedule, shown as "—".
    When week_targets is None entirely, falls back to actual trade counts
    (the original behavior).
    """
    grid = build_month_grid(year, month)

    header_cells = "".join(f'<div class="cs-cal-head">{label}</div>' for label in WEEKDAY_LABELS)
    header_cells += f'<div class="cs-cal-head cs-cal-freq-head">{html.escape(freq_label)}</div>'

    body_rows = []
    for week_idx, week in enumerate(grid):
        row_cells = []
        week_trade_count = 0

        for day, in_month in week:
            if not in_month:
                row_cells.append(
                    f'<div class="cs-cal-cell cs-cal-pad"><div class="cs-cal-daynum">{day.day}</div></div>'
                )
                continue

            stats = daily_stats.get(day, {"pnl": 0.0, "count": 0})
            pnl = stats["pnl"]
            count = stats["count"]
            week_trade_count += count

            if count == 0:
                css_class = "cs-cal-empty"
            elif pnl > 0:
                css_class = "cs-cal-win"
            elif pnl < 0:
                css_class = "cs-cal-loss"
            else:
                css_class = "cs-cal-flat"

            sign = "-" if pnl < 0 else ""
            amount = f"{sign}${abs(pnl):,.2f}"
            trades_label = "trade" if count == 1 else "trades"

            row_cells.append(
                f'<div class="cs-cal-cell {css_class}">'
                f'<div class="cs-cal-daynum">{day.day}</div>'
                f'<div class="cs-cal-amount">{html.escape(amount)}</div>'
                f'<div class="cs-cal-trades">{count} {trades_label}</div>'
                f'</div>'
            )

        # Weekly frequency summary cell, on the right of the row. Either the
        # plan's suggested cadence for this week, or (if no plan is active)
        # the actual sum of trades taken — never both at once.
        if week_targets is not None:
            target = week_targets[week_idx] if week_idx < len(week_targets) else None
            freq_display = "—" if target is None else str(target)
        else:
            freq_display = str(week_trade_count)

        row_cells.append(
            f'<div class="cs-cal-freq-cell"><div class="cs-cal-freq-num">{freq_display}</div></div>'
        )

        body_rows.append(f'<div class="cs-cal-row">{"".join(row_cells)}</div>')

    style = """
    <style>
    .cs-cal-wrapper { font-family: inherit; }
    .cs-cal-row {
        display: grid; grid-template-columns: repeat(7, 1fr) 90px;
        gap: 8px; margin-bottom: 8px; align-items: stretch;
    }
    .cs-cal-head {
        text-align: center; font-weight: 600; font-size: 0.85rem;
        color: #374151; padding-bottom: 4px;
    }
    .cs-cal-freq-head { color: #1F2937; font-weight: 700; }
    .cs-cal-cell {
        border: 1px solid #E5E7EB; border-radius: 8px; min-height: 92px;
        padding: 8px 10px; box-sizing: border-box; position: relative;
    }
    .cs-cal-daynum { font-size: 0.8rem; font-weight: 600; opacity: 0.85; }
    .cs-cal-amount {
        text-align: center; font-weight: 700; font-size: 1.1rem;
        margin-top: 18px;
    }
    .cs-cal-trades { text-align: center; font-size: 0.78rem; margin-top: 2px; opacity: 0.9; }
    .cs-cal-empty { background: #FFFFFF; color: #111827; }
    .cs-cal-win { background: #22C55E; color: #FFFFFF; border-color: #16A34A; }
    .cs-cal-loss { background: #E0435A; color: #FFFFFF; border-color: #C23349; }
    .cs-cal-flat { background: #9CA3AF; color: #FFFFFF; border-color: #6B7280; }
    .cs-cal-pad { background: #FAFAFA; color: #9CA3AF; border-color: #F0F0F0; min-height: 92px; }
    .cs-cal-freq-cell {
        min-height: 92px; border: 1px dashed #D1D5DB; border-radius: 8px;
        display: flex; align-items: center; justify-content: center;
        background: #F9FAFB; box-sizing: border-box;
    }
    .cs-cal-freq-num { font-size: 2.4rem; font-weight: 800; line-height: 1; color: #1F2937; }
    </style>
    """

    header_row = f'<div class="cs-cal-row">{header_cells}</div>'
    return style + '<div class="cs-cal-wrapper">' + header_row + "".join(body_rows) + "</div>"