#!/usr/bin/env python3
"""Count downloads and installs, keep them day by day, and draw the README's chart.

    python3 scripts/download-stats.py            count, and write the stats branch if anything changed
    python3 scripts/download-stats.py --dry-run  count and print stats.json, write nothing
    python3 scripts/download-stats.py --force    write even when the numbers have not changed

What it counts (settings come from the environment, set in .github/workflows/stats.yml):
  release      downloads of the files attached to GitHub releases (not checksums). GitHub keeps only the
               running total, so the total is recorded each day.
  marketplace  installs on the Visual Studio Marketplace (MARKETPLACE_ITEM, e.g. publisher.name)
  clone        people who git-cloned the repository, per day as GitHub counts it. GitHub keeps only the
               last 14 days, so the days are kept here. Reading them needs the repository's
               Administration (read) permission: the TRAFFIC_TOKEN secret in Actions, or gh on a Mac
               logged in as someone who can push. Without it, the kept days stay as they are.
  site         presses of this tool's download / install buttons on https://auralune.tech, which go out
               through auralune.tech/dl/... and are counted there (AURALUNE_SITE_IDS, AURALUNE_STATS_KEY).
               A press that leads to a GitHub release file or the Marketplace is already inside those
               counts, so it is shown as "of which via auralune.tech". A source archive (archive/refs/...
               zip, marked "(source)") is not counted by GitHub, so it is added to the total.

total = release + marketplace + clone + site source archives. The total and the via-auralune.tech number
go to stats.json on the `stats` branch (the README's badges read it) and into downloads-ja.svg /
downloads-en.svg, a chart of how the running totals grow, one point per day (UTC) since the record began.

The repository is never cloned (its own clone would be counted): everything is read and written through
GitHub's API. Standard library only.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

REPO = os.environ.get("STATS_REPO") or os.environ.get("GITHUB_REPOSITORY") or ""
BRANCH = os.environ.get("STATS_BRANCH", "stats")
PRODUCT = os.environ.get("STATS_PRODUCT", REPO.split("/")[-1])
MARKETPLACE_ITEM = os.environ.get("MARKETPLACE_ITEM", "")
SITE_IDS = [s for s in os.environ.get("AURALUNE_SITE_IDS", "").split(",") if s]
SITE_KEY = os.environ.get("AURALUNE_STATS_KEY", "")
SITE_URL = os.environ.get("AURALUNE_STATS_URL", "https://auralune.tech/api/dl-stats")
SKIP_ASSET = re.compile(os.environ.get("RELEASE_SKIP", r"SHA256|sha256|checksum"), re.I)
UTC = dt.timezone.utc


def token():
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        sys.exit("A GitHub token is needed (GH_TOKEN, or gh logged in)")


def http(url, data=None, method=None, tok=None, headers=None, raw=False):
    h = {"User-Agent": "download-stats", **(headers or {})}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
        h.setdefault("Accept", "application/vnd.github+json")
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        b = r.read()
        return b if raw else (json.loads(b) if b else None)


def gh(path, tok, **kw):
    return http(f"https://api.github.com/repos/{REPO}/{path}", tok=tok, **kw)


def releases(tok):
    total, out, page = 0, [], 1
    while True:
        rs = gh(f"releases?per_page=100&page={page}", tok)
        for r in rs:
            if r.get("draft"):
                continue
            n = sum(a["download_count"] for a in r.get("assets", []) if not SKIP_ASSET.search(a["name"]))
            total += n
            out.append({"tag": r["tag_name"], "published": r.get("published_at"), "downloads": n})
        if len(rs) < 100:
            break
        page += 1
    return total, sorted(out, key=lambda r: r["published"] or "")


def marketplace():
    if not MARKETPLACE_ITEM:
        return None
    q = {"filters": [{"criteria": [{"filterType": 7, "value": MARKETPLACE_ITEM}]}], "flags": 914}
    r = http("https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery", data=q, method="POST",
             headers={"Accept": "application/json;api-version=7.2-preview.1"})
    ext = r["results"][0]["extensions"]
    if not ext:
        return None
    stats = {s["statisticName"]: s["value"] for s in ext[0].get("statistics", [])}
    return int(stats.get("install", 0))


def clones(tok):
    for t in (os.environ.get("TRAFFIC_TOKEN"), tok):
        if not t:
            continue
        try:
            return gh("traffic/clones", t).get("clones", [])
        except urllib.error.HTTPError:
            continue
    print("Could not read git clones (needs Administration read); keeping the days already kept", file=sys.stderr)
    return None


def site():
    if not SITE_IDS:
        return None
    if not SITE_KEY:
        print("No AURALUNE_STATS_KEY; keeping the auralune.tech count as it was", file=sys.stderr)
        return None
    try:
        d = http(f"{SITE_URL}?key={SITE_KEY}&format=json")
    except Exception as e:
        print(f"Could not read auralune.tech ({e}); keeping the count as it was", file=sys.stderr)
        return None
    total = source = 0
    for p in d.get("products", []):
        if p["id"] in SITE_IDS:
            total += p["total"]
            source += sum(n for f, n in p.get("files", []) if f.endswith("(source)"))
    return {"total": total, "source": source}


def count(old, tok):
    now = dt.datetime.now(UTC).replace(microsecond=0)
    today, at = now.date().isoformat(), now.isoformat().replace("+00:00", "Z")
    rel_total, rel_list = releases(tok)
    mk = marketplace()
    if mk is None:
        mk = old.get("marketplace", 0) if MARKETPLACE_ITEM else 0
    kept = dict(old.get("clones", {}))
    for c in (clones(tok) or []):
        day = c["timestamp"][:10]
        prev = kept.get(day, {"count": 0, "uniques": 0})
        if c["count"] > 0:
            kept[day] = {"count": max(prev["count"], c["count"]), "uniques": max(prev["uniques"], c["uniques"])}
    kept = dict(sorted(kept.items()))
    clone = sum(v["uniques"] for v in kept.values())
    s = site()
    if s is None:
        s = {"total": old.get("site", 0), "source": old.get("site_source", 0)}
    total = rel_total + mk + clone + s["source"]
    snap = {"total": total, "release": rel_total, "marketplace": mk, "clone": clone, "site": s["total"], "site_source": s["source"]}
    daily = dict(old.get("daily", {}))
    prev = daily.get(today)
    if not prev or any(prev.get(k) != v for k, v in snap.items()):
        daily[today] = {**snap, "at": at}
    new = {"product": PRODUCT, **snap, "daily": dict(sorted(daily.items())), "clones": kept, "releases": rel_list}
    if not MARKETPLACE_ITEM:
        new.pop("marketplace")
        for v in new["daily"].values():
            v.pop("marketplace", None)
    return new, at


# ------------------------------------------------------------------------------------------- chart
W, H = 820, 320
BG, EDGE, WHITE, GRAY, DIM, LINE, GOLD = "#000000", "#1f1f1f", "#ffffff", "#8a8a8a", "#555555", "#2a2a2a", "#e6c56b"
FONT = ("-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', 'Hiragino Sans', 'Hiragino Kaku Gothic ProN', "
        "'Noto Sans CJK JP', 'Noto Sans JP', sans-serif")


def texts(lang, st):
    parts_ja, parts_en = [], []
    if st.get("releases"):
        parts_ja.append("リリースのダウンロード"); parts_en.append("release downloads")
    if "marketplace" in st:
        parts_ja.append("Marketplace のインストール"); parts_en.append("Marketplace installs")
    parts_ja.append("git clone"); parts_en.append("git clones")
    if st.get("site_source") or any(v.get("site_source") for v in st.get("daily", {}).values()):
        parts_ja.append("auralune.tech からのソースの zip"); parts_en.append("source zips from auralune.tech")
    return {
        "ja": {"title": f"{st['product']} のダウンロード・インストール（累計）", "sub": "・".join(parts_ja) + " · 毎日自動で更新",
               "total": "累計", "site": "うち auralune.tech 経由 {n}", "legend_t": "累計", "legend_s": "auralune.tech 経由",
               "foot": "更新 {date} UTC · 記録は {start} から（それより前の分は最初の点に含む）", "empty": "まだ記録がありません"},
        "en": {"title": f"{st['product']} downloads and installs (running total)", "sub": ", ".join(parts_en) + " · updated daily",
               "total": "Total", "site": "via auralune.tech {n}", "legend_t": "Total", "legend_s": "via auralune.tech",
               "foot": "Updated {date} UTC · recorded since {start} (earlier ones are in the first point)", "empty": "No records yet"},
    }[lang]


def chart(st, lang):
    t = texts(lang, st)
    days = sorted(st.get("daily", {}))
    X0, X1, Y0, Y1 = 40, W - 40, 128, H - 70
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(t["title"])}">',
         f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="14" fill="{BG}" stroke="{EDGE}"/>',
         f'<g font-family="{escape(FONT)}">',
         f'<text x="32" y="44" fill="{WHITE}" font-size="19" font-weight="600">{escape(t["title"])}</text>',
         f'<text x="32" y="68" fill="{GRAY}" font-size="12">{escape(t["sub"])}</text>',
         f'<text x="{W - 32}" y="30" fill="{GRAY}" font-size="12" text-anchor="end">{escape(t["total"])}</text>',
         f'<text x="{W - 32}" y="64" fill="{WHITE}" font-size="34" font-weight="700" text-anchor="end">{st["total"]:,}</text>',
         f'<text x="{W - 32}" y="86" fill="{GOLD}" font-size="12" text-anchor="end">{escape(t["site"].format(n=format(st.get("site", 0), ",")))}</text>']
    if not days:
        o.append(f'<text x="{W / 2}" y="{(Y0 + Y1) / 2}" fill="{GRAY}" font-size="14" text-anchor="middle">{escape(t["empty"])}</text>')
    else:
        d0 = dt.date.fromisoformat(days[0])
        d1 = max(dt.date.fromisoformat(days[-1]), d0 + dt.timedelta(days=13))
        span = (d1 - d0).days or 1
        top = max(1, max(st["daily"][d]["total"] for d in days))
        step = 10 ** max(0, len(str(top)) - 1)
        top = ((top + step - 1) // step) * step if top > 5 else 5
        x = lambda d: X0 + (X1 - X0) * (dt.date.fromisoformat(d) - d0).days / span
        y = lambda v: Y1 - (Y1 - Y0) * v / top
        for frac in (0, 0.5, 1):
            yy = y(top * frac)
            o.append(f'<line x1="{X0}" x2="{X1}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="{LINE}" stroke-width="1"/>')
            o.append(f'<text x="{X0 - 8}" y="{yy + 4:.1f}" fill="{DIM}" font-size="11" text-anchor="end">{int(top * frac):,}</text>')

        def path(key):
            return [(x(d), y(st["daily"][d].get(key, 0))) for d in days]

        tot = path("total")
        area = f"M{tot[0][0]:.1f},{Y1} " + " ".join(f"L{a:.1f},{b:.1f}" for a, b in tot) + f" L{tot[-1][0]:.1f},{Y1} Z"
        o.append(f'<path d="{area}" fill="{WHITE}" fill-opacity="0.08"/>')
        o.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in tot)}" fill="none" stroke="{WHITE}" stroke-width="2"/>')
        sit = path("site")
        o.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in sit)}" fill="none" stroke="{GOLD}" stroke-width="2"/>')
        for a, b in tot:
            o.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="2.6" fill="{WHITE}"/>')
        for a, b in sit:
            o.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="2.4" fill="{GOLD}"/>')
        o.append(f'<text x="{X0}" y="{Y1 + 18}" fill="{DIM}" font-size="11">{d0.isoformat()}</text>')
        o.append(f'<text x="{X1}" y="{Y1 + 18}" fill="{DIM}" font-size="11" text-anchor="end">{d1.isoformat()}</text>')
        lx = X0
        o.append(f'<rect x="{lx}" y="{H - 34}" width="14" height="3" fill="{WHITE}"/><text x="{lx + 20}" y="{H - 29}" fill="{GRAY}" font-size="11">{escape(t["legend_t"])}</text>')
        lx += 20 + 7 * len(t["legend_t"]) + 40
        o.append(f'<rect x="{lx}" y="{H - 34}" width="14" height="3" fill="{GOLD}"/><text x="{lx + 20}" y="{H - 29}" fill="{GRAY}" font-size="11">{escape(t["legend_s"])}</text>')
        upd = st.get("updated", "")[:16].replace("T", " ")
        o.append(f'<text x="{X1}" y="{H - 29}" fill="{DIM}" font-size="10.5" text-anchor="end">{escape(t["foot"].format(date=upd, start=days[0]))}</text>')
    o.append("</g></svg>")
    return "\n".join(o) + "\n"


# ------------------------------------------------------------------------------------------- write
def write(new, tok):
    try:
        head = gh(f"git/ref/heads/{BRANCH}", tok)["object"]["sha"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        tree = gh("git/trees", tok, data={"tree": [{"path": "README.md", "mode": "100644", "type": "blob",
               "content": "Data for the README's download badges and chart (scripts/download-stats.py, .github/workflows/stats.yml).\n"}]}, method="POST")["sha"]
        c = gh("git/commits", tok, data={"message": "Start the download stats branch", "tree": tree, "parents": []}, method="POST")["sha"]
        gh("git/refs", tok, data={"ref": f"refs/heads/{BRANCH}", "sha": c}, method="POST")
        head = c
    base = gh(f"git/commits/{head}", tok)["tree"]["sha"]
    files = {"stats.json": json.dumps(new, ensure_ascii=False, indent=2) + "\n",
             "downloads-ja.svg": chart(new, "ja"), "downloads-en.svg": chart(new, "en")}
    tree = gh("git/trees", tok, data={"base_tree": base, "tree": [
        {"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in files.items()]}, method="POST")["sha"]
    msg = f"Download stats: {new['total']} (via auralune.tech {new['site']})"
    c = gh("git/commits", tok, data={"message": msg, "tree": tree, "parents": [head]}, method="POST")["sha"]
    gh(f"git/refs/heads/{BRANCH}", tok, data={"sha": c}, method="PATCH")


def main():
    args = set(sys.argv[1:])
    if not REPO:
        sys.exit("Set STATS_REPO (owner/name) or run in GitHub Actions")
    tok = token()
    try:
        old = json.loads(gh(f"contents/stats.json?ref={BRANCH}", tok, raw=True, headers={"Accept": "application/vnd.github.raw"}))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        old = {}
    new, at = count(old, tok)
    if "--dry-run" in args:
        print(json.dumps({"updated": at, **new}, ensure_ascii=False, indent=2))
        return
    same = {k: v for k, v in old.items() if k != "updated"} == new
    if same and "--force" not in args:
        print(f"No change: total {new['total']}, via auralune.tech {new['site']}")
        return
    write({"updated": at, **new}, tok)
    print(f"Written: total {new['total']}, via auralune.tech {new['site']}")


if __name__ == "__main__":
    main()
