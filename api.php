<?php
header('Content-Type: application/json; charset=utf-8');
date_default_timezone_set('Asia/Kolkata');

$cacheFile = __DIR__ . '/cache_prices.json';
$cacheSeconds = 8;
$fuelCacheSeconds = 300;
$configPath = __DIR__ . '/config.php';
if (file_exists($configPath)) { require_once $configPath; }
$fuelApiKey = defined('INDIANAPI_KEY') ? INDIANAPI_KEY : (getenv('INDIANAPI_KEY') ?: '');

function respond($data, $statusCode = 200) {
    http_response_code($statusCode);
    echo json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function readCacheFile($path) {
    if (!file_exists($path)) {
        return null;
    }
    $raw = @file_get_contents($path);
    if ($raw === false || $raw === '') {
        return null;
    }
    $json = json_decode($raw, true);
    return is_array($json) ? $json : null;
}

function writeCacheFile($path, $data) {
    @file_put_contents($path, json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
}

function fetchText($url, $timeout = 15) {
    $userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36';

    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_CONNECTTIMEOUT => $timeout,
            CURLOPT_TIMEOUT => $timeout,
            CURLOPT_USERAGENT => $userAgent,
            CURLOPT_HTTPHEADER => [
                'Accept-Language: en-IN,en;q=0.9'
            ]
        ]);
        $body = curl_exec($ch);
        $error = curl_error($ch);
        $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($body === false || $status >= 400) {
            throw new Exception($error ?: "HTTP $status while fetching $url");
        }
        return $body;
    }

    $context = stream_context_create([
        'http' => [
            'method' => 'GET',
            'header' => "User-Agent: $userAgent\r\nAccept-Language: en-IN,en;q=0.9\r\n",
            'timeout' => $timeout
        ]
    ]);

    $body = @file_get_contents($url, false, $context);
    if ($body === false) {
        throw new Exception("Could not fetch $url");
    }
    return $body;
}

function fetchJson($url, $timeout = 15) {
    $text = fetchText($url, $timeout);
    $json = json_decode($text, true);
    if (!is_array($json)) {
        throw new Exception("Invalid JSON from $url");
    }
    return $json;
}

function fetchJsonWithHeaders($url, $headers = [], $timeout = 15) {
    $userAgent = 'Metalify/1.0';
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_CONNECTTIMEOUT => $timeout,
            CURLOPT_TIMEOUT => $timeout,
            CURLOPT_USERAGENT => $userAgent,
            CURLOPT_HTTPHEADER => array_merge(['Accept: application/json'], $headers)
        ]);
        $body = curl_exec($ch);
        $error = curl_error($ch);
        $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        if ($body === false || $status >= 400) {
            throw new Exception($error ?: "HTTP $status while fetching $url");
        }
        $json = json_decode($body, true);
        if (!is_array($json)) throw new Exception('Invalid JSON response.');
        return $json;
    }
    $context = stream_context_create(['http' => [
        'method' => 'GET',
        'header' => implode("\r\n", $headers),
        'timeout' => $timeout
    ]]);
    $body = @file_get_contents($url, false, $context);
    if ($body === false) throw new Exception("Could not fetch $url");
    $json = json_decode($body, true);
    if (!is_array($json)) throw new Exception('Invalid JSON response.');
    return $json;
}

function findFuelCityRow($rows, $city) {
    $needle = strtolower(trim(str_replace('-', ' ', $city)));
    foreach ($rows as $row) {
        $name = strtolower(trim($row['city'] ?? ''));
        if ($name === $needle || str_replace(' ', '-', $name) === $city) return $row;
    }
    return null;
}

