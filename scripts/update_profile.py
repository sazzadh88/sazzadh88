#!/usr/bin/env python3
"""Refresh the data-driven panels of the profile README from live GitHub data.

Rewrites, in place:
  assets/header.svg    repo counts, years on GitHub
  assets/whoami.svg    repo counts, years on GitHub
  assets/langs.svg     repos by primary language (bars, counts, percentages)
  assets/timeline.svg  repos by year of last push (adds a point every new year)
  assets/classified.svg  private repo count

Everything else in those files (layout, animation, styling) is left untouched.

Token: set PROFILE_TOKEN to a token that can list the account's private repos.
Without one the script stops instead of publishing public-only numbers
(pass --allow-public to override).

Standard library only. Usage:  python scripts/update_profile.py [--allow-public] [--check]
"""
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.request
from html import escape
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
JOINED = dt.date(2016, 9, 10)                 # GitHub account creation date
# Not programming languages worth a bar of their own.
IGNORED_LANGS = {"Makefile", "Smali", "Jupyter Notebook"}
TOP_ROWS = 10                                  # individual language rows before "the rest"
# Hand-written captions under the timeline. Add a line when a year deserves one.
ERAS = {
    2016: "first commits",
    2018: "Ionic + Laravel",
    2019: "Vue SPAs · POS",
    2020: "Flutter",
    2021: "marketplaces",
    2024: "agritech · ML",
    2026: "Go · macOS · AI",
}


# ───────────────────────────── data ─────────────────────────────

def api(path, token):
    url = "https://api.github.com" + path
    out = []
    while url:
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "profile-readme-updater",
            **({"Authorization": "Bearer " + token} if token else {}),
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            out.extend(json.load(r))
            link = r.headers.get("Link", "")
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m else None
    return out


def fetch_repos(login, allow_public):
    token = os.environ.get("PROFILE_TOKEN", "").strip()
    if token:
        repos = api("/user/repos?per_page=100&affiliation=owner", token)
        repos = [r for r in repos if r["owner"]["login"].lower() == login.lower()]
        if not any(r["private"] for r in repos) and not allow_public:
            sys.exit("PROFILE_TOKEN cannot see any private repositories. "
                     "Give it read access to all repositories, or pass --allow-public.")
        return repos
    if not allow_public:
        sys.exit("PROFILE_TOKEN is not set, so only public repositories are visible. "
                 "Refusing to overwrite the graphics with public-only numbers "
                 "(pass --allow-public to do it anyway).")
    return api(f"/users/{login}/repos?per_page=100&type=owner", os.environ.get("GITHUB_TOKEN", ""))


def summarise(repos, today):
    total = len(repos)
    public = sum(not r["private"] for r in repos)
    originals = [r for r in repos if not r["fork"]]
    langs = {}
    for r in originals:
        lang = r.get("language")
        if lang and lang not in IGNORED_LANGS:
            langs[lang] = langs.get(lang, 0) + 1
    years = {y: 0 for y in range(JOINED.year, today.year + 1)}
    for r in repos:
        stamp = r.get("pushed_at") or r.get("created_at")
        y = min(max(int(stamp[:4]), JOINED.year), today.year)
        years[y] += 1
    uptime = today.year - JOINED.year - ((today.month, today.day) < (JOINED.month, JOINED.day))
    return {
        "total": total, "public": public, "private": total - public,
        "originals": len(originals), "uptime": uptime,
        "langs": sorted(langs.items(), key=lambda kv: (-kv[1], kv[0].lower())),
        "years": sorted(years.items()),
    }


# ──────────────────────────── helpers ────────────────────────────

def sub(pattern, repl, text, what, flags=0):
    new, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        sys.exit(f"update_profile: could not find the {what} to update (pattern {pattern!r})")
    return new


def g(x):
    """Compact number: 2.30 -> 2.3, 1.50 -> 1.5, 3.0 -> 3"""
    return f"{round(x, 2):g}"


