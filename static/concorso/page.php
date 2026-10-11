<?php
// Serves concorso/<id>.html from the gzipped JSON shard built by build.py. Reads only its own files; stores nothing.
$id = $_GET['id'] ?? '';
$html = null;
if (preg_match('/^[0-9a-f]{32}$/', $id)) {
    $shard = __DIR__ . '/data/' . $id[0] . '.json.gz';
    $mtime = @filemtime($shard);
    $raw = @file_get_contents($shard);
    $pages = $raw === false ? null : json_decode(gzdecode($raw), true);
    $html = $pages[$id] ?? null;
    // A call can close between two builds: then drop its JobPosting at once (Google wants expired postings gone)
    // and treat the page as changed at the deadline.
    if ($html !== null && preg_match('/"validThrough": "([^"]+)"/', $html, $m) && ($until = strtotime($m[1])) && $until < time()) {
        $html = preg_replace('#\n<script type="application/ld\+json">\{"@context": "https://schema.org", "@type": "JobPosting".*?</script>#s',
                             "\n" . '<meta name="robots" content="noindex">', $html, 1);
        $mtime = max($mtime, $until);
    }
    // Otherwise the page changes only when the build does: let crawlers ask "changed since?" and get a 304.
    if ($html !== null && $mtime && ($ims = strtotime($_SERVER['HTTP_IF_MODIFIED_SINCE'] ?? '')) && $ims >= $mtime) {
        http_response_code(304);
        exit;
    }
}
header('Content-Type: text/html; charset=utf-8');
if ($html === null) {
    http_response_code(404);
    $html = @file_get_contents(__DIR__ . '/data/404.html') ?: 'Concorso non trovato.';
} else {
    header('Cache-Control: max-age=900');
    header('Last-Modified: ' . gmdate('D, d M Y H:i:s', $mtime) . ' GMT');
}
echo $html;
