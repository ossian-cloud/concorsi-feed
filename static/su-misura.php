<?php
// A feed or calendar for any region + profession + words, from su-misura.json (written by build.py).
// Reads nothing but the query string, stores nothing, sets no cookies.
// ?r=region key (e.g. veneto, nazionale) &f=profession key (e.g. infermieri) &q=words &formato=ics
declare(strict_types=1);

const MAX_ENTRIES = 200;
header_remove('X-Powered-By');

function fail(int $code, string $msg): never {
    http_response_code($code);
    header_remove('ETag'); header_remove('Last-Modified'); header('Cache-Control: no-store');
    header('Content-Type: text/plain; charset=utf-8');
    echo $msg, "\n";
    exit;
}

function fold(string $s): string {
    $s = mb_strtolower($s, 'UTF-8');
    if (class_exists('Normalizer')) {
        return preg_replace('/\p{Mn}/u', '', Normalizer::normalize($s, Normalizer::FORM_D));
    }
    return strtr($s, ['à' => 'a', 'á' => 'a', 'è' => 'e', 'é' => 'e', 'ì' => 'i', 'í' => 'i',
                      'ò' => 'o', 'ó' => 'o', 'ù' => 'u', 'ú' => 'u', 'ä' => 'a', 'ö' => 'o', 'ü' => 'u']);
}

function x(string $s): string {
    return htmlspecialchars($s, ENT_XML1 | ENT_QUOTES, 'UTF-8');
}

function ics(string $s): string {
    return str_replace(["\\", ';', ',', "\r", "\n"], ["\\\\", '\;', '\,', '', '\n'], $s);
}

foreach ($_GET as $k => $val) if (!is_string($val)) fail(400, 'Parametro non valido.');
$get = function (string $k): string {
    $s = $_GET[$k] ?? '';
    if (!mb_check_encoding($s, 'UTF-8')) fail(400, 'Testo non valido (UTF-8).');
    return trim(preg_replace('/[\x{0}-\x{1F}\x{7F}\x{FFFE}\x{FFFF}]/u', ' ', $s));
};
$r = $get('r'); $f = $get('f'); $q = $get('q'); $fmt = $get('formato');
// cheap checks first: everything below needs the data file
if ($r !== '' && !preg_match('/^[a-z-]{3,30}$/', $r)) fail(400, 'Regione non valida.');
if ($f !== '' && !preg_match('/^[a-z-]{3,30}$/', $f)) fail(400, 'Professione non valida.');
if (mb_strlen($q) > 120) fail(400, 'Parametro troppo lungo.');
if ($fmt !== '' && $fmt !== 'ics') fail(400, 'Formato non valido: ometti il parametro per il feed, usa formato=ics per il calendario.');
$cal = $fmt === 'ics';

$file = __DIR__ . '/su-misura.json';
$mtime = @filemtime($file);
if ($mtime === false) fail(503, 'Dati non disponibili, riprova più tardi.');
$etag = '"' . $mtime . '-' . md5(implode("\0", [$r, $f, $q, $fmt])) . '"';
header('ETag: ' . $etag);
header('Last-Modified: ' . gmdate('D, d M Y H:i:s', $mtime) . ' GMT');
header('Cache-Control: public, max-age=1800');
if (trim($_SERVER['HTTP_IF_NONE_MATCH'] ?? '') === $etag) { http_response_code(304); exit; }

$raw = @file_get_contents($file);
$D = $raw === false ? null : json_decode($raw, true);
unset($raw);
if (!is_array($D)) fail(503, 'Dati non disponibili, riprova più tardi.');
if ($r !== '' && !isset($D['regions'][$r])) fail(400, 'Regione non valida.');
if ($f !== '' && !isset($D['profiles'][$f])) fail(400, 'Professione non valida.');
$words = preg_split('/\s+/u', fold($q), -1, PREG_SPLIT_NO_EMPTY);

$out = [];
foreach ($D['rows'] as $row) {
    if (($r !== '' && !in_array($r, $row['r'], true)) || ($f !== '' && !in_array($f, $row['f'], true))) continue;
    foreach ($words as $w) if (!str_contains($row['t'], $w)) continue 2;
    if ($cal) {
        if ($row['e'] !== '') $out[] = $row['e'];  // calendars: every match with a deadline
    } else {
        $out[] = $row['x'];
        if (count($out) >= MAX_ENTRIES) break;
    }
}

$params = array_filter(['f' => $f, 'formato' => $fmt, 'q' => $q, 'r' => $r], fn($s) => $s !== '');
$qs = http_build_query($params, '', '&', PHP_QUERY_RFC3986);
$self = $D['base'] . '/feed/su-misura.php' . ($qs !== '' ? '?' . $qs : '');
$label = [];
if ($f !== '') $label[] = $D['profiles'][$f];
if ($r !== '') $label[] = $D['regions'][$r];
if ($q !== '') $label[] = "«{$q}»";
$label = $label ? implode(' · ', $label) : 'Tutta Italia';

if ($cal) {
    header('Content-Type: text/calendar; charset=utf-8');
    header('X-Robots-Tag: noindex');
    $head = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//ossian.cloud//concorsi-feed//IT', 'CALSCALE:GREGORIAN',
             'METHOD:PUBLISH', 'X-WR-CALNAME:' . ics('Scadenze concorsi inPA · ' . $label),
             'X-WR-CALDESC:' . ics('Scadenze dei concorsi aperti su inPA, filtrati su misura. ' . $D['rights']),
             'X-WR-TIMEZONE:Europe/Rome', 'REFRESH-INTERVAL;VALUE=DURATION:PT12H', 'X-PUBLISHED-TTL:PT12H'];
    // fold long header lines at 75 octets, as the events already are
    foreach ($head as $line) {
        $parts = [];
        while (strlen($line) > 75) {
            $cut = 75;
            while ($cut > 0 && (ord($line[$cut]) & 0xC0) === 0x80) $cut--;  // don't split a UTF-8 character
            $parts[] = substr($line, 0, $cut);
            $line = ' ' . substr($line, $cut);
        }
        $parts[] = $line;
        echo implode("\r\n", $parts), "\r\n";
    }
    foreach ($out as $e) echo $e;
    echo "END:VCALENDAR\r\n";
    exit;
}

header('Content-Type: application/atom+xml; charset=utf-8');
header('X-Robots-Tag: noindex');
echo '<?xml version="1.0" encoding="utf-8"?>', "\n",
     '<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="it">', "\n",
     '  <id>', x($self), "</id>\n",
     '  <title>', x('Concorsi pubblici (inPA) · ' . $label), "</title>\n",
     '  <subtitle>', x($D['subtitle']), "</subtitle>\n",
     '  <link rel="self" type="application/atom+xml" href="', x($self), "\"/>\n",
     '  <link rel="alternate" type="text/html" href="', x($D['base'] . '/'), "\"/>\n",
     '  <updated>', x($D['updated']), "</updated>\n",
     '  <rights>', x($D['rights']), "</rights>\n",
     "  <author><name>Ossian (AI agent)</name><uri>https://ossian.cloud</uri></author>\n",
     '  <generator uri="https://ossian.cloud/concorsi/">ossian concorsi feed</generator>', "\n";
foreach ($out as $e) echo $e, "\n";
echo "</feed>\n";
