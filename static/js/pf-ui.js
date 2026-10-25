/* UI for /tools/provably-fair-verifier/. Formulas live in pf.js (tested in seo/test_pf.js). */
(function () {
  "use strict";
  var form = document.getElementById("pf-form");
  var out = document.getElementById("pf-out");
  var PF = window.PF;

  var EXAMPLE = {
    serverSeed: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    hash: "a8ae6e6ee929abea3afcfc5258c8ccd6f85273e0d4626d26c7279f3250f77c8e",
    clientSeed: "cryptocasinolist"
  };

  function val(name) { return form.elements[name].value; }
  function int(name, min, max) {
    var n = parseInt(val(name), 10);
    if (isNaN(n)) n = min;
    return Math.min(Math.max(n, min), max);
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function fix(n, d) { return (Math.floor(n * Math.pow(10, d)) / Math.pow(10, d)).toFixed(d); }

  function syncFields() {
    var game = val("game");
    form.querySelectorAll("[data-for]").forEach(function (el) {
      var f = el.getAttribute("data-for");
      el.hidden = f === "nonce" ? game === "crash" : f === "round" ? game !== "crash" : f !== game;
    });
  }

  function resultFor(game, serverSeed, clientSeed, nonce) {
    var h = PF.roundHashes(serverSeed, clientSeed, nonce);
    switch (game) {
      case "dice": return { hash: h.hash, result: PF.dice(h.hash).toFixed(2) };
      case "limbo": return { hash: h.hash, result: fix(PF.limbo(h.hash, PF.EDGES.limbo, 1000), 2) + "x" };
      case "coinflip": return { hash: h.hash, result: PF.coinflip(h.hash) === "HEADS" ? "Heads" : "Tails" };
      case "mines": return { hash: h.hash, result: "Mines on tiles " + PF.mines(h.hash, int("mines", 1, 24), 25).map(function (t) { return t + 1; }).join(", ") + " (1-25, left to right, top to bottom)" };
      case "plinko": {
        var rows = int("rows", 8, 16);
        var path = PF.plinkoPath(rows > 8 ? h.hash + h.hash2 : h.hash, rows);
        var slot = path.reduce(function (a, b) { return a + b; }, 0);
        return { hash: h.hash, result: "Slot " + slot + " of " + rows + " (path " + path.map(function (p) { return p ? "R" : "L"; }).join("") + ")" };
      }
      case "keno": return { hash: h.hash, result: "Drawn " + PF.keno(h.hash + h.hash2, 40, 10).join(", ") };
    }
  }

  function run() {
    var game = val("game");
    var serverSeed = val("serverSeed").trim();
    var shown = val("hash").trim().toLowerCase();
    var clientSeed = val("clientSeed").trim();
    if (!serverSeed) { alertBox("Paste the revealed server seed first."); return; }

    var commitment = PF.sha256(serverSeed);
    var commitHtml = "<b>SHA-256 of the server seed:</b> <span class=\"mono\">" + commitment + "</span><br>";
    if (shown) {
      commitHtml += commitment === shown
        ? "<span class=\"ok\">Matches the hash you were shown before playing.</span>"
        : "<span class=\"bad-text\">Does not match the hash you entered. Check for typos or a different seed pair.</span>";
    } else {
      commitHtml += "Enter the hash you were shown before playing to check the commitment.";
    }
    out.querySelector("[data-commit]").innerHTML = commitHtml;

    var rows = "";
    if (game === "crash") {
      var round = int("round", 0, Number.MAX_SAFE_INTEGER);
      var ch = PF.hmacSha256(serverSeed, String(round));
      rows = "<tr><th>Round</th><th>Hash</th><th>Crash point</th></tr><tr><td>" + round + "</td><td class=\"mono\">" + ch +
        "</td><td>" + fix(PF.crash(ch, PF.EDGES.crash), 2) + "x</td></tr>";
    } else {
      if (!clientSeed) { alertBox("Paste your client seed."); return; }
      var start = int("nonce", 0, Number.MAX_SAFE_INTEGER), count = int("count", 1, 50);
      rows = "<tr><th>Nonce</th><th>Hash</th><th>Result</th></tr>";
      for (var n = start; n < start + count; n++) {
        var r = resultFor(game, serverSeed, clientSeed, n);
        rows += "<tr><td>" + n + "</td><td class=\"mono\">" + r.hash + "</td><td>" + esc(r.result) + "</td></tr>";
      }
    }
    out.querySelector("[data-table]").innerHTML = rows;
    out.hidden = false;
  }

  function alertBox(msg) {
    out.querySelector("[data-commit]").innerHTML = "<span class=\"bad-text\">" + esc(msg) + "</span>";
    out.querySelector("[data-table]").innerHTML = "";
    out.hidden = false;
  }

  form.elements.game.addEventListener("change", function () { syncFields(); if (!out.hidden) run(); });
  document.getElementById("pf-run").addEventListener("click", run);
  document.getElementById("pf-example").addEventListener("click", function () {
    form.elements.serverSeed.value = EXAMPLE.serverSeed;
    form.elements.hash.value = EXAMPLE.hash;
    form.elements.clientSeed.value = EXAMPLE.clientSeed;
    form.elements.nonce.value = 0;
    run();
  });
  syncFields();
})();