function handleExtraApiRequest() {
    global $fuelApiKey;
    $action = isset($_GET['action']) ? strtolower(trim($_GET['action'])) : '';

    if ($action === 'currencies') {
        $data = fetchJson('https://api.frankfurter.dev/v2/currencies', 10);
        respond(['currencies' => $data, 'source' => 'Frankfurter / ECB']);
    }

    if ($action === 'exchange') {
        $base = strtoupper(trim($_GET['base'] ?? ''));
        $quote = strtoupper(trim($_GET['quote'] ?? ''));
        if (!preg_match('/^[A-Z]{3}$/', $base) || !preg_match('/^[A-Z]{3}$/', $quote) || $base === $quote) {
            respond(['error' => 'Choose two different valid currencies.'], 400);
        }
        $rate = fetchJson("https://api.frankfurter.dev/v2/rate/$base/$quote", 10);
        respond(['base' => $base, 'quote' => $quote, 'rate' => (float)$rate['rate'], 'date' => $rate['date'] ?? null, 'source' => 'Frankfurter / ECB']);
    }

    if (in_array($action, ['fuel-states', 'fuel-cities', 'fuel-rates'], true)) {
        if ($fuelApiKey === '') respond(['error' => 'Fuel API is not configured. Upload config.php beside api.php.'], 503);
        $base = 'https://fuel.indianapi.in';
        $headers = ['x-api-key: ' . $fuelApiKey];
        if ($action === 'fuel-states') {
            $data = fetchJsonWithHeaders($base . '/states', $headers, 15);
        } elseif ($action === 'fuel-cities') {
            $state = strtolower(trim($_GET['state'] ?? ''));
            if (!preg_match('/^[a-z0-9][a-z0-9 -]*$/i', $state)) respond(['error' => 'Invalid state.'], 400);
            $data = fetchJsonWithHeaders($base . '/cities?state=' . rawurlencode($state), $headers, 15);
        } else {
            $city = strtolower(trim($_GET['city'] ?? ''));
            if (!preg_match('/^[a-z0-9-]+$/', $city)) respond(['error' => 'Invalid city.'], 400);
            $petrolRows = fetchJsonWithHeaders($base . '/live_fuel_price?fuel_type=petrol&location_type=city', $headers, 15);
            $dieselRows = fetchJsonWithHeaders($base . '/live_fuel_price?fuel_type=diesel&location_type=city', $headers, 15);
            $petrol = findFuelCityRow($petrolRows, $city);
            $diesel = findFuelCityRow($dieselRows, $city);
            if (!$petrol && !$diesel) respond(['error' => 'No live fuel data found for this city.'], 404);
            $data = ['cityName' => $petrol['city'] ?? $diesel['city'], 'fuel' => [
                'petrol' => $petrol ? ['retailPrice' => (float)$petrol['price'], 'retailUnit' => 'litre', 'change' => (float)$petrol['change']] : null,
                'diesel' => $diesel ? ['retailPrice' => (float)$diesel['price'], 'retailUnit' => 'litre', 'change' => (float)$diesel['change']] : null,
                'cng' => null
            ], 'source' => 'IndianAPI', 'note' => 'IndianAPI currently provides live petrol and diesel. CNG is not included in its documented API.'];
        }
        respond($data);
    }
}

if (isset($_GET['action'])) {
    try { handleExtraApiRequest(); } catch (Throwable $e) { respond(['error' => $e->getMessage()], 502); }
}

function parseIbja($html) {
    $pattern = '/<td[^>]*data-label="(AM|PM)"[^>]*>\s*<strong>(\d{2}\/\d{2}\/\d{4})<\/strong>\s*<\/td>\s*'
        . '<td[^>]*data-label="Gold 999">([\d. ]+)<\/td>\s*'
        . '<td[^>]*data-label="Gold 995">([\d. ]+)<\/td>\s*'
        . '<td[^>]*data-label="Gold 916">([\d. ]+)<\/td>\s*'
        . '<td[^>]*data-label="Gold 750">([\d. ]+)<\/td>\s*'
        . '<td[^>]*data-label="Gold 585">([\d. ]+)<\/td>\s*'
        . '<td[^>]*data-label="Silver 999">([\d. ]+)<\/td>\s*'
        . '<td[^>]*data-label="Platinum 999">([\d. ]+)<\/td>/is';

    preg_match_all($pattern, $html, $matches, PREG_SET_ORDER);

    $rows = ['AM' => null, 'PM' => null];

    foreach ($matches as $m) {
        $session = strtoupper($m[1]);
        if ($rows[$session] === null) {
            $rows[$session] = [
                'date' => $m[2],
                'gold999' => (int) preg_replace('/\s+/', '', $m[3]),
                'gold995' => (int) preg_replace('/\s+/', '', $m[4]),
                'gold916' => (int) preg_replace('/\s+/', '', $m[5]),
                'gold750' => (int) preg_replace('/\s+/', '', $m[6]),
                'gold585' => (int) preg_replace('/\s+/', '', $m[7]),
                'silver999' => (int) preg_replace('/\s+/', '', $m[8]),
                'platinum999' => (int) preg_replace('/\s+/', '', $m[9]),
            ];
        }
    }

    if (!$rows['AM'] || !$rows['PM']) {
        throw new Exception('Could not parse latest IBJA AM/PM rows.');
    }

    return ['am' => $rows['AM'], 'pm' => $rows['PM']];
}

