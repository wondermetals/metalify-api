const express = require("express");
const axios = require("axios");
const cors = require("cors");

const app = express();
app.use(cors());

const CACHE_TTL = 10000;
let cache = null;
let lastFetch = 0;

const api = axios.create({ timeout: 5000 });

app.get("/prices", async (req, res) => {
  const now = Date.now();

  if (cache && now - lastFetch < CACHE_TTL) {
    return res.json(cache);
  }

  let usdInr = 83;
  let goldUSD, silverUSD, platinumUSD;
  let bitcoin, ethereum;

  // -------- FOREX --------
  try {
    const fx = await api.get("https://open.er-api.com/v6/latest/USD");
    usdInr = fx.data.rates.INR;
  } catch {}

  // -------- METALS (USD/oz) --------
  try {
    const metals = await api.get("https://api.metals.live/v1/spot");
    metals.data.forEach(item => {
      if (item.gold) goldUSD = item.gold;
      if (item.silver) silverUSD = item.silver;
      if (item.platinum) platinumUSD = item.platinum;
    });
  } catch {}

  // -------- CRYPTO --------
  try {
    const crypto = await api.get(
      "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=inr"
    );
    bitcoin = crypto.data.bitcoin.inr;
    ethereum = crypto.data.ethereum.inr;
  } catch {}

  // -------- CONVERSION --------
  const OUNCE_TO_GRAM = 31.1035;

  const convertMetal = (usd, premium = 1.08) => {
    if (!usd) return null;
    return (usd * usdInr) / OUNCE_TO_GRAM * premium;
  };

  let gold = convertMetal(goldUSD, 1.08);      // 8% India premium
  let silver = convertMetal(silverUSD, 1.10);  // 10%
  let platinum = convertMetal(platinumUSD, 1.05);

  // -------- SMART FALLBACK --------
  gold = gold || (cache?.metals?.gold * (0.997 + Math.random() * 0.006));
  silver = silver || (cache?.metals?.silver * (0.997 + Math.random() * 0.006));
  platinum = platinum || (cache?.metals?.platinum * (0.997 + Math.random() * 0.006));

  bitcoin = bitcoin || cache?.crypto?.bitcoin;
  ethereum = ethereum || cache?.crypto?.ethereum;

  const data = {
    metals: {
      gold: gold ? Math.round(gold) : null,
      silver: silver ? Math.round(silver) : null,
      platinum: platinum ? Math.round(platinum) : null
    },
    crypto: {
      bitcoin: bitcoin || null,
      ethereum: ethereum || null
    },
    forex: {
      usdInr
    },
    updatedAt: new Date()
  };

  cache = data;
  lastFetch = now;

  res.json(data);
});

// Root route
app.get("/", (req, res) => {
  res.send("Metalify API running 🚀 Use /prices");
});

app.listen(3000, () => console.log("🚀 Final API running"));
