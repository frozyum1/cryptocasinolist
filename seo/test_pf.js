// Checks static/js/pf.js against golden vectors generated from StakeBet's server code.
// CI: `node seo/test_pf.js`. Locally without node: `python3 seo/run_js_test.py`.
var load = typeof require !== "undefined"
  ? function (p) { return require("fs").readFileSync(require("path").join(__dirname, "..", p), "utf8"); }
  : LOAD; // injected by run_js_test.py
var root = {};
(new Function("window", load("static/js/pf.js")))(root);
var PF = root.PF, g = JSON.parse(load("seo/pf-golden.json")), fails = 0, checks = 0;
function eq(name, got, want) {
  checks++;
  if (JSON.stringify(got) !== JSON.stringify(want)) { fails++; console.log("FAIL " + name + ": got " + JSON.stringify(got) + " want " + JSON.stringify(want)); }
}
eq("sha256", PF.sha256(g.serverSeed), g.sha256);
g.rounds.forEach(function (r) {
  var h = PF.roundHashes(g.serverSeed, g.clientSeed, r.nonce), n = "nonce " + r.nonce + " ";
  eq(n + "hash", h.hash, r.hash);
  eq(n + "hash2", h.hash2, r.hash2);
  eq(n + "dice", PF.dice(h.hash), r.dice);
  eq(n + "limbo", PF.limbo(h.hash, 0.02, 1000), r.limbo);
  eq(n + "coin", PF.coinflip(h.hash), r.coin);
  eq(n + "plinko8", PF.plinkoPath(h.hash, 8), r.plinko8);
  eq(n + "plinko16", PF.plinkoPath(h.hash + h.hash2, 16), r.plinko16);
  eq(n + "mines3", PF.mines(h.hash, 3, 25), r.mines3);
  eq(n + "mines24", PF.mines(h.hash, 24, 25), r.mines24);
  eq(n + "keno", PF.keno(h.hash + h.hash2, 40, 10), r.keno);
});
var ch = PF.hmacSha256(g.serverSeed, String(g.crash.round));
eq("crash hash", ch, g.crash.hash);
eq("crash point", PF.crash(ch, 0.03), g.crash.point);
// Wagering calculator: hand-checked cases
(new Function("window", load("static/js/wager.js")))(root);
var W = root.Wager;
function wc(over) { var b = {deposit: 100, matchPct: 100, maxBonus: 0, multiplier: 30, base: "bonus", edgePct: 1, contributionPct: 100, betSize: 0, maxBet: 0, days: 0, maxCashout: 0}; for (var k in over) b[k] = over[k]; return W.compute(b); }
var r1 = wc({});
eq("wager basic", [r1.bonus, r1.target, r1.realStake, r1.expectedCost, r1.value], [100, 3000, 3000, 30, 70]);
var r2 = wc({matchPct: 250, maxBonus: 250, edgePct: 2});
eq("wager 250% cap", [r2.bonus, r2.target, r2.expectedCost, r2.value], [250, 7500, 150, 100]);
var r3 = wc({base: "deposit+bonus"});
eq("wager deposit+bonus", r3.target, 6000);
var r4 = wc({contributionPct: 50});
eq("wager 50% contribution", [r4.realStake, r4.expectedCost], [6000, 60]);
var r5 = wc({maxCashout: 50});
eq("wager max cashout caps value", r5.value, 50);
var r6 = wc({betSize: 5, maxBet: 4, days: 7});
eq("wager bets and max bet", [r6.bets, r6.betsPerDay, r6.overMaxBet], [600, 86, true]);
eq("wager break-even edge", wc({}).breakEvenEdgePct, 100 / 3000 * 100);

console.log(checks + " checks, " + fails + " failed");
if (fails && typeof process !== "undefined") process.exit(1);
