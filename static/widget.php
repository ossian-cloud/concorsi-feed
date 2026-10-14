<?php
// A short list of open calls to embed in other sites (iframe), from su-misura.json (written by build.py).
// Same filters as su-misura.php: ?r=region &p=province (local authorities) &f=profession &q=words, plus &n=how many.
// Soonest deadline first. Reads nothing but the query string, stores nothing, no cookies, no scripts, no external resources.
declare(strict_types=1);

const MAX_N = 50;
header_remove('X-Powered-By');
header('X-Content-Type-Options: nosniff');
header("Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; frame-ancestors *; base-uri 'none'; form-action 'none'");
header('Referrer-Policy: no-referrer');

function fail(int $code, string $msg): never {
    http_response_code($code);
    header_remove('ETag'); header_remove('Last-Modified'); header('Cache-Control: no-store');
    header('Content-Type: text/plain; charset=utf-8');
    echo $msg, "\n";
    exit;
}

function fold(string $s): string {
    $s = str_replace(["\u{2018}", "\u{2019}"], "'", mb_strtolower($s, 'UTF-8'));
    if (class_exists('Normalizer')) {
        return preg_replace('/\p{Mn}/u', '', Normalizer::normalize($s, Normalizer::FORM_D));
    }
    return strtr($s, ['à' => 'a', 'á' => 'a', 'è' => 'e', 'é' => 'e', 'ì' => 'i', 'í' => 'i',
                      'ò' => 'o', 'ó' => 'o', 'ù' => 'u', 'ú' => 'u', 'ä' => 'a', 'ö' => 'o', 'ü' => 'u']);
}

function h(string $s): string {
    return htmlspecialchars($s, ENT_QUOTES | ENT_HTML5, 'UTF-8');
}

foreach ($_GET as $k => $val) if (!is_string($val)) fail(400, 'Parametro non valido.');
$get = function (string $k): string {
    $s = $_GET[$k] ?? '';
    if (!mb_check_encoding($s, 'UTF-8')) fail(400, 'Testo non valido (UTF-8).');
    return trim(preg_replace('/[\x{0}-\x{1F}\x{7F}\x{FFFE}\x{FFFF}]/u', ' ', $s));
};
$r = $get('r'); $p = $get('p'); $f = $get('f'); $q = $get('q'); $n = $get('n');
if ($p === 'forl-cesena') $p = 'forli-cesena'; // old slug, until 2026-10-14
if ($r !== '' && !preg_match('/^[a-z-]{3,30}$/', $r)) fail(400, 'Regione non valida.');
if ($p !== '' && !preg_match('/^[a-z-]{3,40}$/', $p)) fail(400, 'Provincia non valida.');
if ($f !== '' && !preg_match('/^[a-z-]{3,30}$/', $f)) fail(400, 'Professione non valida.');
if (mb_strlen($q) > 120) fail(400, 'Parametro troppo lungo.');
if ($n !== '' && !preg_match('/^[1-9][0-9]?$/', $n)) fail(400, 'Numero non valido: n va da 1 a ' . MAX_N . '.');
$n = $n === '' ? 10 : min((int)$n, MAX_N);

$file = __DIR__ . '/su-misura.json';
$mtime = @filemtime($file);
if ($mtime === false) fail(503, 'Dati non disponibili, riprova più tardi.');
$now = new DateTimeImmutable('now', new DateTimeZone('Europe/Rome'));
// the day is part of the tag: a call whose deadline passed drops out even if the data file didn't change
$etag = '"' . $mtime . '-' . (int)@filemtime(__FILE__) . '-' . $now->format('YmdH') . '-' . md5(implode("\0", [$r, $p, $f, $q, $n])) . '"';
header('ETag: ' . $etag);
header('Last-Modified: ' . gmdate('D, d M Y H:i:s', $mtime) . ' GMT');
header('Cache-Control: public, max-age=1800');
$inm = array_map(fn($t) => preg_replace('/^W\//', '', trim($t)), explode(',', $_SERVER['HTTP_IF_NONE_MATCH'] ?? ''));
if (in_array($etag, $inm, true)) { http_response_code(304); exit; }

$raw = @file_get_contents($file);
$D = $raw === false ? null : json_decode($raw, true);
unset($raw);
if (!is_array($D)) fail(503, 'Dati non disponibili, riprova più tardi.');
if ($r !== '' && !isset($D['regions'][$r])) fail(400, 'Regione non valida.');
if ($p !== '' && !isset($D['provinces'][$p])) fail(400, 'Provincia non valida.');
if ($f !== '' && !isset($D['profiles'][$f])) fail(400, 'Professione non valida.');
$words = preg_split('/\s+/u', fold($q), -1, PREG_SPLIT_NO_EMPTY);

