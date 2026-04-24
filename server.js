const express = require("express");
const axios = require("axios");
const cors = require("cors");

const app = express();
app.use(cors());

const CACHE_TTL = 10000; // 10 sec
let cache = null;
let lastFetch = 0;

const api = axios.create({ timeout: 5000 });

app.get("/prices", async (req, res) => {
  const now = Date.now();

  // Serve cache if fresh
  if (cache && now - lastFetch < CACHE_TTL) {
    return res.json(cache);
  }

  try {
    const [crypto, metals, forex] = await Promise.allSettled([
      // Crypto (INR)
      api.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=inr"),

      // Metals (better source)
      api.get("https://data-asg.goldprice.org/dbXRates/USD"),

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
      const rates = metals.value.data.items[0];

      goldUSD = rates.xauPrice;
      silverUSD = rates.xagPrice;
      platinumUSD = rates.xptPrice;
    }

    // fallback to cache if needed
    goldUSD = goldUSD || cache?.goldUSD;
    silverUSD = silverUSD || cache?.silverUSD;
    platinumUSD = platinumUSD || cache?.platinumUSD;

    const OUNCE_TO_GRAM = 31.1035;

    const convert = (usd) =>
      usd ? (usd * usdInr) / OUNCE_TO_GRAM : null;

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
      updatedAt: new Date(),

      // raw backup
      goldUSD,
      silverUSD,
      platinumUSD
    };

    // Save cache
    cache = data;
    lastFetch = now;

    res.json(data);

  } catch (err) {
    // fallback (rare now)
    res.json(
      cache || {
        metals: {
          gold: 6000,
          silver: 75,
          platinum: 2500
        },
        crypto: {
          bitcoin: 5000000,
          ethereum: 300000
        },
        forex: {
          usdInr: 83
        },
        fallback: true,
        updatedAt: new Date()
      }
    );
  }
});

// homepage route
app.get("/", (req, res) => {
  res.send("Metalify API running 🚀 Use /prices");
});

app.listen(3000, () => console.log("🚀 Pro API running"));