# ───────────────────────────── header ─────────────────────────────

def update_header(svg, d):
    svg = sub(r'(aria-label="[^"]*?India\. )[^"]*"',
              rf'\g<1>{d["total"]} repositories, {d["public"]} public, {d["private"]} private, '
              rf'{d["uptime"]} years on GitHub."', svg, "header aria-label")
    for label, value in (("REPOS", d["total"]), ("PUBLIC", d["public"]),
                         ("CLASSIFIED", d["private"]), ("UPTIME", f'{d["uptime"]}Y')):
        svg = sub(rf'(>{label}</tspan><tspan [^>]*>)[^<]*(</tspan>)', rf'\g<1>{value}\g<2>',
                  svg, f"header {label} readout")
    return svg


# ───────────────────────────── whoami ─────────────────────────────

def update_whoami(svg, d):
    svg = sub(r'\d+ years on GitHub, \d+ repositories\.',
              f'{d["uptime"]} years on GitHub, {d["total"]} repositories.', svg, "whoami aria-label")
    svg = sub(r'(class="whoami-v">)\d+ years? (<tspan class="whoami-mut">\(since )[^)]*\)',
              rf'\g<1>{d["uptime"]} years \g<2>{JOINED.isoformat()})', svg, "whoami uptime row")
    svg = sub(r'(class="whoami-v">)\d+ repos (<tspan class="whoami-mut">)\([^)]*\)',
              rf'\g<1>{d["total"]} repos \g<2>({d["public"]} public, {d["private"]} private)',
              svg, "whoami packages row")
    return svg


# ─────────────────────────── classified ───────────────────────────

def update_classified(svg, d):
    svg = sub(r'(aria-label="Classified dossier: )\d+', rf'\g<1>{d["private"]}', svg, "classified aria-label")
    return sub(r'(font-weight="700">)\d+(</tspan> PRIVATE REPOSITORIES)', rf'\g<1>{d["private"]}\g<2>',
               svg, "classified private-repo count")


# ───────────────────────────── langs ─────────────────────────────

X0, BLOCK, MAX_BLOCKS, TRACK_END = 268, 10, 47, 738
RANK_OPACITY = [.95, .88, .82, .76, .68, .62, .55]