$cutoff = $now->format('Y-m-d\TH:i');
$hits = [];
foreach ($D['rows'] as $row) {
    if (($r !== '' && !in_array($r, $row['r'], true)) || ($f !== '' && !in_array($f, $row['f'], true))) continue;
    if ($p !== '' && $row['p'] !== $p) continue;
    foreach ($words as $w) if (!str_contains($row['t'], $w)) continue 2;
    if ($row['w'][3] !== '' && $row['w'][3] < $cutoff) continue;  // deadline passed since the last build
    $hits[] = $row['w'];
}
usort($hits, fn($a, $b) => [$a[3] === '' ? '9999' : $a[3], $a[1]] <=> [$b[3] === '' ? '9999' : $b[3], $b[1]]);
$total = count($hits);
$hits = array_slice($hits, 0, $n);

$label = [];
if ($f !== '') $label[] = $D['profiles'][$f];
if ($r !== '') $label[] = $D['regions'][$r];
if ($p !== '') $label[] = 'Comuni ed enti locali, provincia di ' . $D['provinces'][$p];
if ($q !== '') $label[] = "«{$q}»";
$label = $label ? implode(' · ', $label) : 'Tutta Italia';
// "see all": the page for a single filter, else the custom feed form
$only = array_filter(['r' => $r, 'p' => $p, 'f' => $f, 'q' => $q], fn($s) => $s !== '');
$all = $D['base'] . '/';
if (count($only) === 1 && $r !== '') $all .= 'regione/' . $r . '.html';
elseif (count($only) === 1 && $p !== '') $all .= 'provincia/' . $p . '.html';
elseif (count($only) === 1 && $f !== '') $all .= 'profilo/' . $f . '.html';
elseif ($only) $all .= 'feed.html#su-misura';
$page = !str_ends_with($all, '#su-misura');

header('Content-Type: text/html; charset=utf-8');
header('X-Robots-Tag: noindex');
?>
<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Concorsi aperti · <?= h($label) ?></title>
<style>
:root{color-scheme:light;--fg:#1d2a2c;--mute:#55666a;--link:#0b6670;--line:#d5dedf}
body{margin:0;padding:.5rem .75rem;font:15px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--fg);background:#fff}
h1{font-size:1rem;margin:0 0 .4rem}
ol{list-style:none;margin:0;padding:0}
li{padding:.45rem 0;border-top:1px solid var(--line)}
a{color:var(--link)}
li a{font-weight:600;text-decoration:none}
li a:hover,li a:focus{text-decoration:underline}
.m{display:block;color:var(--mute);font-size:.87rem}
p{margin:.5rem 0 0;color:var(--mute);font-size:.8rem;border-top:1px solid var(--line);padding-top:.4rem}
</style>
</head>
<body>
<h1>Concorsi aperti · <?= h($label) ?></h1>
<?php if (!$hits): ?>
<p>Nessun concorso aperto con questi filtri, per ora.</p>
<?php else: ?>
<ol>
<?php foreach ($hits as [$title, $id, $ente, $closes]):
    $when = $closes === '' ? 'scadenza non indicata'
        : (substr($closes, 0, 10) === $now->format('Y-m-d') ? 'scade oggi alle ' . substr($closes, 11, 5)
        : 'scade il ' . substr($closes, 8, 2) . '/' . substr($closes, 5, 2) . '/' . substr($closes, 0, 4));
    $meta = array_filter([$ente, $when]); ?>
<li><a href="<?= h($D['base'] . '/concorso/' . rawurlencode($id) . '.html') ?>" target="_blank" rel="noopener"><?= h($title) ?></a><span class="m"><?= h(implode(' · ', $meta)) ?></span></li>
<?php endforeach; ?>
</ol>
<?php endif; ?>
<p><?= $total <= count($hits) ? '' : ($page ? '<a href="' . h($all) . '" target="_blank" rel="noopener">Tutti i concorsi aperti (' . $total . ')</a> · '
    : $total . ' aperti in tutto (<a href="' . h($all) . '" target="_blank" rel="noopener">feed e calendario</a>) · ') ?>Fonte: inPA (CC BY 3.0). Elenco non ufficiale, aggiornato ogni 4 ore da <a href="https://ossian.cloud/concorsi/" target="_blank" rel="noopener">Ossian</a>, un agente AI: fa fede la scheda su inPA.</p>
</body>
</html>
