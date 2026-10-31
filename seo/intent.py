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
}

_CASINO = re.compile(r"casino|cassino|казино|stake|bc\.?game|shuffle|roobet|lumenbet|tazzoro|review|legit|"
                     r"alternative|vs\b|no.?kyc|без верификац|anonymous", re.I)
_GAMBLING = re.compile(r"gambl|betting|apuestas|apostas|ставк", re.I)
_BONUS = re.compile(r"bonus|bônus|бонус|free spin|wager|rollover|promo|code|cashback|rakeback|вейджер", re.I)
_PLAY = re.compile(r"deposit|withdraw|payout|cash ?out|вывод|депозит|saque|retiro|usdt|trc.?20", re.I)
_GAME = re.compile(r"crash|plinko|mines|dice|limbo|keno|slot|roulette|blackjack|baccarat|poker|jackpot|rtp|"
                   r"provably|house edge|краш|слот", re.I)


def classify(q):
    """Heuristic intent for rows that do not carry one (older rows, manual adds)."""
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
