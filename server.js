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

  let gold = null, silver = null, platinum = null;
  let bitcoin = null, ethereum = null;
  let usdInr = 83;

  // -------- FETCH FOREX --------
  try {
    const fx = await api.get("https://open.er-api.com/v6/latest/USD");
    usdInr = fx.data.rates.INR;
  } catch {}

  // -------- FETCH METALS --------
  try {
    const metals = await api.get("https://data-asg.goldprice.org/dbXRates/USD");
    const rates = metals.data.items[0];

    const OUNCE_TO_GRAM = 31.1035;

    gold = (rates.xauPrice * usdInr) / OUNCE_TO_GRAM;
    silver = (rates.xagPrice * usdInr) / OUNCE_TO_GRAM;
    platinum = (rates.xptPrice * usdInr) / OUNCE_TO_GRAM;
  } catch {}

  // -------- FETCH CRYPTO --------
  try {
    const crypto = await api.get(
      "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=inr"
    );

    bitcoin = crypto.data.bitcoin.inr;
    ethereum = crypto.data.ethereum.inr;
  } catch {}

  // -------- FINAL FALLBACK PER FIELD --------
  const data = {
    metals: {
      gold: gold || cache?.metals?.gold || 6000,
      silver: silver || cache?.metals?.silver || 75,
      platinum: platinum || cache?.metals?.platinum || 2500
    },
    crypto: {
      bitcoin: bitcoin || cache?.crypto?.bitcoin || 5000000,
      ethereum: ethereum || cache?.crypto?.ethereum || 300000
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

// root route
app.get("/", (req, res) => {
  res.send("Metalify API running 🚀 Use /prices");
});

app.listen(3000, () => console.log("🚀 Stable API running"));
