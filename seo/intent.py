"""How much a search is worth to us, beyond its volume.

The site earns from players who sign up at a casino, so a search by someone
choosing a casino or a bonus is worth far more than the same volume of
general crypto curiosity ("what is bitcoin", "xrp price"). Topics are ranked
by monthly impressions x intent weight, so a 300-impression "no kyc casino"
query beats a 1,000-impression "crypto wallet" one.
"""
import re

WEIGHTS = {
    "choose_casino": 1.0,   # best/top/review/alternative/legit, comparisons
    "bonus": 1.0,           # bonuses, codes, wagering, free spins
    "play": 0.9,            # how to deposit/withdraw/play at a crypto casino
    "game_guide": 0.7,      # how Mines/Plinko/Crash/Dice work, strategy, RTP
    "other": 0.3,           # gambling-adjacent but weak
    "general_crypto": 0.05,  # crypto with no gambling angle: practically never picked
    "navigational": 0.0,    # looking for another site's login, app or official address: we cannot serve it
}

_CASINO = re.compile(r"casino|cassino|казино|stake|bc\.?game|shuffle|roobet|lumenbet|tazzoro|review|legit|"
                     r"alternative|vs\b|no.?kyc|без верификац|anonymous", re.I)
_GAMBLING = re.compile(r"gambl|betting|apuestas|apostas|ставк", re.I)
_BONUS = re.compile(r"bonus|bônus|бонус|free spin|wager|rollover|promo|code|cashback|rakeback|вейджер", re.I)
_PLAY = re.compile(r"deposit|withdraw|payout|cash ?out|вывод|депозит|saque|retiro|usdt|trc.?20", re.I)
_GAME = re.compile(r"crash|plinko|mines|dice|limbo|keno|slot|roulette|blackjack|baccarat|poker|jackpot|rtp|"
                   r"provably|house edge|краш|слот", re.I)


# Games people play for free with no money on the line. "minesweeper" contains
# "mines", so without this the free Windows game read as a casino game guide.
_NOT_GAMBLING = re.compile(r"minesweeper|solitaire|sudoku|tetris|chess|google (game|doodle)|"
                           r"unblocked|free online game|сапер", re.I)


# Someone trying to reach a specific site, not to read about it. These carried the biggest
# volumes in discovery ("usdt0 official website", "stake login") and kept topping the
# refresh list although no page of ours can answer them.
_NAVIGATIONAL = re.compile(r"\blog ?in\b|\bsign ?in\b|\bofficial\b|\bwebsite\b|\bweb ?site\b|\bapp\b|\bapk\b|\bdownload\b|"
                           r"customer (service|support)|\bвход\b|официальн|скачать|зеркало|\bentrar\b|iniciar sesi[oó]n|"
                           r"\.(com|io|us|net|org|today|bet)\b", re.I)
# Crypto with no gambling angle. "usdt0" is a token of its own, not Tether on TRON: it
# matched the deposit pattern below and read as casino-payment intent.
_GENERAL = re.compile(r"\busdt0\b|\bprice\b|\bprecio\b|\bpreço\b|\bкурс\b|\bwallet\b|кошел[её]к|\bairdrop\b|\bstaking\b|"
                      r"\bmining\b|\bexchange\b|how to buy|what is (a )?(bitcoin|crypto|usdt|tether|ethereum|blockchain)", re.I)


def classify(q):
    """Heuristic intent for rows that do not carry one (older rows, manual adds)."""
    if _NAVIGATIONAL.search(q):
        return "navigational"
    if _GENERAL.search(q) and not (_CASINO.search(q) or _GAMBLING.search(q) or _BONUS.search(q)):
        return "general_crypto"
    if _NOT_GAMBLING.search(q) and not (_CASINO.search(q) or _GAMBLING.search(q)):
        return "other"
    if _BONUS.search(q):
        return "bonus"
    if _CASINO.search(q):
        return "choose_casino"
    if _PLAY.search(q):
        return "play"
    if _GAME.search(q):
        return "game_guide"
    if _GAMBLING.search(q):
        return "choose_casino"  # "crypto gambling", "bitcoin betting": someone picking where to play
    return "general_crypto"


def score(row):
    intent = row.get("intent") or classify(row.get("q", ""))
    return (row.get("impressions") or 0) * WEIGHTS.get(intent, 0.3)


def queries_score(queries, impressions):
    """Weight a merged group by the share of its queries worth having."""
    if not queries:
        return 0.0
    w = sum(WEIGHTS[classify(q)] for q in queries) / len(queries)
    return impressions * w


def worth_covering(queries):
    """The queries from a merged group that a page of ours could genuinely answer."""
    return [q for q in queries if WEIGHTS[classify(q)] >= 0.3]