function buildPayload() {
    $ibjaHtml = fetchText('https://www.ibjarates.com/', 15);
    $btcJson = fetchJson('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=inr&include_24hr_change=true', 15);

    $ibja = parseIbja($ibjaHtml);
    $btc = isset($btcJson['bitcoin']) ? $btcJson['bitcoin'] : null;

    if (!$btc || !isset($btc['inr'])) {
        throw new Exception('Bitcoin INR price missing from CoinGecko.');
    }

    $goldRate = round($ibja['pm']['gold999'] / 10, 2);
    $silverRate = round($ibja['pm']['silver999'] / 1000, 3);
    $sterlingRate = round($silverRate * 0.925, 3);
    $platinumRate = round($ibja['pm']['platinum999'] / 10, 2);
    $btcInr = (float) $btc['inr'];
    $btcChange = isset($btc['inr_24h_change']) ? (float) $btc['inr_24h_change'] : 0.0;

    return [
        'generated_at' => date('c'),
        'refresh_seconds' => 10,
        'assets' => [
            'gold' => [
                'title' => 'Gold Tracker',
                'subtitle' => 'Official IBJA benchmark prices, converted from the latest published AM and PM tables into a live-refreshing gold dashboard.',
                'ticker' => 'IBJA PM ' . $ibja['pm']['date'] . ' | Gold 999',
                'unit' => 'g',
                'unit_name' => 'gram',
                'primary_rate' => $goldRate,
                'price_rows' => [
                    ['label' => 'IBJA 999 PM (' . $ibja['pm']['date'] . ')', 'value' => $ibja['pm']['gold999'], 'kind' => 'per_10g'],
                    ['label' => '999 per gram (derived)', 'value' => $goldRate, 'kind' => 'per_g'],
                    ['label' => 'IBJA 995 PM (' . $ibja['pm']['date'] . ')', 'value' => $ibja['pm']['gold995'], 'kind' => 'per_10g'],
                    ['label' => 'IBJA 916 PM (' . $ibja['pm']['date'] . ')', 'value' => $ibja['pm']['gold916'], 'kind' => 'per_10g'],
                    ['label' => 'IBJA 750 PM (' . $ibja['pm']['date'] . ')', 'value' => $ibja['pm']['gold750'], 'kind' => 'per_10g']
                ],
                'highlights' => [
                    ['label' => 'Official Source', 'value' => 'IBJA'],
                    ['label' => 'Latest PM', 'value' => $ibja['pm']['date']],
                    ['label' => 'Converter Base', 'value' => 'Gold 999 per gram']
                ],
                'source_note' => 'IBJA publishes gold in rupees per 10 grams. The per-gram number shown here is the exact benchmark derived from that official PM value.'
            ],
            'silver' => [
                'title' => 'Silver Tracker',
                'subtitle' => 'Official IBJA silver 999 benchmarks, with per-gram conversion and a sterling 92.5% purity benchmark derived from the same live IBJA base.',
                'ticker' => 'IBJA PM ' . $ibja['pm']['date'] . ' | Silver 999',
                'unit' => 'g',
                'unit_name' => 'gram',
                'primary_rate' => $silverRate,
                'price_rows' => [
                    ['label' => 'IBJA 999 PM (' . $ibja['pm']['date'] . ')', 'value' => $ibja['pm']['silver999'], 'kind' => 'per_kg'],
                    ['label' => '999 per gram (derived)', 'value' => $silverRate, 'kind' => 'per_g'],
                    ['label' => 'Sterling 92.5% benchmark', 'value' => $sterlingRate, 'kind' => 'per_g'],
                    ['label' => 'IBJA 999 AM (' . $ibja['am']['date'] . ')', 'value' => $ibja['am']['silver999'], 'kind' => 'per_kg']
                ],
                'highlights' => [
                    ['label' => 'Official Source', 'value' => 'IBJA'],
                    ['label' => 'Latest PM', 'value' => $ibja['pm']['date']],
                    ['label' => 'Sterling Basis', 'value' => '999 x 92.5%']
                ],
                'source_note' => 'IBJA publishes silver 999 in rupees per kilogram. Sterling here is a purity-only benchmark, so it is normally lower than 999 silver unless retail premiums or making charges are added.'
            ],
            'platinum' => [
                'title' => 'Platinum Tracker',
                'subtitle' => 'Official IBJA platinum 999 values, converted to exact per-gram pricing for your live tracker, converter, and profit calculator.',
                'ticker' => 'IBJA PM ' . $ibja['pm']['date'] . ' | Platinum 999',
                'unit' => 'g',
                'unit_name' => 'gram',
                'primary_rate' => $platinumRate,
                'price_rows' => [
                    ['label' => 'IBJA Platinum 999 PM (' . $ibja['pm']['date'] . ')', 'value' => $ibja['pm']['platinum999'], 'kind' => 'per_10g'],
                    ['label' => 'Platinum per gram (derived)', 'value' => $platinumRate, 'kind' => 'per_g'],
                    ['label' => 'IBJA Platinum 999 AM (' . $ibja['am']['date'] . ')', 'value' => $ibja['am']['platinum999'], 'kind' => 'per_10g']
                ],
                'highlights' => [
                    ['label' => 'Official Source', 'value' => 'IBJA'],
                    ['label' => 'Latest PM', 'value' => $ibja['pm']['date']],
                    ['label' => 'Converter Base', 'value' => 'Platinum 999 per gram']
                ],
                'source_note' => 'IBJA publishes platinum in rupees per 10 grams. The per-gram rate in this dashboard is the exact conversion of the published PM figure.'
            ],
            'bitcoin' => [
                'title' => 'Bitcoin Tracker',
                'subtitle' => 'Live INR bitcoin pricing from CoinGecko so the crypto side of the dashboard refreshes alongside the bullion benchmarks.',
                'ticker' => 'CoinGecko | Bitcoin INR',
                'unit' => 'btc',
                'unit_name' => 'BTC',
                'primary_rate' => $btcInr,
                'price_rows' => [
                    ['label' => 'Bitcoin live', 'value' => $btcInr, 'kind' => 'per_btc'],
                    ['label' => '24h change', 'value' => $btcChange, 'kind' => 'percent'],
                    ['label' => '0.01 BTC', 'value' => round($btcInr * 0.01, 2), 'kind' => 'inr']
                ],
                'highlights' => [
                    ['label' => 'Source', 'value' => 'CoinGecko'],
                    ['label' => 'Refresh', 'value' => '10 seconds'],
                    ['label' => '24h Move', 'value' => sprintf('%+.2f%%', $btcChange)]
                ],
                'source_note' => 'Bitcoin is fetched live in INR from CoinGecko and refreshed by the UI every 10 seconds.'
            ]
        ],
        'overview' => [
            'gold' => $goldRate,
            'silver' => $silverRate,
            'platinum' => $platinumRate,
            'bitcoin' => $btcInr
        ],
        'sources' => [
            'ibja' => [
                'label' => 'IBJA',
                'status' => 'ok',
                'message' => 'Latest official IBJA tables parsed successfully. AM: ' . $ibja['am']['date'] . ' | PM: ' . $ibja['pm']['date'] . '.'
            ],
            'mcx' => [
                'label' => 'MCX',
                'status' => 'blocked',
                'message' => 'MCX blocks stable public scraping for exact live contract values, so this site does not guess those numbers.'
            ],
            'safegold' => [
                'label' => 'SafeGold',
                'status' => 'unavailable',
                'message' => 'SafeGold public pages do not expose a stable exact anonymous live rate we can verify here, so the site does not invent one.'
            ],
            'bitcoin' => [
                'label' => 'CoinGecko',
                'status' => 'ok',
                'message' => 'Bitcoin INR price fetched successfully from CoinGecko.'
            ]
        ]
    ];
}

try {
    $cache = readCacheFile($cacheFile);

    if ($cache && isset($cache['generated_at'])) {
        $age = time() - strtotime($cache['generated_at']);
        if ($age < $cacheSeconds) {
            respond($cache);
        }
    }

    $payload = buildPayload();
    writeCacheFile($cacheFile, $payload);
    respond($payload);
} catch (Throwable $e) {
    $cache = readCacheFile($cacheFile);
    if ($cache) {
        $cache['stale'] = true;
        $cache['warning'] = 'Showing cached data because live refresh failed.';
        respond($cache);
    }

    respond([
        'error' => $e->getMessage()
    ], 500);
}
