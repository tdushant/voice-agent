"""Demo ledger and the fast path. No network, no model tokens."""

import copy
import re

# ponytail: keyword router. Swap in a parser if real callers phrase transfers differently.

SMALL = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

SEED = {
    "name": "Alex Morgan",
    "card": "active",
    "accounts": {
        "checking": {"mask": "4291", "cents": 428_016},
        "savings": {"mask": "8804", "cents": 1_264_000},
    },
    "txns": [
        {"account": "checking", "desc": "Payroll", "cents": 320_000},
        {"account": "checking", "desc": "Northline Mortgage", "cents": -184_250},
        {"account": "checking", "desc": "Netflix", "cents": -1_599},
        {"account": "checking", "desc": "Blue Bottle", "cents": -475},
        {"account": "savings", "desc": "Interest", "cents": 842},
    ],
    "pending": None,
}

CONFIRM = re.compile(
    r"^(yes|yeah|yep|confirm|confirmed|do it|go ahead|okay|ok|sure|yes please|please do)\.?$"
)
CANCEL = re.compile(r"^(no|nope|cancel|stop|never mind|nevermind)\.?$")
MONEY_RE = re.compile(r"\$?\b(\d{1,6})(?:\.(\d{1,2}))?\b")
DOLLAR_RE = re.compile(r"\$(\d[\d,]*)(?:\.(\d{1,2}))?")


def create_bank():
    return copy.deepcopy(SEED)


def format_usd(cents):
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def say_money(cents):
    negative = cents < 0
    cents = abs(cents)
    dollars, remainder = divmod(cents, 100)
    spoken = f"{dollars:,} dollar" + ("" if dollars == 1 else "s")
    if remainder:
        spoken += f" and {remainder} cent" + ("" if remainder == 1 else "s")
    return ("minus " if negative else "") + spoken


def norm(text):
    text = text.lower().replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9.\s$]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def words_to_int(text):
    total = 0
    cur = 0
    seen = False
    for word in text.split():
        if word in ("and", "dollars", "dollar", "bucks", "usd"):
            continue
        if word == "hundred":
            cur = (cur or 1) * 100
            seen = True
            continue
        if word == "thousand":
            cur = (cur or 1) * 1000
            total += cur
            cur = 0
            seen = True
            continue
        number = SMALL.get(word)
        if number is None:
            if seen:
                break
            continue
        if cur == 0:
            cur = number
            seen = True
            continue
        if number < 10 and cur >= 20 and cur % 10 == 0:
            cur += number
            continue
        if number >= 20 and cur % 100 == 0:
            cur += number
            continue
        break
    if not seen:
        return None
    return total + cur


def parse_cents(text):
    match = MONEY_RE.search(text.replace(",", ""))
    if match:
        cents = int(match.group(1)) * 100
        frac = match.group(2) or ""
        if len(frac) == 1:
            frac += "0"
        return cents + (int(frac) if frac else 0)
    number = words_to_int(text)
    if number is None:
        return None
    return number * 100


def _cents_of(match):
    dollars = int(match.group(1).replace(",", ""))
    frac = match.group(2) or ""
    if len(frac) == 1:
        frac += "0"
    return dollars * 100 + (int(frac) if frac else 0)


