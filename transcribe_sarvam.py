"""
Transcribe call recordings (e.g. the sample calls) with Sarvam batch speech-to-text.

What it does
  - Sends the .mp3 files in audited_recordings/ to Sarvam in batches of 20
  - Asks for speaker separation (bot vs buyer) and timestamps
  - Saves, per call:
        transcripts/json/<key>.json   raw Sarvam output (keep this)
        transcripts/text/<key>.txt    readable version: [mm:ss] S0: ...
  - Writes transcripts/summary.csv with one row per call
  - Skips calls that are already done, so you can safely re-run it

Before running (PowerShell):
  pip install sarvamai
  $env:SARVAM_API_KEY = "paste-your-key-here"

Test on 3 calls first:
  python transcribe_sarvam.py --limit 3
Then run everything:
  python transcribe_sarvam.py
"""
import argparse
import csv
import glob
import json
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sarvamai import SarvamAI

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(HERE, "audited_recordings")
OUT_JSON = os.path.join(HERE, "transcripts", "json")
OUT_TEXT = os.path.join(HERE, "transcripts", "text")
SUMMARY = os.path.join(HERE, "transcripts", "summary.csv")
BATCH_SIZE = 20  # Sarvam maximum per job


def mmss(sec):
    sec = int(round(sec or 0))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def to_text(data):
    """Turn Sarvam JSON into readable lines. Returns (text, stats)."""
    entries = (data.get("diarized_transcript") or {}).get("entries") or []
    lines, gaps = [], []
    prev_end = None
    if entries:
        for e in entries:
            start, end = e.get("start_time_seconds", 0), e.get("end_time_seconds", 0)
            if prev_end is not None:
                gaps.append(start - prev_end)
            prev_end = end
            lines.append(f"[{mmss(start)}] S{e.get('speaker_id', '?')}: {e.get('transcript', '').strip()}")
    else:  # no speaker labels: fall back to timed chunks
        ts = data.get("timestamps") or {}
        for chunk, start, end in zip(ts.get("words") or ts.get("chunks") or [],
                                     ts.get("start_time_seconds") or [],
                                     ts.get("end_time_seconds") or []):
            if prev_end is not None:
                gaps.append(start - prev_end)
            prev_end = end
            lines.append(f"[{mmss(start)}] {str(chunk).strip()}")
        if not lines and data.get("transcript"):
            lines.append(data["transcript"])
    stats = {
        "turns": len(lines),
        "speakers": len({e.get("speaker_id") for e in entries}) if entries else 0,
        "last_end_sec": round(prev_end or 0, 1),
        "longest_gap_sec": round(max(gaps), 1) if gaps else 0,
        "language": data.get("language_code", ""),
    }
    return "\n".join(lines), stats


