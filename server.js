const express = require("express");
const axios = require("axios");
const cors = require("cors");

const app = express();
app.use(cors());

const CACHE_TTL = 10000; // 10 sec
let cache = null;
let lastFetch = 0;

const api = axios.create({ timeout: 4000 });

app.get("/prices", async (req, res) => {
  const now = Date.now();

  // Serve cached data
  if (cache && now - lastFetch < CACHE_TTL) {
    return res.json(cache);
  }

  try {
    const [crypto, metals, forex] = await Promise.allSettled([
      // Crypto prices (INR)
      api.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=inr"),

      // Metals (USD per ounce)
      api.get("https://api.metals.live/v1/spot"),

      // USD → INR
      api.get("https://api.exchangerate.host/latest?base=USD&symbols=INR")
    ]);

    // -------- FOREX --------
    let usdInr = forex.status === "fulfilled"
      ? forex.value.data.rates.INR
      : cache?.forex?.usdInr || 83;

    // -------- METALS --------
    let goldUSD, silverUSD, platinumUSD;

    if (metals.status === "fulfilled") {
      metals.value.data.forEach(item => {
        if (item.gold) goldUSD = item.gold;
        if (item.silver) silverUSD = item.silver;
        if (item.platinum) platinumUSD = item.platinum;
      });
    }

    // fallback if API fails
    goldUSD = goldUSD || cache?.goldUSD;
    silverUSD = silverUSD || cache?.silverUSD;
    platinumUSD = platinumUSD || cache?.platinumUSD;

    const OUNCE_TO_GRAM = 31.1035;

    const convert = (usd) =>
      usd ? (usd * usdInr) / OUNCE_TO_GRAM : null;

    // -------- FINAL DATA --------
    const data = {
      metals: {
        gold: convert(goldUSD),
        silver: convert(silverUSD),
        platinum: convert(platinumUSD)
      },
      crypto: {
        bitcoin: crypto.status === "fulfilled"
          ? crypto.value.data.bitcoin.inr
          : cache?.crypto?.bitcoin,
        ethereum: crypto.status === "fulfilled"
          ? crypto.value.data.ethereum.inr
          : cache?.crypto?.ethereum
      },
      forex: {
        usdInr
      },
      updatedAt: new Date()
    };

    // save cache
    cache = data;
    lastFetch = now;

    res.json(data);

  } catch (err) {
    // fallback if everything fails
    res.json(cache || { error: "API failed" });
  }
});

// Start server
app.listen(3000, () => console.log("🚀 API running"));
