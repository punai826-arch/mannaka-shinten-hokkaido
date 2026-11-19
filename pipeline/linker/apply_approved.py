"""候補一覧で「承認」に○を付けた行を pipeline/overrides.csv に反映する

- 承認 ○ … instagram・公式サイト・食べログのリンクを反映（空欄のセルは反映しない。間違ったセルは消してから○）
- 承認 × … 3つのリンクをすべて出さない（overrides.csv に - を入れる）。一部だけ止めたいときは overrides.csv のそのセルに - を書く
自動紐づけはこの作業なしでもサイトに出ます。これは間違いを直すときだけ使います。

使い方: python pipeline/linker/apply_approved.py [候補一覧.csv ...]
        ファイルを指定しないと pipeline/out/link_candidates_*.csv をすべて読みます。
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OVERRIDES = ROOT / "pipeline" / "overrides.csv"
FIELDS = ["id", "instagram", "website", "tabelog", "genre", "pr", "hide", "memo"]
NG_FIELDS = {"photo", "photoSrc", "vibe"}  # 画像まわりは使わない（著作権のおそれ）
YES = {"○", "〇", "◯", "o", "O", "1", "y", "Y", "yes", "ok", "OK", "はい"}
NO = {"×", "x", "X", "✕", "0", "n", "no", "いいえ"}


def read_rows(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:  # Excelの「CSV（コンマ区切り）」保存はShift_JIS
        text = path.read_text(encoding="cp932")
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]


def main():
    files = [Path(a) for a in sys.argv[1:]] or sorted((ROOT / "pipeline" / "out").glob("link_candidates_*.csv"))
    if not files:
        sys.exit("候補一覧（link_candidates_*.csv）が見つかりません。")

    ov = {r["id"]: r for r in read_rows(OVERRIDES)} if OVERRIDES.exists() else {}
    today = dt.date.today().isoformat()
    n_ok = n_no = 0
    for path in files:  # 古い順に読むので、新しい判断で上書きされる
        for r in read_rows(path):
            mark = r.get("承認", "")
            if mark not in YES and mark not in NO:
                continue
            o = ov.setdefault(r["id"], {k: "" for k in FIELDS} | {"id": r["id"]})
            memo = [m for m in o.get("memo", "").split(" / ") if m and not m.startswith("紐づけ")]
            if mark in YES:
                if r.get("instagram"):
                    o["instagram"] = r["instagram"].lstrip("@")
                if r.get("公式サイト"):
                    o["website"] = r["公式サイト"]
                if r.get("食べログ"):
                    o["tabelog"] = r["食べログ"]
                memo.append(f"紐づけ承認 {today}（{r.get('店名', '')}）")
                n_ok += 1
            elif mark in NO:
                o["instagram"] = o["website"] = o["tabelog"] = "-"
                memo.append(f"紐づけなし確認 {today}（{r.get('店名', '')}）")
                n_no += 1
            o["memo"] = " / ".join(memo)

    with OVERRIDES.open("w", encoding="utf-8-sig", newline="") as f:
        extra = sorted({k for o in ov.values() for k in o if k and k not in FIELDS and k not in NG_FIELDS})
        w = csv.DictWriter(f, fieldnames=FIELDS + extra, extrasaction="ignore")
        w.writeheader()
        for o in ov.values():
            w.writerow({k: o.get(k, "") for k in FIELDS + extra})
    print(f"反映しました：承認 {n_ok}件、紐づけなし {n_no}件 → {OVERRIDES}")
    print("サイトに出すには run.bat（または build_hokkaido.py）をもう一度実行してください。")


if __name__ == "__main__":
    main()
