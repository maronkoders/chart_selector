"""Maps a saved Trading Plan's *suggested* weekly trade cadence onto real
calendar weeks — this is the same "N trades per week" pattern shown on the
Trading Plan page's "Trade Frequency Distribution" section, not a count of
trades actually taken.

Kept separate from core/config.py since plan storage/CRUD already lives
there; this module only derives read-only scheduling info from a plan dict.
"""
import datetime as dt


def _week_capacities(weeks_in_duration: int, start_date: dt.date | None) -> list[int]:
    """Each week's usable trading-day capacity out of 7. Only the first week
    can be partial — it starts counting from `start_date`'s weekday rather
    than Monday, since you can't trade before the plan actually begins.
    Every other week is a full 7-day week.
    """
    if start_date is not None:
        first_week_capacity = 7 - start_date.weekday()  # Monday start -> 7; later in the week -> fewer
    else:
        first_week_capacity = 7
    return [first_week_capacity] + [7] * (weeks_in_duration - 1)


def compute_weekly_targets(plan_data: dict) -> list[int]:
    """Distributes trading_days across (challenge_duration * 4) weeks,
    weighted by each week's actual usable-day capacity — so a full 7-day
    week always gets at least as many trades as a shorter partial week
    (e.g. the first week, if the plan doesn't start on a Monday), instead
    of just front-loading the remainder onto the earliest weeks blindly.

    Uses the largest-remainder method: allocate the proportional floor to
    every week, then hand out the leftover trades one at a time to the
    weeks with the biggest fractional shortfall (ties favor fuller weeks),
    so the total still sums exactly to trading_days.
    """
    trading_days = int(plan_data.get("trading_days", 0))
    challenge_duration = int(plan_data.get("challenge_duration", 1))
    weeks_in_duration = challenge_duration * 4  # matches trading_plan.py's approximation

    if weeks_in_duration <= 0 or trading_days <= 0:
        return []

    start_date_str = plan_data.get("start_date")
    start_date = None
    if start_date_str:
        try:
            start_date = dt.datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            start_date = None

    capacities = _week_capacities(weeks_in_duration, start_date)
    total_capacity = sum(capacities)
    if total_capacity <= 0:
        return [0] * weeks_in_duration

    raw_shares = [trading_days * cap / total_capacity for cap in capacities]
    targets = [int(share) for share in raw_shares]  # proportional floor per week
    remainder = trading_days - sum(targets)

    # Hand out leftover trades to the weeks closest to rounding up next,
    # breaking ties toward the fuller week so partial weeks never overtake
    # a full week purely from remainder luck.
    order = sorted(
        range(weeks_in_duration),
        key=lambda i: (raw_shares[i] - targets[i], capacities[i]),
        reverse=True,
    )
    for i in order[:remainder]:
        targets[i] += 1

    return targets


def _plan_start_monday(plan_data: dict) -> dt.date | None:
    start_date_str = plan_data.get("start_date")
    if not start_date_str:
        return None
    try:
        start_date = dt.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    return start_date - dt.timedelta(days=start_date.weekday())


def get_week_target(monday_date: dt.date, plan_data: dict, weekly_targets: list[int] | None = None) -> int | None:
    """Returns the plan's suggested trade count for the week starting on
    `monday_date`, or None if that week falls outside the plan's schedule
    (before it starts, or past its final week).
    """
    plan_start_monday = _plan_start_monday(plan_data)
    if plan_start_monday is None:
        return None

    if weekly_targets is None:
        weekly_targets = compute_weekly_targets(plan_data)
    if not weekly_targets:
        return None

    week_index = (monday_date - plan_start_monday).days // 7
    if 0 <= week_index < len(weekly_targets):
        return weekly_targets[week_index]
    return None


def build_week_targets_for_grid(grid: list[list[tuple[dt.date, bool]]], plan_data: dict | None) -> list[int | None] | None:
    """Given a calendar month grid (from calendar_view.build_month_grid) and
    an active plan, returns one suggested-frequency value per week row
    (None where that week isn't covered by the plan). Returns None entirely
    if there's no plan, so callers can fall back to actual trade counts.
    """
    if not plan_data:
        return None

    weekly_targets = compute_weekly_targets(plan_data)
    if not weekly_targets:
        return None

    return [
        get_week_target(week[0][0], plan_data, weekly_targets)
        for week in grid
    ]