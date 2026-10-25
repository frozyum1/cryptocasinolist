/* Bonus wagering calculator. No dependencies.
 *
 * Model (expected values, no variance):
 *   bonus        = min(deposit * match%, maxBonus)
 *   wagerTarget  = multiplier * (bonus | deposit + bonus)
 *   realStake    = wagerTarget / contribution        (a game counting 50% needs twice the bets)
 *   expectedCost = realStake * houseEdge
 *   value        = bonus - expectedCost              (what the bonus is worth on average)
 * Max cashout caps what a successful run can withdraw, so value is also capped by it.
 */
(function (root) {
  "use strict";

  function compute(i) {
    var bonus = Math.min(i.deposit * i.matchPct / 100, i.maxBonus > 0 ? i.maxBonus : Infinity);
    var base = i.base === "deposit+bonus" ? i.deposit + bonus : bonus;
    var target = i.multiplier * base;
    var contribution = Math.max(i.contributionPct, 0.0001) / 100;
    var realStake = target / contribution;
    var cost = realStake * i.edgePct / 100;
    var value = bonus - cost;
    if (i.maxCashout > 0) value = Math.min(value, i.maxCashout);
    var bets = i.betSize > 0 ? Math.ceil(realStake / i.betSize) : null;
    return {
      bonus: bonus,
      target: target,
      realStake: realStake,
      expectedCost: cost,
      value: value,
      bets: bets,
      betsPerDay: bets && i.days > 0 ? Math.ceil(bets / i.days) : null,
      overMaxBet: i.maxBet > 0 && i.betSize > i.maxBet,
      breakEvenEdgePct: realStake > 0 ? (bonus / realStake) * 100 : 0
    };
  }

  function fmt(n, d) {
    return n === null || !isFinite(n) ? "–" : n.toLocaleString("en-US", { maximumFractionDigits: d === undefined ? 2 : d });
  }

  function bind(form, out) {
    function num(name) { var v = parseFloat(form.elements[name].value); return isNaN(v) ? 0 : v; }
    function render() {
      var edgeSel = form.elements.game.value;
      var edge = edgeSel === "custom" ? num("customEdge") : parseFloat(edgeSel);
      form.querySelector("[data-custom-edge]").hidden = edgeSel !== "custom";
      var r = compute({
        deposit: num("deposit"), matchPct: num("match"), maxBonus: num("maxBonus"),
        multiplier: num("multiplier"), base: form.elements.base.value, edgePct: edge,
        contributionPct: num("contribution"), betSize: num("betSize"), maxBet: num("maxBet"),
        days: num("days"), maxCashout: num("maxCashout")
      });
      var cur = " " + (form.elements.currency.value || "USDT");
      out.querySelector("[data-bonus]").textContent = fmt(r.bonus) + cur;
      out.querySelector("[data-target]").textContent = fmt(r.target) + cur;
      out.querySelector("[data-stake]").textContent = fmt(r.realStake) + cur;
      out.querySelector("[data-cost]").textContent = fmt(r.expectedCost) + cur;
      out.querySelector("[data-value]").textContent = (r.value >= 0 ? "+" : "") + fmt(r.value) + cur;
      out.querySelector("[data-bets]").textContent = r.bets ? fmt(r.bets, 0) + (r.betsPerDay ? " (" + fmt(r.betsPerDay, 0) + " a day)" : "") : "–";
      out.querySelector("[data-breakeven]").textContent = fmt(r.breakEvenEdgePct) + "%";
      var verdict = out.querySelector("[data-verdict]");
      verdict.className = "verdict " + (r.value > 0 ? "good" : "bad");
      verdict.textContent = r.value > 0
        ? "On average this bonus is worth about " + fmt(r.value) + cur + " on this game. Variance is large: many runs bust before finishing."
        : "On this game the wagering costs more than the bonus on average. Take it only if you would play this much anyway, or pick a lower-edge game.";
      var warn = out.querySelector("[data-warn]");
      warn.hidden = !r.overMaxBet;
    }
    form.addEventListener("input", render);
    form.addEventListener("change", render);
    document.querySelectorAll("[data-fill]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var d = btn.dataset;
        ["match", "maxBonus", "multiplier", "maxBet", "days"].forEach(function (k) {
          if (d[k.toLowerCase()] !== undefined) form.elements[k].value = d[k.toLowerCase()];
        });
        if (d.mindeposit && num("deposit") < parseFloat(d.mindeposit)) form.elements.deposit.value = d.mindeposit;
        form.elements.base.value = d.base || "bonus";
        render();
      });
    });
    render();
  }

  root.Wager = { compute: compute, bind: bind };
})(typeof window !== "undefined" ? window : this);