def scrub_amounts(speech, facts):
    """Drop dollar amounts the ledger did not provide."""
    allowed = {_cents_of(match) for match in DOLLAR_RE.finditer(facts)}

    def repl(match):
        cents = _cents_of(match)
        if cents in allowed:
            return match.group(0)
        if cents % 100 == 0 and any(cents // 100 == other // 100 for other in allowed):
            return match.group(0)
        return "the amount on your screen"

    return DOLLAR_RE.sub(repl, speech)


def snapshot(bank):
    checking = bank["accounts"]["checking"]["cents"]
    savings = bank["accounts"]["savings"]["cents"]
    latest = []
    for row in bank["txns"]:
        if row["account"] != "checking":
            continue
        sign = "+" if row["cents"] > 0 else "-"
        latest.append(f"{row['desc']} {sign}{format_usd(abs(row['cents']))}")
        if len(latest) == 3:
            break
    return (
        f"Alex Morgan. Checking 4291 {format_usd(checking)}. "
        f"Savings 8804 {format_usd(savings)}. Card {bank['card']}. "
        f"Latest checking: {'; '.join(latest)}."
    )


def public_state(bank):
    pending = bank["pending"]
    if pending and pending.get("ready"):
        hint = (
            f"Say confirm to move {format_usd(pending['cents'])} "
            f"from {pending['src']} to {pending['dst']}."
        )
    elif pending:
        hint = "Transfer in progress."
    else:
        hint = None
    accounts = []
    for key, label in (("checking", "Checking"), ("savings", "Savings")):
        acct = bank["accounts"][key]
        accounts.append({
            "name": label,
            "mask": acct["mask"],
            "cents": acct["cents"],
            "display": format_usd(acct["cents"]),
        })
    txns = []
    for row in bank["txns"][:6]:
        sign = "+" if row["cents"] > 0 else ""
        txns.append({
            "desc": row["desc"],
            "account": row["account"].capitalize(),
            "cents": row["cents"],
            "display": sign + format_usd(row["cents"]),
        })
    return {
        "name": bank["name"],
        "card": bank["card"],
        "accounts": accounts,
        "txns": txns,
        "pending": hint,
    }


def _hit(speech):
    return {"hit": True, "speech": speech}


def _named(text):
    return re.findall(r"\b(checking|savings)\b", text)


def _balance(bank, text):
    names = _named(text)
    checking = bank["accounts"]["checking"]["cents"]
    savings = bank["accounts"]["savings"]["cents"]
    if names == ["checking"]:
        return f"Your checking balance is {say_money(checking)}."
    if names == ["savings"]:
        return f"Your savings balance is {say_money(savings)}."
    return f"Checking has {say_money(checking)}. Savings has {say_money(savings)}."


def _activity(bank, text):
    names = _named(text)
    account = names[0] if len(names) == 1 else "checking"
    rows = [row for row in bank["txns"] if row["account"] == account][:3]
    if not rows:
        return f"No recent {account} activity."
    parts = []
    for row in rows:
        way = "in" if row["cents"] > 0 else "out"
        parts.append(f"{row['desc']}, {way} {say_money(abs(row['cents']))}")
    return f"Latest {account} activity: " + "; ".join(parts) + "."


def _ends(text):
    source = re.search(r"\bfrom\s+(?:my\s+)?(checking|savings)\b", text)
    dest = re.search(r"\b(?:to|into)\s+(?:my\s+)?(checking|savings)\b", text)
    src = source.group(1) if source else None
    dst = dest.group(1) if dest else None
    if not src and not dst:
        names = _named(text)
        if len(names) == 1:
            dst = names[0]
    if dst and not src:
        src = "savings" if dst == "checking" else "checking"
    if src and not dst:
        dst = "savings" if src == "checking" else "checking"
    return src, dst


def _ask(bank):
    pending = bank["pending"]
    if pending["cents"] is None:
        pending["ready"] = False
        if pending.get("dst"):
            return f"How much should I move to {pending['dst']}?"
        return "How much should I move?"
    if pending["cents"] <= 0:
        bank["pending"] = None
        return "Tell me an amount greater than zero."
    if not pending.get("src") or not pending.get("dst"):
        pending["ready"] = False
        return "Into checking or savings?"
    if pending["src"] == pending["dst"]:
        bank["pending"] = None
        return "Those are the same account. Nothing moved."
    have = bank["accounts"][pending["src"]]["cents"]
    if pending["cents"] > have:
        bank["pending"] = None
        return (
            f"{pending['src'].capitalize()} has {say_money(have)}, "
            f"so I can't move {say_money(pending['cents'])}."
        )
    pending["ready"] = True
    return (
        f"Move {say_money(pending['cents'])} from {pending['src']} "
        f"to {pending['dst']}. Say confirm."
    )


def _fill(bank, text):
    pending = bank["pending"]
    if not pending:
        return None
    changed = False
    if re.search(r"\d|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)\b", text):
        amount = parse_cents(text)
        if amount is not None:
            pending["cents"] = amount
            changed = True
    if re.search(r"\b(checking|savings)\b", text):
        src, dst = _ends(text)
        if dst and dst != pending.get("dst"):
            pending["dst"] = dst
            changed = True
        if src and not pending.get("src"):
            pending["src"] = src
            changed = True
        if dst and not pending.get("src"):
            pending["src"] = "savings" if dst == "checking" else "checking"
            changed = True
    if not changed:
        return None
    return _ask(bank)


def _execute(bank):
    pending = bank["pending"]
    src, dst, cents = pending["src"], pending["dst"], pending["cents"]
    bank["accounts"][src]["cents"] -= cents
    bank["accounts"][dst]["cents"] += cents
    bank["txns"].insert(0, {"account": dst, "desc": f"Transfer from {src}", "cents": cents})
    bank["txns"].insert(1, {"account": src, "desc": f"Transfer to {dst}", "cents": -cents})
    del bank["txns"][8:]
    left = bank["accounts"][src]["cents"]
    bank["pending"] = None
    return (
        f"Done. {say_money(cents)} is now in {dst}. "
        f"{src.capitalize()} has {say_money(left)} left."
    )


def _is_balance(text):
    if re.search(r"\bbalance\b", text):
        return True
    if re.search(r"\bhow much\b", text) and not re.search(r"\b(transfer|move|send|put|shift)\b", text):
        return True
    return bool(re.search(r"\b(what do i have|whats in)\b", text))


def _is_activity(text):
    return bool(re.search(r"\b(transaction|transactions|activity|charges|charge|spent|history|statement|purchases)\b", text))


def _is_unfreeze(text):
    return bool(re.search(r"\b(card|debit)\b", text) and re.search(r"\b(unfreeze|unlock|unblock|reactivate)\b", text))


def _is_freeze(text):
    return bool(re.search(r"\b(card|debit)\b", text) and re.search(r"\b(freeze|lock|block)\b", text))


def _is_transfer(text):
    return bool(re.search(r"\b(transfer|move|send|put|shift)\b", text))


def _clear(bank, speech):
    bank["pending"] = None
    return _hit(speech)


def handle(bank, raw):
    text = norm(raw or "")
    if not text:
        return _hit("I didn't catch that.")

    if _is_unfreeze(text):
        if bank["card"] == "active":
            return _clear(bank, "Your debit card is already active.")
        bank["card"] = "active"
        return _clear(bank, "Your debit card is active again.")
    if _is_freeze(text):
        if bank["card"] == "frozen":
            return _clear(bank, "Your debit card is already frozen.")
        bank["card"] = "frozen"
        return _clear(bank, "Your debit card is frozen. Say unlock my card to turn it back on.")
    if _is_activity(text):
        return _clear(bank, _activity(bank, text))
    if _is_balance(text):
        return _clear(bank, _balance(bank, text))
    if re.search(r"\b(help|what can you do|options|menu)\b", text):
        return _clear(bank, "You can ask for a balance, recent activity, a transfer, or to freeze your card.")
    if re.search(r"\b(hours|routing|branch)\b", text):
        return _clear(
            bank,
            "Branches are open weekdays from 9 to 5. The demo routing number is 0 2 6 0 0 9 5 9 3.",
        )
    if re.fullmatch(r"(bye|goodbye|thank you|thanks|thats all|that is all)\.?", text):
        return _clear(bank, "You're welcome. I can still check a balance or move money if you need it.")

    pending = bank["pending"]
    if pending and pending.get("ready") and CONFIRM.fullmatch(text):
        return _hit(_execute(bank))
    if pending and CANCEL.fullmatch(text):
        bank["pending"] = None
        return _hit("Canceled. Nothing moved.")
    if pending:
        filled = _fill(bank, text)
        if filled:
            return _hit(filled)

    if _is_transfer(text):
        src, dst = _ends(text)
        bank["pending"] = {"src": src, "dst": dst, "cents": parse_cents(text), "ready": False}
        return _hit(_ask(bank))

    if re.fullmatch(r"(hi|hello|hey|good morning|good afternoon|good evening)( there| alex)?\.?", text):
        return _hit(
            "Hi Alex. I can check a balance, recent activity, move money between your accounts, or freeze your card."
        )

    bank["pending"] = None
    return {"hit": False}