def update_langs(svg, d):
    langs, originals = d["langs"], d["originals"]
    rows = list(langs[:TOP_ROWS])
    rest = langs[TOP_ROWS:]
    if rest:
        names = [n for n, _ in rest]
        label = " · ".join(names) if len(names) <= 4 else " · ".join(names[:3]) + f" · +{len(names) - 3} more"
        rows.append((label, sum(c for _, c in rest)))
    top = max(c for _, c in rows)
    per_block = max(1, math.ceil(top / MAX_BLOCKS))          # repos represented by one LED block
    width = lambda c: max(1, round(c / per_block)) * BLOCK
    pct = lambda c: f"{c / originals * 100:.1f}%"

    out = ['<g class="langs-in" style="animation-delay:.95s">']
    ticks = range(0, 5)
    out.append('<path d="' + "".join(f"M{X0 - .5 + 100 * j} 83V361" for j in ticks) + '" stroke="#14261a"/>')
    for j in ticks:
        out.append(f'<text x="{X0 - 1 + 100 * j}" y="376" text-anchor="middle" font-size="11" '
                   f'fill="#4a6352">{j * 10 * per_block}</text>')
    out.append(f'<text x="852" y="376" text-anchor="end" font-size="11" fill="#4a6352">% of {originals}</text></g>')

    # labels + counts
    for i, (name, c) in enumerate(rows):
        is_rest = bool(rest) and i == len(rows) - 1
        y = 102 + 25 * i
        if i == 0:
            style = 'font-size="14" fill="#00ff41" font-weight="700"'
        elif is_rest:
            y, style = y - .5, 'font-size="13" fill="#7d9a85"'
        else:
            style = 'font-size="14" fill="#d7ffe0"'
        out.append(f'<text class="langs-in" style="animation-delay:{.90 + .07 * i:.2f}s" x="252" y="{g(y)}" '
                   f'text-anchor="end" {style}>{escape(name)}</text>')
        cy = 101.5 + 25 * i
        out.append(f'<g class="langs-in" style="animation-delay:{1.65 + .07 * i:.2f}s">'
                   f'<text x="{X0 + width(c) + 7}" y="{g(cy)}" font-size="13" font-weight="700" '
                   f'fill="{"#00ff41" if i == 0 else "#d7ffe0"}">{c}</text>'
                   f'<text x="852" y="{g(cy)}" text-anchor="end" font-size="13" '
                   f'fill="{"#d7ffe0" if i == 0 else "#7d9a85"}">{pct(c)}</text></g>')

    # bars
    w0 = width(rows[0][1])
    out.append(f'<g class="langs-bar" style="animation-delay:1.05s"><rect class="langs-pulse" x="{X0}" y="91" '
               f'width="{w0 - 2}" height="12" rx="2" fill="#00ff41" opacity=".5" filter="url(#langs-glow)"/></g>')
    out.append('<g mask="url(#langs-led)">')
    distinct = sorted({c for _, c in rows[1:len(rows) - (1 if rest else 0)]}, reverse=True)
    for i, (name, c) in enumerate(rows):
        is_rest = bool(rest) and i == len(rows) - 1
        y, w = 91 + 25 * i, width(c)
        if i == 0:
            fill, op, cap = "#00ff41", "1", "#b9ffc9"
        else:
            op = g(.5 if is_rest else RANK_OPACITY[min(distinct.index(c), len(RANK_OPACITY) - 1)])
            fill, cap = "#39d353", "#00ff41"
            tx = X0 + w + 20 + 10 * len(str(c))        # leave room for the count label
            if TRACK_END - tx > 0:
                out.append(f'<rect class="langs-in" style="animation-delay:.95s" x="{tx}" y="{y}" '
                           f'width="{TRACK_END - tx}" height="12" fill="#0f3d1e" opacity=".6"/>')
        out.append(f'<rect class="langs-bar" style="animation-delay:{1.05 + .07 * i:.2f}s" x="{X0}" y="{y}" '
                   f'width="{w}" height="12" fill="{fill}" opacity="{op}"/>')
        out.append(f'<rect class="langs-in" style="animation-delay:{1.55 + .07 * i:.2f}s" x="{X0 + w - 10}" y="{y}" '
                   f'width="10" height="12" fill="{cap}"/>')
    out.append('<rect class="langs-shine" x="138" y="91" width="130" height="12" fill="url(#langs-shineg)"/>')
    out.append('</g>')
    out.append('<path d="M28 391.5H852" stroke="#14261a"/>')
    dot = '<tspan fill="#4a6352">&#183;</tspan>'
    foot = (f'<tspan fill="#d7ffe0">{originals}</tspan> original repos {dot} '
            f'<tspan fill="#d7ffe0">{len(langs)}</tspan> languages')
    counts = dict(langs)
    if "PHP" in counts and "Blade" in counts:
        foot += (f' {dot} PHP + Blade = <tspan fill="#ffb000">{counts["PHP"] + counts["Blade"]}</tspan> '
                 f'Laravel-world repos')
    out.append(f'<text class="langs-in" style="animation-delay:2.6s" x="28" y="416" font-size="13" '
               f'fill="#7d9a85">{foot}</text>')
    body = "\n".join(out) + "\n"

    svg = sub(r'<g class="langs-in" style="animation-delay:\.95s">\n<path d="M267\.5.*?'
              r'(?=<rect width="880" height="440" fill="url\(#langs-scan\)"/>)',
              lambda m: body, svg, "langs chart body", re.S)
    svg = sub(r'(text-anchor="end" font-size="13" fill="#4a6352">)= [^<]*(</text>)',
              rf'\g<1>= {per_block} repo{"s" if per_block > 1 else ""}\g<2>', svg, "langs legend")
    said = ", ".join(f"{n} {c}" for n, c in rows[:TOP_ROWS])
    if rest:
        said += f", {len(rest)} more languages {rows[-1][1]}"
    aria = (f"Language arsenal: repositories by primary language. {said}. "
            f"{originals} original repos, {len(langs)} languages.")
    return sub(r'aria-label="[^"]*"', lambda m: f'aria-label="{escape(aria)}"', svg, "langs aria-label")


