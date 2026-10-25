/* Provably fair verification for StakeBet originals. No dependencies, runs offline.
 *
 * Mirrors the casino's server code exactly (checked against golden vectors
 * generated from it, see seo/test_pf.js):
 *   hash      = HMAC-SHA256(key = serverSeed, message = clientSeed + ":" + nonce)   (hex)
 *   hash2     = HMAC-SHA256(serverSeed, clientSeed + ":" + nonce + ":1")           (Plinko > 8 rows, Keno)
 *   commitment = SHA-256(serverSeed)                                              (the hash shown before play)
 *   Crash round = HMAC-SHA256(roundServerSeed, String(roundNumber))
 * Seeds are used as UTF-8 text exactly as shown, not hex-decoded.
 */
(function (root) {
  "use strict";

  // ── SHA-256 / HMAC-SHA256 (FIPS 180-4), byte arrays in, hex out ────────────
  var K = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];

  function utf8(str) {
    var out = [];
    for (var i = 0; i < str.length; i++) {
      var c = str.charCodeAt(i);
      if (c >= 0xd800 && c <= 0xdbff && i + 1 < str.length) {
        var d = str.charCodeAt(i + 1);
        if (d >= 0xdc00 && d <= 0xdfff) { c = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00); i++; }
      }
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
      else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return out;
  }

  function sha256Bytes(bytes) {
    var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var msg = bytes.slice();
    var bitLen = bytes.length * 8;
    msg.push(0x80);
    while (msg.length % 64 !== 56) msg.push(0);
    var hi = Math.floor(bitLen / 0x100000000), lo = bitLen >>> 0;
    msg.push((hi >>> 24) & 255, (hi >>> 16) & 255, (hi >>> 8) & 255, hi & 255,
             (lo >>> 24) & 255, (lo >>> 16) & 255, (lo >>> 8) & 255, lo & 255);
    var w = new Array(64);
    for (var off = 0; off < msg.length; off += 64) {
      for (var t = 0; t < 16; t++) {
        w[t] = (msg[off + 4 * t] << 24) | (msg[off + 4 * t + 1] << 16) | (msg[off + 4 * t + 2] << 8) | msg[off + 4 * t + 3];
      }
      for (t = 16; t < 64; t++) {
        var x = w[t - 15], y = w[t - 2];
        var s0 = ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3);
        var s1 = ((y >>> 17) | (y << 15)) ^ ((y >>> 19) | (y << 13)) ^ (y >>> 10);
        w[t] = (w[t - 16] + s0 + w[t - 7] + s1) | 0;
      }
      var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
      for (t = 0; t < 64; t++) {
        var S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + K[t] + w[t]) | 0;
        var S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0; H[2] = (H[2] + c) | 0; H[3] = (H[3] + d) | 0;
      H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0; H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0;
    }
    var out = [];
    for (var i = 0; i < 8; i++) out.push((H[i] >>> 24) & 255, (H[i] >>> 16) & 255, (H[i] >>> 8) & 255, H[i] & 255);
    return out;
  }

  function hex(bytes) {
    var s = "";
    for (var i = 0; i < bytes.length; i++) s += (bytes[i] < 16 ? "0" : "") + bytes[i].toString(16);
    return s;
  }

  function sha256(text) { return hex(sha256Bytes(utf8(text))); }

  function hmacSha256(key, message) {
    var k = utf8(key);
    if (k.length > 64) k = sha256Bytes(k);
    while (k.length < 64) k.push(0);
    var ipad = [], opad = [];
    for (var i = 0; i < 64; i++) { ipad.push(k[i] ^ 0x36); opad.push(k[i] ^ 0x5c); }
    var inner = sha256Bytes(ipad.concat(utf8(message)));
    return hex(sha256Bytes(opad.concat(inner)));
  }

  // ── Game derivations (identical arithmetic to the server) ──────────────────
  function u32(h, from) { return parseInt(h.substring(from, from + 8), 16); }

  function dice(h) {
    // 13 hex chars = 52 bits, exactly representable in a JS number
    return (parseInt(h.substring(0, 13), 16) % 10000) / 100;
  }

  function limbo(h, edge, max) {
    var v = u32(h, 0);
    if (v === 0) return max;
    var raw = (4294967296 / v) * (1 - edge);
    return Math.min(Math.max(raw, 1), max);
  }

  function coinflip(h) { return u32(h, 0) % 2 === 0 ? "HEADS" : "TAILS"; }

  function crash(h, edge) {
    var raw = (4294967296 / (u32(h, 0) + 1)) * (1 - edge);
    return Math.max(1, Math.min(raw, 1000));
  }

  function plinkoPath(fullHash, rows) {
    var path = [];
    for (var i = 0; i < rows; i++) path.push(u32(fullHash, i * 8) % 2);
    return path;
  }

  function mines(h, count, grid) {
    grid = grid || 25;
    var available = [], positions = [], current = h, offset = 0;
    for (var i = 0; i < grid; i++) available.push(i);
    for (i = 0; i < count; i++) {
      if (offset + 8 > current.length) { current = hmacSha256(current, String(i)); offset = 0; }
      var v = u32(current, offset);
      offset += 8;
      positions.push(available.splice(v % available.length, 1)[0]);
    }
    return positions.sort(function (a, b) { return a - b; });
  }

  function keno(fullHash, pool, count) {
    var nums = [];
    for (var i = 1; i <= pool; i++) nums.push(i);
    for (i = 0; i < count; i++) {
      var swap = (u32(fullHash, i * 8) % (pool - i)) + i;
      var t = nums[i]; nums[i] = nums[swap]; nums[swap] = t;
    }
    return nums.slice(0, count);
  }

  var EDGES = { dice: 0.02, limbo: 0.02, coinflip: 0.01, crash: 0.03, mines: 0.02, plinko: 0.02, keno: 0.04 };

  root.PF = {
    sha256: sha256, hmacSha256: hmacSha256,
    dice: dice, limbo: limbo, coinflip: coinflip, crash: crash,
    plinkoPath: plinkoPath, mines: mines, keno: keno, EDGES: EDGES,
    roundHashes: function (serverSeed, clientSeed, nonce) {
      return {
        hash: hmacSha256(serverSeed, clientSeed + ":" + nonce),
        hash2: hmacSha256(serverSeed, clientSeed + ":" + nonce + ":1")
      };
    }
  };
})(typeof window !== "undefined" ? window : this);