def save(key, raw_path):
    with open(raw_path, encoding="utf-8") as f:
        data = json.load(f)
    shutil.copyfile(raw_path, os.path.join(OUT_JSON, f"{key}.json"))
    text, stats = to_text(data)
    with open(os.path.join(OUT_TEXT, f"{key}.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return stats


def run_batch(client, files, args, batch_no):
    """Run one Sarvam job for up to 20 files. Returns list of (key, status, stats_or_error)."""
    results = []
    for attempt in (1, 2):  # one retry for the whole batch
        try:
            job = client.speech_to_text_job.create_job(
                model=args.model,
                mode=args.mode,
                language_code=args.lang,
                with_diarization=True,
                with_timestamps=True,
                num_speakers=2,
            )
            job.upload_files(file_paths=files, timeout=180)
            job.start()
            job.wait_until_complete(poll_interval=10, timeout=1800)
            fr = job.get_file_results()
            tmp = tempfile.mkdtemp(prefix=f"sarvam_b{batch_no}_")
            try:
                job.download_outputs(output_dir=tmp)
            except Exception as e:  # some outputs may still have downloaded
                print(f"  batch {batch_no}: download warning: {e}")
            for f in files:
                key = os.path.splitext(os.path.basename(f))[0]
                raw = os.path.join(tmp, os.path.basename(f) + ".json")
                if os.path.exists(raw):
                    results.append((key, "ok", save(key, raw)))
                else:
                    err = next((x.get("error_message") for x in fr.get("failed", [])
                                if key in str(x.get("file_name"))), "no output returned")
                    results.append((key, "failed", err))
            shutil.rmtree(tmp, ignore_errors=True)
            return results
        except Exception as e:
            print(f"  batch {batch_no}: attempt {attempt} failed: {e}")
            if attempt == 2:
                return [(os.path.splitext(os.path.basename(f))[0], "failed", str(e)) for f in files]
            time.sleep(15)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--set", default="audited", choices=["audited", "provided"],
                   help="audited = audited_recordings -> transcripts/ ; provided = provided_recordings (a second, unaudited sample) -> transcripts_provided/")
    p.add_argument("--limit", type=int, default=0, help="only process this many calls (for a test run)")
    p.add_argument("--workers", type=int, default=3, help="batches running at the same time")
    p.add_argument("--model", default="saaras:v4", help="saaras:v4 (recommended) or saaras:v3")
    p.add_argument("--mode", default="codemix",
                   help="codemix (Hinglish as spoken), translit (all in Roman letters), transcribe, translate")
    p.add_argument("--lang", default="hi-IN", help="hi-IN, en-IN, or unknown (auto-detect)")
    args = p.parse_args()
    global AUDIO_DIR, OUT_JSON, OUT_TEXT, SUMMARY
    if args.set == "provided":
        AUDIO_DIR = os.path.join(HERE, "provided_recordings")
        base = os.path.join(HERE, "transcripts_provided")
        OUT_JSON, OUT_TEXT, SUMMARY = os.path.join(base, "json"), os.path.join(base, "text"), os.path.join(base, "summary.csv")
        if not os.path.isdir(AUDIO_DIR):
            sys.exit("Folder provided_recordings not found. Put the .mp3 files in provided_recordings/")

    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        sys.exit('SARVAM_API_KEY is not set. In PowerShell run:  $env:SARVAM_API_KEY = "your-key"')
    os.makedirs(OUT_JSON, exist_ok=True)
    os.makedirs(OUT_TEXT, exist_ok=True)

    all_files = sorted(glob.glob(os.path.join(AUDIO_DIR, "*.mp3")))
    todo = [f for f in all_files
            if not os.path.exists(os.path.join(OUT_TEXT, os.path.splitext(os.path.basename(f))[0] + ".txt"))]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(all_files)} recordings found, {len(todo)} to transcribe now "
          f"(model={args.model}, mode={args.mode}, lang={args.lang})")
    if not todo:
        return

    client = SarvamAI(api_subscription_key=key)
    batches = [todo[i:i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(run_batch, client, b, args, i + 1): i + 1 for i, b in enumerate(batches)}
        for fut in as_completed(futs):
            res = fut.result()
            ok = sum(1 for r in res if r[1] == "ok")
            print(f"batch {futs[fut]}/{len(batches)} done: {ok}/{len(res)} ok  ({int(time.time() - t0)}s elapsed)")
            rows.extend(res)

    # append to summary.csv
    new_file = not os.path.exists(SUMMARY)
    with open(SUMMARY, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["key", "status", "turns", "speakers", "last_end_sec", "longest_gap_sec", "language", "error"])
        for k, status, info in rows:
            if status == "ok":
                w.writerow([k, status, info["turns"], info["speakers"], info["last_end_sec"],
                            info["longest_gap_sec"], info["language"], ""])
            else:
                w.writerow([k, status, "", "", "", "", "", info])

    ok = sum(1 for r in rows if r[1] == "ok")
    print(f"\nFinished in {int(time.time() - t0)}s: {ok} ok, {len(rows) - ok} failed.")
    print(f"Readable transcripts: {OUT_TEXT}")
    if len(rows) - ok:
        print("Re-run the same command to retry the failed ones (finished calls are skipped).")


if __name__ == "__main__":
    main()