# ──────────────────────────── timeline ────────────────────────────

def nice_step(top):
    for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000):
        if top / s <= 5:
            return s
    return 2000


def update_timeline(svg, d):
    years = d["years"]
    n = len(years)
    vals = [v for _, v in years]
    step = nice_step(max(vals))
    ymax = max(step, math.ceil(max(vals) / step) * step)
    last = n - 1
    # A new year starts low, right after a busy one. The "you are here" label then moves to the
    # top-right corner, so make sure the previous year's point is not sitting up there too.
    falls = last > 0 and (vals[last - 1] - vals[last]) * 185 / ymax > 40
    if falls and vals[last - 1] > .85 * ymax:
        ymax += step
    xs = [round(84 + 750 * i / (n - 1)) for i in range(n)]
    ys = [300 - v * 185 / ymax for v in vals]

    # how far along the line each point sits (drives when its dot pops in)
    seg = [math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(n - 1)]
    frac = [sum(seg[:i]) / sum(seg) for i in range(n)]
    dot_t = [round(1.5 + 2.8 * f, 2) for f in frac]

    o = ['<g class="tl-in" style="animation-delay:1.1s">', '<g stroke="#14261a" stroke-dasharray="2 5">']
    ticks = list(range(step, ymax + 1, step))
    ty = lambda t: round(300 - t * 185 / ymax) + .5
    for t in ticks:
        o.append(f'<line x1="76" y1="{g(ty(t))}" x2="852" y2="{g(ty(t))}"/>')
    top_y = g(ty(ymax))
    for x in xs:
        o.append(f'<line x1="{x}.5" y1="{top_y}" x2="{x}.5" y2="300"/>')
    o.append('</g>')
    o.append('<line x1="76" y1="300.5" x2="852" y2="300.5" stroke="#1c3a23"/>')
    for t in [0] + ticks:
        o.append(f'<text x="66" y="{g(ty(t) + 4)}" text-anchor="end" fill="#4a6352">{t}</text>')
    for i, (year, _) in enumerate(years):
        marked = year in ERAS or i == last
        colour = "#ffb000" if i == last else "#39d353" if year in ERAS else "#4a6352"
        o.append(f'<line x1="{xs[i]}.5" y1="300" x2="{xs[i]}.5" y2="305" '
                 f'stroke="{"#1f7a3a" if marked else "#1c3a23"}"/>')
        o.append(f'<text x="{xs[i]}" y="322" text-anchor="middle" fill="{colour}">{year}</text>')
    o.append('</g>')

    line = " L".join(f"{xs[i]} {ys[i]:.1f}" for i in range(n))
    o.append('<g class="tl-wipe" clip-path="url(#tl-plot)"><g class="tl-unwipe">')
    o.append(f'<path d="M{line} L{xs[last]} 300 L{xs[0]} 300 Z" fill="url(#tl-fill)"/>')
    o.append('<g stroke="#1f7a3a" stroke-opacity=".7" stroke-dasharray="1 4">')
    for i in range(1, last):
        if ys[i] + 7 < 290:
            o.append(f'<line x1="{xs[i]}.5" y1="{ys[i] + 7:.1f}" x2="{xs[i]}.5" y2="299"/>')
    o.append('</g></g></g>')
    if ys[last] + 11 < 295:
        o.append(f'<line class="tl-in" style="animation-delay:4.3s" x1="{xs[last]}.5" y1="{ys[last] + 11:.1f}" '
                 f'x2="{xs[last]}.5" y2="299" stroke="#ffb000" stroke-opacity=".45" stroke-dasharray="1 4"/>')
    o.append(f'<path class="tl-line" pathLength="100" d="M{line}" fill="none" stroke="#00ff41" stroke-width="2.25" '
             f'stroke-linejoin="round" stroke-linecap="round" filter="url(#tl-glow)"/>')
    o.append(f'<path class="tl-tail" pathLength="100" d="M{line}" fill="none" stroke="#d7ffe0" stroke-opacity=".4" '
             f'stroke-width="2.25" stroke-linejoin="round"/>')
    o.append(f'<path class="tl-head" pathLength="100" d="M{line}" fill="none" stroke="#d7ffe0" stroke-width="2.6" '
             f'stroke-linejoin="round" stroke-linecap="round" filter="url(#tl-glow)"/>')
    o.append(f'<path class="tl-tracer" pathLength="100" d="M{line}" fill="none" stroke="#d7ffe0" stroke-width="7" '
             f'stroke-linecap="round" filter="url(#tl-glow)"/>')

    for i in range(last):
        x, y = xs[i], ys[i]
        o.append(f'<circle class="tl-dot" style="animation-delay:{g(dot_t[i])}s" cx="{x}" cy="{y:.1f}" r="4" '
                 f'fill="#0a0e0a" stroke="#00ff41" stroke-width="2"/>')
        lx, ly = x, y - 11
        # a low point between steep slopes: the label goes underneath, clear of the line
        dip = 0 < i and ys[i - 1] < y and ys[i + 1] < y and max(y - ys[i - 1], y - ys[i + 1]) > 40
        if dip and y + 22 < 297:
            ly = y + 22
        elif y - ys[i + 1] > 40:                                  # line climbs steeply to the right
            lx = x - 11
        elif i > 0 and y - ys[i - 1] > 40:                        # line drops steeply from the left
            lx = x + 12
        o.append(f'<text class="tl-lab" style="animation-delay:{g(dot_t[i] + .08)}s;font-size:14px" x="{lx}" '
                 f'y="{ly:.1f}" text-anchor="middle" font-weight="700" fill="#d7ffe0">{vals[i]}</text>')
    x, y = xs[last], ys[last]
    o.append(f'<circle class="tl-ping" cx="{x}" cy="{y:.1f}" r="7" fill="none" stroke="#ffb000" stroke-width="1.5"/>')
    o.append(f'<circle class="tl-ping tl-ping2" cx="{x}" cy="{y:.1f}" r="7" fill="none" stroke="#ffb000" stroke-width="1"/>')
    o.append(f'<circle class="tl-ring" cx="{x}" cy="{y:.1f}" r="9" fill="none" stroke="#ffb000" stroke-width="1.5" '
             f'filter="url(#tl-aglow)"/>')
    o.append(f'<circle class="tl-dot" style="animation-delay:4.3s" cx="{x}" cy="{y:.1f}" r="4.5" fill="#ffb000"/>')
    o.append(f'<text class="tl-lab" style="animation-delay:4.45s;font-size:14px" x="852" y="{94 if falls else max(y - 21, 94):.1f}" '
             f'text-anchor="end"><tspan fill="#ffb000" font-weight="700">{vals[last]}</tspan>'
             f'<tspan fill="#7d9a85"> · </tspan><tspan fill="#ffb000">you are here</tspan></text>')

    prev_x, prev_low = None, True
    for i, (year, _) in enumerate(years):
        if year not in ERAS:
            continue
        near = prev_x is not None and xs[i] - prev_x < (220 if i == last else 150)
        low = near and not prev_low                # two rows, so neighbouring captions never collide
        prev_x, prev_low = xs[i], low
        y2, ty_ = (355, 368) if low else (334, 347)
        delay = "4.5" if i == last else g(dot_t[i] + .2)
        pos = 'x="852" text-anchor="end"' if i == last else f'x="{xs[i]}" text-anchor="middle"'
        o.append(f'<g class="tl-lab" style="animation-delay:{delay}s">')
        o.append(f'<line x1="{xs[i]}.5" y1="328" x2="{xs[i]}.5" y2="{y2}" stroke="#1f7a3a"/>')
        o.append(f'<text {pos.split(" ", 1)[0]} y="{ty_}" {pos.split(" ", 1)[1]} fill="#7d9a85">{escape(ERAS[year])}</text>')
        o.append('</g>')
    body = "\n".join(o) + "\n"

    svg = sub(r'<g class="tl-in" style="animation-delay:1\.1s">\n<g stroke="#14261a" stroke-dasharray="2 5">.*?'
              r'(?=<rect x="0" y="0" width="880" height="400" fill="url\(#tl-scan\)")',
              lambda m: body, svg, "timeline chart body", re.S)

    def frames(sign):
        return "".join(f"{g(frac[i] * 100)}%{{transform:translateX({sign}{750 - (xs[i] - 84)}px)}}" for i in range(last))
    svg = sub(r'@keyframes tl-wipe\{.*?\}\}', lambda m: "@keyframes tl-wipe{" + frames("-") + "}", svg, "tl-wipe keyframes")
    svg = sub(r'@keyframes tl-unwipe\{.*?\}\}', lambda m: "@keyframes tl-unwipe{" + frames("") + "}", svg, "tl-unwipe keyframes")
    svg = sub(r'(id="tl-fill" x1="0" y1=")[^"]*"', rf'\g<1>{min(ys):.1f}"', svg, "timeline gradient")
    y0, y1 = years[0][0], years[-1][0]
    svg = sub(r'aria-label="[^"]*"',
              f'aria-label="Activity timeline: {d["total"]} repositories by year of last push, {y0} to {y1}: '
              f'{vals[0]} in {y0}, {vals[-1]} in {y1}"', svg, "timeline aria-label")
    svg = sub(r'<title>[^<]*</title>',
              f'<title>Activity timeline: {d["total"]} repos by year of last push, {y0}-{y1}</title>', svg, "timeline title")
    return sub(r'(<tspan fill="#d7ffe0">)\d+(</tspan> repos by year of last push)', rf'\g<1>{d["total"]}\g<2>',
               svg, "timeline legend")


# ───────────────────────────── main ─────────────────────────────

def main():
    args = set(sys.argv[1:])
    login = os.environ.get("PROFILE_LOGIN") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "sazzadh88"
    today = dt.datetime.now(dt.timezone.utc).date()
    data = summarise(fetch_repos(login, "--allow-public" in args), today)
    print(f"{login}: {data['total']} repos ({data['public']} public, {data['private']} private), "
          f"{data['originals']} original, {len(data['langs'])} languages, {data['uptime']} years")
    print("years:", ", ".join(f"{y}:{v}" for y, v in data["years"]))
    print("langs:", ", ".join(f"{n} {c}" for n, c in data["langs"]))

    changed = []
    for name, fn in (("header.svg", update_header), ("whoami.svg", update_whoami),
                     ("langs.svg", update_langs), ("timeline.svg", update_timeline),
                     ("classified.svg", update_classified)):
        path = ASSETS / name
        old = path.read_text(encoding="utf-8")
        new = fn(old, data)
        if new != old:
            changed.append(name)
            if "--check" not in args:
                path.write_text(new, encoding="utf-8", newline="\n")
    print("changed:" if changed else "no changes", ", ".join(changed))


if __name__ == "__main__":
    main()
